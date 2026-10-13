"""Test penyusunan & pengiriman rekap closing ke API eksternal (TODO Fase 8.4).

Kontrak: docs/usulan-kontrak-kirim-closing.md. Keputusan: TODO.md Fase 8.0.
HTTP client diganti tiruan — perilaku HTTP-nya diuji di test_closing_export_client.py.
"""

import uuid
from datetime import date, timedelta

import pytest

from app.config import settings
from app.core.time import utcnow
from app.models.closing_report import ClosingExportLog, ClosingMenuProduct
from app.services import closing_export_client, closing_export_service
from app.services.closing_export_client import HasilKirim
from tests.unit.test_routes_closing import HARI_INI, KEMARIN, item, jual, kirim_closing, petakan

ADMIN = "admin@maharasa.id"


@pytest.fixture(autouse=True)
def konfigurasi(monkeypatch):
    monkeypatch.setattr(settings, "CLOSING_EXPORT_URL", "https://api.contoh.id/closing-totals")
    monkeypatch.setattr(settings, "CLOSING_EXPORT_TOKEN", "token-uji")
    monkeypatch.setattr(settings, "CLOSING_EXPORT_TIMEOUT", 3.0)
    monkeypatch.setattr(settings, "CLOSING_EXPORT_MAX_RETRIES", 1)


class ApiTiruan:
    def __init__(self):
        self.hasil = []
        self.panggilan = []

    def __call__(self, payload, **opsi):
        self.panggilan.append((payload, opsi))
        if self.hasil:
            return self.hasil.pop(0)
        return HasilKirim(status="terkirim", http_status=201, response_body='{"ok":true}', error=None, attempts=1)


@pytest.fixture()
def api(monkeypatch):
    tiruan = ApiTiruan()
    monkeypatch.setattr(closing_export_client, "kirim", tiruan)
    return tiruan


def siapkan(db, outlet="OUTLET_001"):
    """Satu menu terpetakan + satu produk POS tanpa menu, siap dikirim.

    Mapping berlaku untuk semua outlet — hanya dibuat sekali.
    """
    kirim_closing(db, outlet=outlet, items=[item(sold=10, waste=1, adjustment=-1, compensation=2)])
    if not db.query(ClosingMenuProduct).count():
        petakan(db, "SU-001", 200104)
    jual(db, 1, 200104, 3, outlet=outlet)
    jual(db, 2, 300001, 2, outlet=outlet, nama="Ocha Dingin")


def jadi_mengirim(db, log, menit_lalu=0):
    """Log `mengirim` yang dimulai `menit_lalu`; lewat BATAS_MACET = macet."""
    log.status = "mengirim"
    log.started_at = utcnow() - timedelta(minutes=menit_lalu)
    db.commit()


MACET = closing_export_service.BATAS_MACET.total_seconds() / 60 + 1


def gagal(kode=500, attempts=2):
    return HasilKirim(status="gagal", http_status=kode, response_body="error", error=f"HTTP {kode}", attempts=attempts)


# ---------------------------------------------------------------------------
# Isi payload
# ---------------------------------------------------------------------------


