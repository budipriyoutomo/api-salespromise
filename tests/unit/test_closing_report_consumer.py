"""Test worker consumer closing report (TODO Fase 7.4).

Broker tidak disentuh — channel pika di-mock. Penyimpanan memakai SQLite.
"""

import copy
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.consumers import closing_report_consumer as consumer
from app.consumers.closing_report_consumer import Keputusan, proses_pesan
from app.core.request_context import get_request_id
from app.models.closing_report import ClosingReport, ClosingReportRevision
from app.services.closing_report_service import HasilSimpan, StatusSimpan

REPORT_ID = "6f1c2a9e-3b4d-4e5f-8a7b-9c0d1e2f3a4b"

PAYLOAD = {
    "event": "closingreport.submitted",
    "version": 1,
    "messageId": REPORT_ID,
    "sentAt": "2026-10-02T22:15:00+07:00",
    "data": {
        "closingReportId": REPORT_ID,
        "date": "2026-10-02",
        "outlet": {"code": "STTSM", "name": "Maharasa PIK"},
        "brand": {"code": "MHR", "name": "Maharasa"},
        "items": [
            {
                "menuId": "0a1b2c3d-4e5f-4a7b-8c9d-0e1f2a3b4c5d",
                "menuCode": "SU-001",
                "menuName": "Salmon Nigiri",
                "productionDate": "2026-10-02",
                "sold": 42,
                "waste": 3,
                "adjustment": 1,
                "compensation": 0,
            }
        ],
    },
}

BODY = json.dumps(PAYLOAD).encode()

CONFIG = consumer.KonfigurasiConsumer(
    host="rabbit",
    port=5672,
    vhost="/",
    user="u",
    password="p",
    exchange="closing_exchange",
    routing_key="closingreport.submitted",
    queue="syncapi.closingreport",
    prefetch=1,
)


@pytest.fixture()
def factory(db_session):
    """Session factory yang selalu memberi session test yang sama."""
    db_session.close = MagicMock()  # consumer menutup session; data test tetap terbaca
    return lambda: db_session


class TestProsesPesan:

    def test_pesan_valid_disimpan_dan_di_ack(self, db_session, factory):
        assert proses_pesan(BODY, factory) is Keputusan.ACK

        assert db_session.query(ClosingReport).count() == 1
        assert db_session.query(ClosingReportRevision).one().raw_payload == PAYLOAD

    def test_session_selalu_ditutup(self, db_session, factory):
        proses_pesan(BODY, factory)

        db_session.close.assert_called_once()

    def test_pesan_duplikat_tetap_di_ack(self, db_session, factory):
        proses_pesan(BODY, factory)

        assert proses_pesan(BODY, factory) is Keputusan.ACK
        assert db_session.query(ClosingReportRevision).count() == 1

    @pytest.mark.parametrize("body", [b"bukan json", b"\xff\xfe", b"[1, 2]", b'"teks"', b""])
    def test_bukan_objek_json_ke_dlq(self, db_session, factory, body):
        assert proses_pesan(body, factory) is Keputusan.DLQ
        assert db_session.query(ClosingReport).count() == 0

    def test_gagal_validasi_ke_dlq_tanpa_menyentuh_db(self, db_session, factory):
        rusak = copy.deepcopy(PAYLOAD)
        rusak["version"] = 2

        assert proses_pesan(json.dumps(rusak).encode(), factory) is Keputusan.DLQ
        assert db_session.query(ClosingReport).count() == 0

    def test_database_putus_diulang_bukan_dibuang(self, factory, monkeypatch):
        """Datanya valid — tidak boleh masuk DLQ hanya karena DB sedang mati."""

        def putus(db, event, raw):
            raise OperationalError("SELECT 1", {}, Exception("server closed the connection"))

        monkeypatch.setattr(consumer, "simpan_closing_report", putus)

        assert proses_pesan(BODY, factory) is Keputusan.ULANGI

    @pytest.mark.parametrize(
        "error", [ProgrammingError("x", {}, Exception("kolom tidak ada")), RuntimeError("bug")]
    )
    def test_error_lain_ke_dlq(self, factory, monkeypatch, error):
        """Error yang tidak sembuh dengan diulang — supaya antrean tidak macet."""

        def gagal(db, event, raw):
            raise error

        monkeypatch.setattr(consumer, "simpan_closing_report", gagal)

        assert proses_pesan(BODY, factory) is Keputusan.DLQ

    def test_log_membawa_message_id_lalu_dibersihkan(self, factory, monkeypatch):
        terlihat = []

        def catat(db, event, raw):
            terlihat.append(get_request_id())
            return HasilSimpan(StatusSimpan.BARU, 1, 1, True)

        monkeypatch.setattr(consumer, "simpan_closing_report", catat)

        proses_pesan(BODY, factory)

        assert terlihat == [REPORT_ID]
        assert get_request_id() is None


