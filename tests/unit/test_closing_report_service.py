"""Test penyimpanan closing report (TODO Fase 7.3).

Tidak ada baris yang dihapus: kiriman ulang menjadi revisi baru, revisi lama
dimatikan lewat `is_current`.
"""

import copy
from datetime import datetime
from decimal import Decimal
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


def item_v1(menu_id=MENU_ID, menu_code="SU-001", menu_name="Salmon Nigiri", sold=42, waste=3):
    return {
        "menuId": menu_id,
        "menuCode": menu_code,
        "menuName": menu_name,
        "productionDate": "2026-10-02",
        "sold": sold,
        "waste": waste,
        "adjustment": 1,
        "compensation": 0,
    }


def item_v3(harga=15000, **ubah):
    item = item_v1(**ubah)
    waste = item["waste"]
    harga = Decimal(str(harga))
    item.update(
        wasteByCategory=[{"categoryCode": "DEFAULT_WASTE", "categoryName": "Default Waste", "quantity": waste}]
        if waste
        else [],
        unitPrice=str(harga),
        soldAmount=str(item["sold"] * harga),
        wasteAmount=str(waste * harga),
        adjustmentAmount=str(item["adjustment"] * harga),
        compensationAmount=0,
    )
    return item


def kirim_ulang_v3(db, items, sent_at="2026-11-23T10:00:00+07:00"):
    """Kiriman ulang historis (TODO 7.10): messageId `<closingReportId>.v3`."""
    event, raw = pesan(message_id=f"{REPORT_ID}.v3", sent_at=sent_at, items=items)
    raw["version"] = 3
    event = ClosingReportSubmitted.model_validate(raw)
    return simpan_closing_report(db, event, raw)


class TestKirimUlangHistorisV3:
    """TODO 7.10: laporan lama dikirim ulang sebagai v3 dengan messageId baru.

    Revisi v3 menggantikan seluruh item revisi v1; angka tidak dijumlah dua kali.
    """

    def test_v3_menjadi_revisi_aktif_dan_menggantikan_seluruh_item(self, db_session):
        # v1: Salmon + Tuna. v3: Salmon (angka baru) + Ebi; Tuna hilang.
        pertama = simpan(db_session, items=[item_v1(), item_v1(menu_id=MENU_ID_2, menu_code="SU-002", menu_name="Tuna")])
        ebi = "2c3d4e5f-6a7b-4c9d-8e1f-2a3b4c5d6e7f"
        hasil = kirim_ulang_v3(db_session, [item_v3(sold=40), item_v3(menu_id=ebi, menu_code="SU-003", menu_name="Ebi")])

        assert hasil.status is StatusSimpan.REVISI
        assert hasil.report_id == pertama.report_id
        aktif = revisi_aktif(db_session)
        assert (aktif.id, aktif.message_id, aktif.version) == (hasil.revision_id, f"{REPORT_ID}.v3", 3)
        assert sorted((str(i.menu_id), i.sold) for i in aktif.items) == sorted([(MENU_ID, 40), (ebi, 42)])
        # Revisi v1 tetap tersimpan, hanya tidak aktif.
        assert db_session.get(ClosingReportRevision, pertama.revision_id).is_current is False
        assert db_session.query(ClosingReportItem).count() == 4

    def test_harga_v3_tersimpan_di_item(self, db_session):
        simpan(db_session)
        kirim_ulang_v3(db_session, [item_v3(harga="12500.5", sold=2, waste=1)])

        [item] = revisi_aktif(db_session).items
        assert item.unit_price == Decimal("12500.50")
        assert (item.sold_amount, item.waste_amount) == (Decimal("25001.00"), Decimal("12500.50"))
        assert (item.adjustment_amount, item.compensation_amount) == (Decimal("12500.50"), Decimal("0"))

    def test_item_v1_tanpa_harga(self, db_session):
        simpan(db_session)

        [item] = revisi_aktif(db_session).items
        assert item.unit_price is None
        assert item.sold_amount is None

    def test_detail_dan_perbandingan_memakai_angka_v3_saja(self, db_session):
        simpan(db_session, items=[item_v1(), item_v1(menu_id=MENU_ID_2, menu_code="SU-002", menu_name="Tuna")])
        kirim_ulang_v3(db_session, [item_v3(sold=40)])

        detail = closing_report_service.get_report(db_session, UUID(REPORT_ID))
        assert [(i.menu_name, i.sold, i.unit_price) for i in detail["items"]] == [
            ("Salmon Nigiri", 40, Decimal("15000.00"))
        ]
        assert detail["item_count"] == 1

        baris = closing_report_service.compare_with_pos(db_session)
        assert [(b.menu_id, b.sold) for b in baris] == [(UUID(MENU_ID), 40)]

    def test_kiriman_ulang_dua_kali_tetap_duplikat(self, db_session):
        """Skrip kirim ulang yang dijalankan dua kali tidak membuat revisi baru."""
        simpan(db_session)
        pertama = kirim_ulang_v3(db_session, [item_v3()])
        kedua = kirim_ulang_v3(db_session, [item_v3(sold=1)], sent_at="2026-11-24T10:00:00+07:00")

        assert kedua.status is StatusSimpan.DUPLIKAT
        assert kedua.revision_id == pertama.revision_id
        assert [i.sold for i in revisi_aktif(db_session).items] == [42]

    def test_pesan_v1_tertunda_yang_tiba_belakangan_tidak_menimpa_v3(self, db_session):
        kirim_ulang_v3(db_session, [item_v3(sold=40)])
        lama = simpan(db_session, sold=99)

        assert lama.status is StatusSimpan.REVISI_LAMA
        assert [i.sold for i in revisi_aktif(db_session).items] == [40]

    def test_messageid_sama_dengan_versi_lebih_tinggi_tetap_duplikat(self, db_session):
        """Opsi B tidak dipakai: v3 dengan messageId lama dibuang tanpa efek."""
        simpan(db_session)
        event, raw = pesan(sent_at="2026-11-23T10:00:00+07:00", items=[item_v3(sold=40)])
        raw["version"] = 3
        hasil = simpan_closing_report(db_session, ClosingReportSubmitted.model_validate(raw), raw)

        assert hasil.status is StatusSimpan.DUPLIKAT
        assert [i.sold for i in revisi_aktif(db_session).items] == [42]


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


