"""Test penyimpanan closing report (TODO Fase 7.3).

Tidak ada baris yang dihapus: kiriman ulang menjadi revisi baru, revisi lama
dimatikan lewat `is_current`.
"""

import copy
from datetime import datetime
from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.api_key import ApiKey
from app.models.closing_report import (
    ClosingMenu,
    ClosingMenuProduct,
    ClosingReport,
    ClosingReportItem,
    ClosingReportRevision,
)
from app.schemas.closing_report_event import ClosingReportSubmitted
from app.services import closing_report_service
from app.services.closing_report_service import StatusSimpan, simpan_closing_report

REPORT_ID = "6f1c2a9e-3b4d-4e5f-8a7b-9c0d1e2f3a4b"
MENU_ID = "0a1b2c3d-4e5f-4a7b-8c9d-0e1f2a3b4c5d"
MENU_ID_2 = "1b2c3d4e-5f6a-4b8c-9d0e-1f2a3b4c5d6e"

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
                "menuId": MENU_ID,
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


def pesan(sent_at=None, message_id=None, outlet_name=None, sold=None, items=None, outlet_code=None):
    raw = copy.deepcopy(PAYLOAD)
    if sent_at:
        raw["sentAt"] = sent_at
    if message_id:
        raw["messageId"] = message_id
    if outlet_name:
        raw["data"]["outlet"]["name"] = outlet_name
    if outlet_code:
        raw["data"]["outlet"]["code"] = outlet_code
    if sold is not None:
        raw["data"]["items"][0]["sold"] = sold
    if items is not None:
        raw["data"]["items"] = items
    return ClosingReportSubmitted.model_validate(raw), raw


def simpan(db, **ubah):
    event, raw = pesan(**ubah)
    return simpan_closing_report(db, event, raw)


def revisi_aktif(db):
    return db.query(ClosingReportRevision).filter(ClosingReportRevision.is_current.is_(True)).one()


class TestLaporanBaru:

    def test_header_revisi_item_tersimpan(self, db_session):
        hasil = simpan(db_session)

        assert hasil.status is StatusSimpan.BARU
        laporan = db_session.query(ClosingReport).one()
        assert laporan.id == hasil.report_id
        assert laporan.closing_report_id == UUID(REPORT_ID)
        assert (laporan.outlet_code, laporan.outlet_name) == ("STTSM", "Maharasa PIK")
        assert (laporan.brand_code, laporan.brand_name) == ("MHR", "Maharasa")
        assert str(laporan.report_date) == "2026-10-02"

        revisi = revisi_aktif(db_session)
        assert revisi.id == hasil.revision_id
        assert revisi.message_id == REPORT_ID
        assert revisi.version == 1
        assert revisi.sent_at == datetime(2026, 10, 2, 15, 15)
        assert revisi.raw_payload == PAYLOAD

        item = db_session.query(ClosingReportItem).one()
        assert item.revision_id == revisi.id
        assert (item.menu_id, item.menu_code, item.menu_name) == (UUID(MENU_ID), "SU-001", "Salmon Nigiri")
        assert (item.sold, item.waste, item.adjustment, item.compensation) == (42, 3, 1, 0)

    def test_sudah_di_commit(self, db_session):
        simpan(db_session)
        db_session.rollback()

        assert db_session.query(ClosingReport).count() == 1

    def test_outlet_belum_terdaftar_tetap_disimpan(self, db_session):
        hasil = simpan(db_session)

        assert hasil.outlet_dikenal is False
        assert db_session.query(ClosingReport).count() == 1

    def test_outlet_terdaftar_dikenali(self, db_session):
        db_session.add(ApiKey(key_hash="h" * 64, outlet_code="STTSM"))
        db_session.commit()

        assert simpan(db_session).outlet_dikenal is True

    @pytest.mark.parametrize("kode_pengirim", ["sttsm", " Stt-SM ", "STT SM"])
    def test_kode_outlet_dicocokkan_setelah_normalisasi(self, db_session, kode_pengirim):
        """Jawaban pengirim: kodenya sama dengan POS setelah dinormalisasi, tidak
        dijamin sama huruf besar/kecilnya. Disimpan dengan kode POS supaya
        perbandingan dengan penjualan cukup mencocokkan persis."""
        db_session.add(ApiKey(key_hash="h" * 64, outlet_code="STTSM"))
        db_session.commit()

        hasil = simpan(db_session, outlet_code=kode_pengirim)

        assert hasil.outlet_dikenal is True
        assert db_session.query(ClosingReport).one().outlet_code == "STTSM"

    def test_kode_outlet_tidak_dikenal_disimpan_apa_adanya(self, db_session):
        simpan(db_session, outlet_code="Outlet-Baru")

        assert db_session.query(ClosingReport).one().outlet_code == "Outlet-Baru"