class TestCallback:

    def _panggil(self, monkeypatch, keputusan):
        monkeypatch.setattr(consumer, "proses_pesan", lambda body, factory=None: keputusan)
        ch = MagicMock()
        method = SimpleNamespace(delivery_tag=7)
        consumer.on_message(ch, method, None, BODY)
        return ch

    def test_ack(self, monkeypatch):
        ch = self._panggil(monkeypatch, Keputusan.ACK)

        ch.basic_ack.assert_called_once_with(delivery_tag=7)
        ch.basic_nack.assert_not_called()

    def test_dlq_tanpa_requeue(self, monkeypatch):
        ch = self._panggil(monkeypatch, Keputusan.DLQ)

        ch.basic_nack.assert_called_once_with(delivery_tag=7, requeue=False)
        ch.basic_ack.assert_not_called()

    def test_ulangi_menunggu_dulu_lalu_requeue(self, monkeypatch):
        """Jeda lewat connection.sleep supaya heartbeat tetap terkirim."""
        ch = self._panggil(monkeypatch, Keputusan.ULANGI)

        ch.connection.sleep.assert_called_once_with(consumer.JEDA_ULANGI_DETIK)
        ch.basic_nack.assert_called_once_with(delivery_tag=7, requeue=True)


class TestTopologi:

    def test_exchange_pengirim_hanya_dicek_tidak_dibuat(self):
        ch = MagicMock()

        consumer.siapkan_channel(ch, CONFIG)

        ch.exchange_declare.assert_any_call(exchange="closing_exchange", passive=True)

    def test_queue_punya_dead_letter(self):
        ch = MagicMock()

        consumer.siapkan_channel(ch, CONFIG)

        ch.exchange_declare.assert_any_call(
            exchange="syncapi.closingreport.dlx", exchange_type="direct", durable=True
        )
        ch.queue_declare.assert_any_call(queue="syncapi.closingreport.dlq", durable=True)
        ch.queue_bind.assert_any_call(
            queue="syncapi.closingreport.dlq",
            exchange="syncapi.closingreport.dlx",
            routing_key="syncapi.closingreport",
        )
        ch.queue_declare.assert_any_call(
            queue="syncapi.closingreport",
            durable=True,
            arguments={
                "x-dead-letter-exchange": "syncapi.closingreport.dlx",
                "x-dead-letter-routing-key": "syncapi.closingreport",
            },
        )

    def test_queue_diikat_ke_exchange_pengirim_lalu_dikonsumsi(self):
        ch = MagicMock()

        consumer.siapkan_channel(ch, CONFIG)

        ch.queue_bind.assert_any_call(
            queue="syncapi.closingreport", exchange="closing_exchange", routing_key="closingreport.submitted"
        )
        ch.basic_qos.assert_called_once_with(prefetch_count=1)
        ch.basic_consume.assert_called_once_with(queue="syncapi.closingreport", on_message_callback=consumer.on_message)


class TestKonfigurasi:

    def test_dibaca_dari_settings(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "CLOSING_EXCHANGE", "ex")
        monkeypatch.setattr(settings, "CLOSING_ROUTING_KEY", "rk")
        monkeypatch.setattr(settings, "CLOSING_QUEUE", "q")
        monkeypatch.setattr(settings, "RABBITMQ_PORT", 5673)
        monkeypatch.setattr(settings, "RABBITMQ_VHOST", "maharasa")

        cfg = consumer.KonfigurasiConsumer.dari_settings()

        assert (cfg.exchange, cfg.routing_key, cfg.queue) == ("ex", "rk", "q")
        assert (cfg.host, cfg.port, cfg.vhost) == ("test-rabbit", 5673, "maharasa")
        assert cfg.password == "test-pass"

    def test_env_wajib_yang_kosong_dilaporkan(self, monkeypatch):
        from app.config import settings

        for nama in ["CLOSING_EXCHANGE", "CLOSING_ROUTING_KEY", "CLOSING_QUEUE", "RABBITMQ_PASSWORD"]:
            monkeypatch.setattr(settings, nama, "")

        with pytest.raises(consumer.KonfigurasiTidakLengkap) as exc:
            consumer.KonfigurasiConsumer.dari_settings()

        for nama in ["CLOSING_EXCHANGE", "CLOSING_ROUTING_KEY", "CLOSING_QUEUE", "RABBITMQ_PASSWORD"]:
            assert nama in str(exc.value)