class TestPayload:

    def test_isi_sesuai_kontrak(self, db_session, api):
        siapkan(db_session)

        log = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        payload, opsi = api.panggilan[0]
        assert payload["messageId"] == str(log.message_id)
        assert payload["sequence"] == 1
        assert payload["sentAt"].endswith("Z")
        assert payload["outlet"] == {"code": "OUTLET_001"}
        assert payload["productionDate"] == "2026-10-02"
        assert payload["items"] == [
            {
                "source": "closing",
                "menuId": str(uuid.uuid5(uuid.NAMESPACE_URL, "SU-001")),
                "menuCode": "SU-001",
                "menuName": "Salmon Nigiri",
                "productId": None,
                "productName": None,
                "colorplateSold": 10,
                "posQty": 3,
                "totalSold": 13,
                "waste": 1,
                "adjustment": -1,
                "compensation": 2,
            },
            {
                "source": "pos_only",
                "menuId": None,
                "menuCode": None,
                "menuName": None,
                "productId": 300001,
                "productName": "Ocha Dingin",
                "colorplateSold": 0,
                "posQty": 2,
                "totalSold": 2,
                "waste": 0,
                "adjustment": 0,
                "compensation": 0,
            },
        ]
        assert opsi == {
            "message_id": str(log.message_id),
            "url": "https://api.contoh.id/closing-totals",
            "token": "token-uji",
            "timeout": 3.0,
            "max_retries": 1,
        }

    def test_menu_terpetakan_tidak_terjual_pos_nol(self, db_session, api):
        kirim_closing(db_session, items=[item(sold=4)])
        petakan(db_session, "SU-001", 200104)

        closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        (baris,) = api.panggilan[0][0]["items"]
        assert (baris["posQty"], baris["totalSold"]) == (0, 4)

    def test_qty_pos_tanpa_pengali(self, db_session, api):
        kirim_closing(db_session, items=[item(sold=1)])
        petakan(db_session, "SU-001", 200104, multiplier=3)
        jual(db_session, 1, 200104, 2)

        closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        (baris,) = api.panggilan[0][0]["items"]
        assert (baris["posQty"], baris["totalSold"]) == (2, 3)

    def test_qty_pos_pecahan_tetap_desimal(self, db_session, api):
        kirim_closing(db_session, items=[item(sold=1)])
        petakan(db_session, "SU-001", 200104)
        jual(db_session, 1, 200104, 1.5)

        closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        (baris,) = api.panggilan[0][0]["items"]
        assert (baris["posQty"], baris["totalSold"]) == (1.5, 2.5)

    def test_transaksi_void_tidak_pernah_dihitung(self, db_session, api):
        kirim_closing(db_session, items=[item(sold=1)])
        petakan(db_session, "SU-001", 200104)
        jual(db_session, 1, 200104, 5, deleted=1)

        closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        assert api.panggilan[0][0]["items"][0]["posQty"] == 0

    def test_hanya_outlet_dan_tanggal_yang_diminta(self, db_session, api):
        kirim_closing(db_session, items=[item(production_date=HARI_INI), item("SU-002", "Tuna", production_date=KEMARIN)])
        kirim_closing(db_session, outlet="OUTLET_002", items=[item()])
        petakan(db_session, "SU-001", 200104)
        petakan(db_session, "SU-002", 200105)

        closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        assert [b["menuCode"] for b in api.panggilan[0][0]["items"]] == ["SU-001"]


# ---------------------------------------------------------------------------
# Penolakan sebelum kirim
# ---------------------------------------------------------------------------