class TestKirimUlang:

    def test_retry_pengirim_dengan_sent_at_baru_tetap_duplikat(self, db_session):
        """Jawaban pengirim: sentAt diisi tiap percobaan kirim, isi identik."""
        pertama = simpan(db_session)
        retry = simpan(db_session, sent_at="2026-10-03T09:00:00+07:00")

        assert retry.status is StatusSimpan.DUPLIKAT
        assert retry.revision_id == pertama.revision_id
        assert db_session.query(ClosingReportRevision).count() == 1
        assert revisi_aktif(db_session).sent_at == datetime(2026, 10, 2, 15, 15)

    def test_pesan_yang_sama_diabaikan(self, db_session):
        """Redelivery RabbitMQ — messageId dan sentAt sama."""
        pertama = simpan(db_session)
        kedua = simpan(db_session)

        assert kedua.status is StatusSimpan.DUPLIKAT
        assert (kedua.report_id, kedua.revision_id) == (pertama.report_id, pertama.revision_id)
        assert db_session.query(ClosingReportRevision).count() == 1
        assert db_session.query(ClosingReportItem).count() == 1

    def test_revisi_lebih_baru_menjadi_aktif_tanpa_menghapus_yang_lama(self, db_session):
        pertama = simpan(db_session)
        kedua = simpan(
            db_session, message_id="kiriman-2", sent_at="2026-10-02T23:00:00+07:00", outlet_name="PIK Baru", sold=40
        )

        assert kedua.status is StatusSimpan.REVISI
        assert kedua.report_id == pertama.report_id
        assert db_session.query(ClosingReport).count() == 1
        assert db_session.query(ClosingReportRevision).count() == 2
        assert db_session.query(ClosingReportItem).count() == 2

        assert revisi_aktif(db_session).id == kedua.revision_id
        assert db_session.get(ClosingReportRevision, pertama.revision_id).is_current is False

        laporan = db_session.query(ClosingReport).one()
        assert laporan.outlet_name == "PIK Baru"
        assert laporan.updated_at is not None
        assert [i.sold for i in revisi_aktif(db_session).items] == [40]

    def test_revisi_dengan_message_id_berbeda_juga_diterima(self, db_session):
        simpan(db_session)
        hasil = simpan(db_session, message_id="kiriman-2", sent_at="2026-10-02T23:00:00+07:00")

        assert hasil.status is StatusSimpan.REVISI

    def test_message_id_lain_dengan_sent_at_sama_dianggap_revisi_terbaru(self, db_session):
        simpan(db_session)
        hasil = simpan(db_session, message_id="kiriman-2")

        assert hasil.status is StatusSimpan.REVISI
        assert revisi_aktif(db_session).message_id == "kiriman-2"

    def test_revisi_lebih_lama_disimpan_tapi_tidak_menimpa(self, db_session):
        """Usulan TODO 7.0: pesan yang tertunda tidak menimpa data yang lebih baru."""
        baru = simpan(db_session, message_id="kiriman-baru", sent_at="2026-10-02T23:00:00+07:00", sold=40)
        lama = simpan(db_session, message_id="kiriman-lama", outlet_name="Nama Lama", sold=99)

        assert lama.status is StatusSimpan.REVISI_LAMA
        assert revisi_aktif(db_session).id == baru.revision_id
        assert db_session.get(ClosingReportRevision, lama.revision_id).is_current is False
        assert db_session.query(ClosingReport).one().outlet_name == "Maharasa PIK"
        assert [i.sold for i in revisi_aktif(db_session).items] == [40]
        # Pesan pertama (messageId = closingReportId) ikut tersimpan sebagai revisi lama.
        assert db_session.query(ClosingReportRevision).count() == 2