class TestWarnaPiringDariPesan:
    """`items[].plateColor` mengisi `closing_menus.platecolor` (Opsi A, kirim rekap ke ERP).

    Colorplate sumber kebenaran: warna pesan menimpa isian admin, kecuali menu
    itu sudah punya laporan aktif bertanggal lebih baru (kiriman ulang historis).
    """

    @pytest.fixture(autouse=True)
    def _warna_pos(self, monkeypatch):
        from app.services import product_menu_service

        self.dibaca = 0

        def list_colors(db):
            self.dibaca += 1
            return ["Blue", "Red"]

        monkeypatch.setattr(product_menu_service, "list_colors", list_colors)

    def kirim(self, db, warna, tanggal="2026-10-02", report_id=REPORT_ID, sent_at=None, menu_id=MENU_ID):
        item = item_v1(menu_id=menu_id)
        if warna is not None:
            item["plateColor"] = warna
        event, raw = pesan(items=[item], sent_at=sent_at)
        raw["messageId"] = raw["data"]["closingReportId"] = report_id
        raw["data"]["date"] = tanggal
        event = ClosingReportSubmitted.model_validate(raw)
        return simpan_closing_report(db, event, raw)

    def warna(self, db, menu_id=MENU_ID):
        menu = db.query(ClosingMenu).filter(ClosingMenu.menu_id == UUID(menu_id)).one()
        return menu.platecolor, menu.platecolor_by

    def test_menu_baru_langsung_berwarna_dengan_ejaan_pos(self, db_session):
        hasil = self.kirim(db_session, "red")

        assert self.warna(db_session) == ("Red", closing_report_service.WARNA_DARI_PESAN)
        assert hasil.warna_tidak_dikenal == []

    def test_warna_pesan_menimpa_isian_admin(self, db_session):
        self.kirim(db_session, None)
        menu = db_session.query(ClosingMenu).one()
        menu.platecolor, menu.platecolor_by = "Blue", "admin@maharasa.id"
        db_session.commit()

        self.kirim(db_session, "Red", sent_at="2026-10-03T08:00:00+07:00", report_id="7a1c2a9e-3b4d-4e5f-8a7b-9c0d1e2f3a4b")

        assert self.warna(db_session) == ("Red", closing_report_service.WARNA_DARI_PESAN)

    def test_tanpa_plate_color_warna_admin_tetap(self, db_session):
        self.kirim(db_session, None)
        menu = db_session.query(ClosingMenu).one()
        menu.platecolor, menu.platecolor_by = "Blue", "admin@maharasa.id"
        db_session.commit()

        self.kirim(db_session, None, report_id="7a1c2a9e-3b4d-4e5f-8a7b-9c0d1e2f3a4b")

        assert self.warna(db_session) == ("Blue", "admin@maharasa.id")

    def test_warna_tidak_dikenal_tidak_mengubah_menu(self, db_session):
        hasil = self.kirim(db_session, "Ungu")

        assert self.warna(db_session) == (None, None)
        assert hasil.warna_tidak_dikenal == ["Ungu"]

    def test_kiriman_ulang_tanggal_lama_tidak_menimpa_warna_baru(self, db_session):
        self.kirim(db_session, "Red", tanggal="2026-11-20")

        # Kiriman ulang historis: laporan Oktober tiba belakangan dengan warna lama.
        self.kirim(db_session, "Blue", tanggal="2026-10-02", report_id="7a1c2a9e-3b4d-4e5f-8a7b-9c0d1e2f3a4b")

        assert self.warna(db_session)[0] == "Red"

    def test_laporan_tanggal_lebih_baru_mengganti_warna(self, db_session):
        self.kirim(db_session, "Blue", tanggal="2026-10-02")
        self.kirim(db_session, "Red", tanggal="2026-11-20", report_id="7a1c2a9e-3b4d-4e5f-8a7b-9c0d1e2f3a4b")

        assert self.warna(db_session)[0] == "Red"

    def test_revisi_lama_tidak_mengubah_warna(self, db_session):
        self.kirim(db_session, "Red", sent_at="2026-10-03T08:00:00+07:00")
        event, raw = pesan(items=[{**item_v1(), "plateColor": "Blue"}], message_id="lama", sent_at="2026-10-02T08:00:00+07:00")
        event = ClosingReportSubmitted.model_validate(raw)

        assert simpan_closing_report(db_session, event, raw).status is StatusSimpan.REVISI_LAMA
        assert self.warna(db_session)[0] == "Red"

    def test_daftar_warna_pos_tidak_dibaca_kalau_warna_sama(self, db_session):
        self.kirim(db_session, "Red")
        self.kirim(db_session, "RED", report_id="7a1c2a9e-3b4d-4e5f-8a7b-9c0d1e2f3a4b")

        assert self.dibaca == 1