class TestDitolak:

    def test_belum_dikonfigurasi(self, db_session, api, monkeypatch):
        siapkan(db_session)
        monkeypatch.setattr(settings, "CLOSING_EXPORT_TOKEN", "")

        with pytest.raises(closing_export_service.BelumDikonfigurasi):
            closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)
        assert api.panggilan == []

    def test_tanpa_closing(self, db_session, api):
        jual(db_session, 1, 200104, 3)

        with pytest.raises(closing_export_service.TidakAdaClosing):
            closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

    def test_menu_belum_dipetakan_diblokir(self, db_session, api):
        kirim_closing(db_session, items=[item(), item("SU-002", "Tuna")])
        petakan(db_session, "SU-001", 200104)

        with pytest.raises(closing_export_service.Diblokir) as exc:
            closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        assert [m.menu_code for m in exc.value.blokir.menu_belum_dipetakan] == ["SU-002"]
        assert exc.value.blokir.produk_dobel == []
        assert api.panggilan == []
        assert db_session.query(ClosingExportLog).count() == 0

    def test_produk_dipetakan_ke_dua_menu_diblokir(self, db_session, api):
        kirim_closing(db_session, items=[item(), item("SU-002", "Tuna")])
        petakan(db_session, "SU-001", 200104)
        petakan(db_session, "SU-002", 200104)
        petakan(db_session, "SU-002", 200105)
        jual(db_session, 1, 200104, 3)

        with pytest.raises(closing_export_service.Diblokir) as exc:
            closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        (dobel,) = exc.value.blokir.produk_dobel
        assert (dobel.product_id, dobel.product_name, dobel.menus) == (200104, "Salmon HR", ["SU-001", "SU-002"])

    def test_produk_dua_menu_di_tanggal_lain_tidak_memblokir(self, db_session, api):
        kirim_closing(db_session, items=[item(production_date=HARI_INI), item("SU-002", "Tuna", production_date=KEMARIN)])
        petakan(db_session, "SU-001", 200104)
        petakan(db_session, "SU-002", 200104)

        closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        assert len(api.panggilan) == 1

    def test_mapping_nonaktif_tidak_dihitung_dobel(self, db_session, api):
        kirim_closing(db_session, items=[item(), item("SU-002", "Tuna")])
        petakan(db_session, "SU-001", 200104)
        petakan(db_session, "SU-002", 200104, is_active=False)
        petakan(db_session, "SU-002", 200105)

        closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        assert len(api.panggilan) == 1

    def test_kiriman_sebelumnya_masih_berjalan(self, db_session, api):
        siapkan(db_session)
        api.hasil = [gagal()]
        log = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)
        jadi_mengirim(db_session, log)

        with pytest.raises(closing_export_service.SedangDikirim):
            closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

    def test_kiriman_macet_ditandai_gagal_lalu_digantikan(self, db_session, api):
        """Proses mati di tengah kiriman: status tertinggal `mengirim` selamanya."""
        siapkan(db_session)
        macet = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)
        jadi_mengirim(db_session, macet, menit_lalu=MACET)

        baru = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        db_session.refresh(macet)
        assert (macet.status, macet.error) == ("gagal", closing_export_service.PESAN_MACET)
        assert macet.finished_at is not None
        assert (baru.sequence, baru.status) == (2, "terkirim")


# ---------------------------------------------------------------------------
# Log & sequence
# ---------------------------------------------------------------------------


class TestLog:

    def test_hasil_terkirim_dicatat(self, db_session, api):
        siapkan(db_session)

        log = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        db_session.expire_all()
        log = db_session.get(ClosingExportLog, log.id)
        assert (log.outlet_code, log.production_date, log.sequence) == ("OUTLET_001", HARI_INI, 1)
        assert (log.status, log.http_status, log.attempts, log.error) == ("terkirim", 201, 1, None)
        assert log.response_body == '{"ok":true}'
        assert log.item_count == 2
        assert log.sent_by == ADMIN
        assert log.started_at is not None
        assert log.finished_at is not None
        assert len(log.content_hash) == 64
        assert log.payload == api.panggilan[0][0]

    def test_hasil_gagal_dicatat(self, db_session, api):
        siapkan(db_session)
        api.hasil = [gagal(503, attempts=2)]

        log = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        assert (log.status, log.http_status, log.attempts, log.error) == ("gagal", 503, 2, "HTTP 503")

    def test_sequence_naik_per_outlet_dan_tanggal(self, db_session, api):
        siapkan(db_session)
        siapkan(db_session, outlet="OUTLET_002")

        a = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)
        b = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)
        c = closing_export_service.kirim(db_session, "OUTLET_002", HARI_INI, ADMIN)

        assert (a.sequence, b.sequence, c.sequence) == (1, 2, 1)
        assert a.message_id != b.message_id

    def test_hash_sama_untuk_isi_sama(self, db_session, api):
        siapkan(db_session)

        a = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)
        b = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        assert a.content_hash == b.content_hash