class TestMenu:

    def test_menu_baru_tercatat_otomatis_belum_dipetakan(self, db_session):
        simpan(db_session)

        menu = db_session.query(ClosingMenu).one()
        assert (menu.menu_code, menu.menu_id, menu.menu_name) == ("SU-001", UUID(MENU_ID), "Salmon Nigiri")
        assert menu.brand_code == "MHR"
        assert menu.products == []

    def test_menu_dikenali_lewat_menu_id_walau_kodenya_berubah(self, db_session):
        """Jawaban pengirim: menuCode bisa diubah admin; menuId tetap."""
        simpan(db_session)
        item = copy.deepcopy(PAYLOAD["data"]["items"][0])
        item["menuCode"] = "SU-001B"
        simpan(db_session, message_id="kiriman-2", sent_at="2026-10-02T23:00:00+07:00", items=[item])

        menu = db_session.query(ClosingMenu).one()
        assert menu.menu_code == "SU-001B"

    def test_menu_tanpa_kode_tetap_tercatat(self, db_session):
        item = copy.deepcopy(PAYLOAD["data"]["items"][0])
        item["menuCode"] = None
        item["productionDate"] = None

        simpan(db_session, items=[item])

        assert db_session.query(ClosingMenu).one().menu_code is None
        stored = db_session.query(ClosingReportItem).one()
        assert (stored.menu_code, stored.production_date) == (None, None)

    def test_menu_yang_sama_tidak_dobel_dan_nama_ikut_terbaru(self, db_session):
        simpan(db_session)
        menu = db_session.query(ClosingMenu).one()
        db_session.add(ClosingMenuProduct(closing_menu_id=menu.id, product_id=200104))
        db_session.commit()

        item = copy.deepcopy(PAYLOAD["data"]["items"][0])
        item["menuName"] = "Salmon Nigiri (2 pcs)"
        simpan(db_session, message_id="kiriman-2", sent_at="2026-10-02T23:00:00+07:00", items=[item])
        db_session.expire_all()

        menu = db_session.query(ClosingMenu).one()
        assert menu.menu_name == "Salmon Nigiri (2 pcs)"
        assert menu.last_seen_at >= menu.first_seen_at
        # Mapping yang sudah dibuat admin tidak tersentuh.
        assert [p.product_id for p in menu.products] == [200104]

    def test_revisi_lama_tidak_mengubah_nama_menu(self, db_session):
        simpan(db_session, message_id="kiriman-baru", sent_at="2026-10-02T23:00:00+07:00")
        item = copy.deepcopy(PAYLOAD["data"]["items"][0])
        item["menuName"] = "Nama Lama"
        simpan(db_session, message_id="kiriman-lama", items=[item])

        assert db_session.query(ClosingMenu).one().menu_name == "Salmon Nigiri"

    def test_beberapa_menu_dan_tanggal_produksi(self, db_session):
        satu = copy.deepcopy(PAYLOAD["data"]["items"][0])
        kemarin = dict(satu, productionDate="2026-10-01", sold=0, waste=2)
        dua = dict(satu, menuId=MENU_ID_2, menuCode="SU-002", menuName="Tuna Nigiri")

        simpan(db_session, items=[satu, kemarin, dua])

        assert db_session.query(ClosingReportItem).count() == 3
        assert sorted(m.menu_code for m in db_session.query(ClosingMenu).all()) == ["SU-001", "SU-002"]

    def test_kode_menu_sama_menu_id_beda_jadi_dua_menu(self, db_session):
        """menuCode tidak unik lintas brand — dua menuId tetap dua menu."""
        satu = copy.deepcopy(PAYLOAD["data"]["items"][0])
        dua = dict(satu, menuId=MENU_ID_2)

        simpan(db_session, items=[satu, dua])

        assert db_session.query(ClosingMenu).count() == 2


class TestBalapan:

    def test_integrity_error_sekali_diulang(self, db_session, monkeypatch):
        """Dua consumer menyimpan laporan / menu yang sama bersamaan."""
        asli = closing_report_service._simpan
        panggilan = []

        def gagal_sekali(db, event, raw):
            panggilan.append(1)
            if len(panggilan) == 1:
                raise IntegrityError("insert", {}, Exception("balapan"))
            return asli(db, event, raw)

        monkeypatch.setattr(closing_report_service, "_simpan", gagal_sekali)

        hasil = simpan(db_session)

        assert hasil.status is StatusSimpan.BARU
        assert len(panggilan) == 2

    def test_integrity_error_berulang_diteruskan(self, db_session, monkeypatch):
        def selalu_gagal(db, event, raw):
            raise IntegrityError("insert", {}, Exception("rusak"))

        monkeypatch.setattr(closing_report_service, "_simpan", selalu_gagal)

        with pytest.raises(IntegrityError):
            simpan(db_session)
        assert db_session.query(ClosingReport).count() == 0
