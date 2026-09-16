"""Test app/services/product_group_service.py — mapping product group (Fase 6).

Tabel `product_group_mappings` menentukan group mana yang dipublish ke
RabbitMQ. Aturan yang dijaga di sini:

- nama disimpan dalam bentuk normal (trim + huruf besar), jadi `colorplate `
  dan `COLORPLATE` tidak bisa jadi dua baris;
- tidak ada penghapusan — group dimatikan lewat `is_active`, barisnya tetap ada.
"""

import pytest

from app.models.product_group_mapping import ProductGroupMapping
from app.services import product_group_service as svc


class TestNormalisasi:

    @pytest.mark.parametrize(
        "mentah, normal",
        [
            ("COLORPLATE", "COLORPLATE"),
            (" colorplate ", "COLORPLATE"),
            (" PROMO BANDUNG", "PROMO BANDUNG"),
            ("Promo Bandung", "PROMO BANDUNG"),
            ("   ", ""),
            ("", ""),
            (None, ""),
        ],
    )
    def test_trim_dan_huruf_besar(self, mentah, normal):
        assert svc.normalize_product_group(mentah) == normal


class TestCreateMapping:

    def test_disimpan_dalam_bentuk_normal(self, db_session):
        row = svc.create_mapping(db_session, " food ")

        assert row.id is not None
        assert row.product_group == "FOOD"
        assert row.is_active is True

    def test_bisa_dibuat_dalam_keadaan_nonaktif(self, db_session):
        row = svc.create_mapping(db_session, "FOOD", is_active=False)

        assert row.is_active is False

    def test_duplikat_beda_kapitalisasi_ditolak(self, db_session):
        svc.create_mapping(db_session, "COLORPLATE")

        with pytest.raises(svc.GroupSudahAda):
            svc.create_mapping(db_session, " colorplate")

    def test_duplikat_tidak_menambah_baris(self, db_session):
        svc.create_mapping(db_session, "COLORPLATE")

        with pytest.raises(svc.GroupSudahAda):
            svc.create_mapping(db_session, "COLORPLATE")

        assert db_session.query(ProductGroupMapping).count() == 1

    @pytest.mark.parametrize("nama", ["", "   ", None])
    def test_nama_kosong_ditolak(self, db_session, nama):
        with pytest.raises(svc.DataTidakValid):
            svc.create_mapping(db_session, nama)

    def test_nama_melebihi_kolom_ditolak(self, db_session):
        """Kolom `Group` di orderdetail hanya 255 karakter — lebih dari itu tidak akan pernah cocok."""
        with pytest.raises(svc.DataTidakValid):
            svc.create_mapping(db_session, "X" * 256)


class TestSetActive:

    def test_menonaktifkan(self, db_session):
        row = svc.create_mapping(db_session, "FOOD")

        hasil = svc.set_active(db_session, row.id, False)

        assert hasil.is_active is False
        assert hasil.updated_at is not None

    def test_mengaktifkan_kembali(self, db_session):
        row = svc.create_mapping(db_session, "FOOD", is_active=False)

        assert svc.set_active(db_session, row.id, True).is_active is True

    def test_baris_tidak_dihapus(self, db_session):
        row = svc.create_mapping(db_session, "FOOD")

        svc.set_active(db_session, row.id, False)

        assert db_session.query(ProductGroupMapping).count() == 1

    def test_id_tidak_dikenal(self, db_session):
        with pytest.raises(svc.GroupTidakDitemukan):
            svc.set_active(db_session, 999, False)

    def test_service_tidak_menyediakan_penghapusan(self):
        """Keputusan sadar: mapping dimatikan, tidak pernah dihapus."""
        assert not [nama for nama in dir(svc) if "delete" in nama.lower() or "hapus" in nama.lower()]


class TestDaftar:

    def test_list_mappings_memuat_yang_nonaktif_dan_terurut(self, db_session):
        svc.create_mapping(db_session, "FOOD")
        svc.create_mapping(db_session, "BEVERAGE", is_active=False)
        svc.create_mapping(db_session, "COLORPLATE")

        assert [r.product_group for r in svc.list_mappings(db_session)] == ["BEVERAGE", "COLORPLATE", "FOOD"]

    def test_get_active_groups_hanya_yang_aktif(self, db_session):
        svc.create_mapping(db_session, "FOOD")
        svc.create_mapping(db_session, "BEVERAGE", is_active=False)
        svc.create_mapping(db_session, "COLORPLATE")

        assert svc.get_active_groups(db_session) == ["COLORPLATE", "FOOD"]

    def test_get_active_groups_kosong(self, db_session):
        assert svc.get_active_groups(db_session) == []