# ---------------------------------------------------------------------------
# Kirim ulang log yang gagal
# ---------------------------------------------------------------------------


class TestKirimUlang:

    def test_payload_dan_message_id_sama(self, db_session, api):
        siapkan(db_session)
        api.hasil = [gagal(attempts=2)]
        log = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        hasil = closing_export_service.kirim_ulang(db_session, log.id)

        assert hasil.id == log.id
        assert api.panggilan[1][0] == api.panggilan[0][0]
        assert api.panggilan[1][1]["message_id"] == str(log.message_id)
        assert (hasil.status, hasil.attempts, hasil.http_status, hasil.error) == ("terkirim", 3, 201, None)
        assert db_session.query(ClosingExportLog).count() == 1

    def test_log_mengirim_yang_macet_boleh_diulang(self, db_session, api):
        siapkan(db_session)
        log = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)
        jadi_mengirim(db_session, log, menit_lalu=MACET)
        sebelum = log.started_at

        hasil = closing_export_service.kirim_ulang(db_session, log.id)

        assert hasil.status == "terkirim"
        assert hasil.started_at > sebelum

    def test_yang_masih_berjalan_tidak_diulang(self, db_session, api):
        """Mengulang kiriman yang belum selesai = request kedua ke API tujuan."""
        siapkan(db_session)
        log = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)
        jadi_mengirim(db_session, log)

        with pytest.raises(closing_export_service.TidakBisaDiulang, match="sedang berjalan"):
            closing_export_service.kirim_ulang(db_session, log.id)

    @pytest.mark.parametrize("status", ["terkirim", "duplikat"])
    def test_yang_sudah_sampai_tidak_diulang(self, db_session, api, status):
        siapkan(db_session)
        log = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)
        log.status = status
        db_session.commit()

        with pytest.raises(closing_export_service.TidakBisaDiulang):
            closing_export_service.kirim_ulang(db_session, log.id)

    def test_yang_sudah_digantikan_kiriman_baru_tidak_diulang(self, db_session, api):
        """API tujuan akan menolak sequence lama — kirim yang baru saja."""
        siapkan(db_session)
        api.hasil = [gagal()]
        lama = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)
        closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        with pytest.raises(closing_export_service.TidakBisaDiulang):
            closing_export_service.kirim_ulang(db_session, lama.id)

    def test_tidak_ada(self, db_session, api):
        with pytest.raises(closing_export_service.LogTidakDitemukan):
            closing_export_service.kirim_ulang(db_session, 999)

    def test_belum_dikonfigurasi(self, db_session, api, monkeypatch):
        siapkan(db_session)
        api.hasil = [gagal()]
        log = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)
        monkeypatch.setattr(settings, "CLOSING_EXPORT_URL", "")

        with pytest.raises(closing_export_service.BelumDikonfigurasi):
            closing_export_service.kirim_ulang(db_session, log.id)


# ---------------------------------------------------------------------------
# Status per outlet × tanggal
# ---------------------------------------------------------------------------