class TestBerhenti:

    def test_stop_menghentikan_konsumsi(self):
        worker = consumer.Worker(CONFIG)
        worker.connection = MagicMock()
        worker.channel = MagicMock()

        worker.stop()

        assert worker.berhenti is True
        # Dijadwalkan lewat add_callback_threadsafe: aman dipanggil dari signal handler.
        callback = worker.connection.add_callback_threadsafe.call_args.args[0]
        callback()
        worker.channel.stop_consuming.assert_called_once()

    def test_stop_sebelum_terhubung_tidak_error(self):
        worker = consumer.Worker(CONFIG)

        worker.stop()

        assert worker.berhenti is True

    def test_koneksi_gagal_dicoba_lagi_dengan_jeda_naik(self, monkeypatch):
        import pika

        worker = consumer.Worker(CONFIG)
        jeda = []

        def gagal(*args, **kwargs):
            if len(jeda) == 3:
                worker.berhenti = True
            raise pika.exceptions.AMQPConnectionError("broker mati")

        monkeypatch.setattr(consumer, "skema_siap", lambda factory=None: True)
        monkeypatch.setattr(consumer.pika, "BlockingConnection", gagal)
        monkeypatch.setattr(consumer.time, "sleep", jeda.append)

        worker.run()

        assert jeda == sorted(jeda)
        assert jeda[0] < jeda[-1] <= consumer.JEDA_RECONNECT_MAKS


class TestTungguSkema:
    """Migrasi dijalankan container API. Consumer yang start lebih dulu tidak
    boleh membuang pesan ke DLQ hanya karena tabelnya belum dibuat."""

    def test_skema_siap_kalau_tabel_ada(self, db_session, factory):
        assert consumer.skema_siap(factory) is True

    def test_skema_belum_siap_kalau_tabel_belum_ada(self, db_session, factory):
        from app.models.closing_report import ClosingReportItem

        ClosingReportItem.__table__.drop(db_session.get_bind())

        assert consumer.skema_siap(factory) is False

    def test_database_mati_dianggap_belum_siap(self):
        def mati():
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

        assert consumer.skema_siap(mati) is False

    def test_worker_menunggu_skema_sebelum_terhubung_ke_broker(self, monkeypatch):
        worker = consumer.Worker(CONFIG)
        status = iter([False, False, True])
        jeda = []

        monkeypatch.setattr(consumer, "skema_siap", lambda factory=None: next(status))
        monkeypatch.setattr(consumer.time, "sleep", jeda.append)

        assert worker.tunggu_skema() is True
        assert jeda == [consumer.JEDA_CEK_SKEMA_DETIK] * 2

    def test_tunggu_skema_berhenti_saat_sigterm(self, monkeypatch):
        worker = consumer.Worker(CONFIG)

        def belum(factory=None):
            worker.berhenti = True
            return False

        monkeypatch.setattr(consumer, "skema_siap", belum)
        monkeypatch.setattr(consumer.time, "sleep", lambda s: None)

        assert worker.tunggu_skema() is False


class TestCompensationNegatif:
    """Pengirim belum memvalidasi compensation >= 0 per menu. Diputuskan
    2026-10-05: laporan tetap disimpan, consumer mencatat warning."""

    def test_disimpan_dan_dicatat(self, db_session, factory, caplog):
        janggal = copy.deepcopy(PAYLOAD)
        janggal["data"]["items"][0]["compensation"] = -2

        with caplog.at_level("WARNING", logger="sync-api"):
            assert proses_pesan(json.dumps(janggal).encode(), factory) is Keputusan.ACK

        assert db_session.query(ClosingReport).count() == 1
        peringatan = [r for r in caplog.records if "compensation negatif" in r.getMessage()]
        assert len(peringatan) == 1
        assert peringatan[0].menu_ids == ["0a1b2c3d-4e5f-4a7b-8c9d-0e1f2a3b4c5d"]

    def test_tanpa_nilai_negatif_tidak_ada_peringatan(self, factory, caplog):
        with caplog.at_level("WARNING", logger="sync-api"):
            proses_pesan(BODY, factory)

        assert not [r for r in caplog.records if "compensation negatif" in r.getMessage()]