class TestStatus:

    def _status(self, db, **filter_):
        return {(s.outlet_code, s.production_date): s for s in closing_export_service.status_pasangan(db, **filter_)}

    def test_belum_dikirim(self, db_session, api):
        siapkan(db_session)

        (s,) = self._status(db_session).values()

        assert (s.outlet_code, s.production_date, s.status, s.can_send) == ("OUTLET_001", HARI_INI, "belum_dikirim", True)
        assert (s.item_count, s.total_sold) == (2, 15)
        assert s.last_attempt is None and s.last_sent is None

    def test_terkirim_lalu_closing_direvisi_perlu_kirim_ulang(self, db_session, api):
        siapkan(db_session)
        terkirim = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        s = self._status(db_session)[("OUTLET_001", HARI_INI)]
        assert (s.status, s.last_sent.id, s.last_attempt.id) == ("terkirim", terkirim.id, terkirim.id)

        jual(db_session, 3, 200104, 1)

        assert self._status(db_session)[("OUTLET_001", HARI_INI)].status == "perlu_kirim_ulang"

    def test_duplikat_dihitung_sudah_sampai(self, db_session, api):
        siapkan(db_session)
        api.hasil = [HasilKirim(status="duplikat", http_status=409, response_body=None, error=None, attempts=1)]
        closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        assert self._status(db_session)[("OUTLET_001", HARI_INI)].status == "terkirim"

    def test_gagal_setelah_terkirim(self, db_session, api):
        siapkan(db_session)
        sampai = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)
        api.hasil = [gagal()]
        gagal_ = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)

        s = self._status(db_session)[("OUTLET_001", HARI_INI)]

        assert (s.status, s.last_sent.id, s.last_attempt.id, s.last_attempt.status) == (
            "terkirim",
            sampai.id,
            gagal_.id,
            "gagal",
        )

    def test_diblokir_tidak_bisa_dikirim(self, db_session, api):
        kirim_closing(db_session, items=[item()])

        s = self._status(db_session)[("OUTLET_001", HARI_INI)]

        assert s.can_send is False
        assert [m.menu_code for m in s.menu_belum_dipetakan] == ["SU-001"]

    def test_sedang_mengirim_tidak_bisa_dikirim(self, db_session, api):
        siapkan(db_session)
        log = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)
        jadi_mengirim(db_session, log)

        assert self._status(db_session)[("OUTLET_001", HARI_INI)].can_send is False

    def test_kiriman_macet_tidak_menghalangi(self, db_session, api):
        siapkan(db_session)
        log = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)
        jadi_mengirim(db_session, log, menit_lalu=MACET)

        assert self._status(db_session)[("OUTLET_001", HARI_INI)].can_send is True

    def test_filter_outlet_dan_tanggal(self, db_session, api):
        kirim_closing(db_session, items=[item(production_date=HARI_INI), item("SU-002", "Tuna", production_date=KEMARIN)])
        kirim_closing(db_session, outlet="OUTLET_002", items=[item()])

        semua = self._status(db_session)
        sebagian = self._status(db_session, outlet="OUTLET_001", start_date=HARI_INI, end_date=HARI_INI)

        assert set(semua) == {("OUTLET_001", HARI_INI), ("OUTLET_001", KEMARIN), ("OUTLET_002", HARI_INI)}
        assert set(sebagian) == {("OUTLET_001", HARI_INI)}

    def test_urut_tanggal_terbaru_dulu(self, db_session, api):
        kirim_closing(db_session, items=[item(production_date=KEMARIN), item("SU-002", "Tuna", production_date=HARI_INI)])

        hasil = closing_export_service.status_pasangan(db_session)

        assert [s.production_date for s in hasil] == [HARI_INI, KEMARIN]


# ---------------------------------------------------------------------------
# Riwayat
# ---------------------------------------------------------------------------


def test_riwayat_terbaru_dulu_dengan_filter(db_session, api):
    siapkan(db_session)
    siapkan(db_session, outlet="OUTLET_002")
    a = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)
    api.hasil = [gagal()]
    b = closing_export_service.kirim(db_session, "OUTLET_001", HARI_INI, ADMIN)
    c = closing_export_service.kirim(db_session, "OUTLET_002", HARI_INI, ADMIN)

    rows, total = closing_export_service.list_logs(db_session)
    assert ([r.id for r in rows], total) == ([c.id, b.id, a.id], 3)

    rows, total = closing_export_service.list_logs(db_session, outlet="OUTLET_001", status="gagal")
    assert ([r.id for r in rows], total) == ([b.id], 1)

    rows, total = closing_export_service.list_logs(db_session, start_date=date(2026, 10, 3))
    assert total == 0

    rows, total = closing_export_service.list_logs(db_session, limit=1, offset=1)
    assert ([r.id for r in rows], total) == ([b.id], 3)
