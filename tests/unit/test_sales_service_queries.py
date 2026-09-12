"""Test query baca SalesService — get_sales & get_sales_colorplate.

Dijalankan di atas SQLite in-memory: kedua fungsi hanya memakai konstruksi
SQL standar (filter / join / group_by), tidak ada dialek PostgreSQL.
"""

from datetime import date

import pytest

from app.services.sales_service import SalesService


@pytest.fixture()
def seeded(db_session, sale_factory, item_factory):
    """Dua outlet, tiga tanggal, campuran produk COLORPLATE dan non-COLORPLATE."""
    db_session.add_all(
        [
            sale_factory(transaction_id=1, outlet_code="OUTLET_001", sale_date=date(2026, 1, 10)),
            sale_factory(transaction_id=2, outlet_code="OUTLET_001", sale_date=date(2026, 1, 15)),
            sale_factory(transaction_id=3, outlet_code="OUTLET_002", sale_date=date(2026, 1, 15)),
            sale_factory(transaction_id=4, outlet_code="OUTLET_002", sale_date=date(2026, 1, 20)),
        ]
    )
    db_session.add_all(
        [
            # OUTLET_001 / 10 Jan — RED 2
            item_factory(order_detail_id=1, transaction_id=1, product_name="RED", qty=2, sale_date=date(2026, 1, 10)),
            # OUTLET_001 / 15 Jan — RED 3 + RED 1 (dua baris, harus ter-SUM jadi 4)
            item_factory(order_detail_id=1, transaction_id=2, product_name="RED", qty=3, sale_date=date(2026, 1, 15)),
            item_factory(order_detail_id=2, transaction_id=2, product_name="RED", qty=1, sale_date=date(2026, 1, 15)),
            # OUTLET_001 / 15 Jan — BLUE 5
            item_factory(order_detail_id=3, transaction_id=2, product_name="BLUE", qty=5, sale_date=date(2026, 1, 15)),
            # OUTLET_002 / 15 Jan — RED 7
            item_factory(order_detail_id=1, transaction_id=3, product_name="RED", qty=7, sale_date=date(2026, 1, 15)),
            # non-COLORPLATE, tidak boleh ikut terhitung
            item_factory(
                order_detail_id=4,
                transaction_id=2,
                product_group="FOOD",
                product_name="NASI GORENG",
                qty=99,
                sale_date=date(2026, 1, 15),
            ),
            item_factory(
                order_detail_id=1,
                transaction_id=4,
                product_group="DRINK",
                product_name="ES TEH",
                qty=50,
                sale_date=date(2026, 1, 20),
            ),
        ]
    )
    db_session.commit()
    return db_session


class TestGetSales:

    def test_tanpa_filter_mengembalikan_semua_baris(self, seeded):
        result = SalesService.get_sales(db=seeded)

        assert len(result) == 4

    def test_database_kosong_mengembalikan_list_kosong(self, db_session):
        result = SalesService.get_sales(db=db_session)

        assert result == []

    def test_filter_outlet(self, seeded):
        result = SalesService.get_sales(db=seeded, outlet="OUTLET_001")

        assert len(result) == 2
        assert {r.outlet_code for r in result} == {"OUTLET_001"}

    def test_filter_rentang_tanggal_inklusif_di_kedua_ujung(self, seeded):
        result = SalesService.get_sales(
            db=seeded,
            start_date=date(2026, 1, 10),
            end_date=date(2026, 1, 15),
        )

        assert len(result) == 3

    def test_start_date_lebih_besar_dari_end_date_mengembalikan_kosong(self, seeded):
        """Harus list kosong, bukan exception."""
        result = SalesService.get_sales(
            db=seeded,
            start_date=date(2026, 12, 31),
            end_date=date(2026, 1, 1),
        )

        assert result == []

    def test_outlet_tanpa_data_mengembalikan_kosong(self, seeded):
        result = SalesService.get_sales(db=seeded, outlet="OUTLET_TIDAK_ADA")

        assert result == []

    def test_terurut_dari_transaksi_terbaru(self, seeded):
        """Urutan harus deterministik, kalau tidak pagination bisa melewatkan baris."""
        result = SalesService.get_sales(db=seeded)

        tanggal = [r.sale_date for r in result]
        assert tanggal == sorted(tanggal, reverse=True)


class TestGetSalesPagination:

    def test_limit_default_membatasi_hasil(self, db_session, sale_factory):
        db_session.add_all([sale_factory(transaction_id=i) for i in range(1, 60)])
        db_session.commit()

        result = SalesService.get_sales(db=db_session)

        assert len(result) == SalesService.DEFAULT_LIMIT

    def test_limit_eksplisit_dipatuhi(self, seeded):
        result = SalesService.get_sales(db=seeded, limit=2)

        assert len(result) == 2

    def test_offset_melewati_baris_awal(self, seeded):
        halaman_1 = SalesService.get_sales(db=seeded, limit=2, offset=0)
        halaman_2 = SalesService.get_sales(db=seeded, limit=2, offset=2)

        id_1 = {r.transaction_id for r in halaman_1}
        id_2 = {r.transaction_id for r in halaman_2}
        assert id_1.isdisjoint(id_2)
        assert len(id_1 | id_2) == 4

    def test_offset_melebihi_jumlah_data_mengembalikan_kosong(self, seeded):
        result = SalesService.get_sales(db=seeded, offset=100)

        assert result == []

    def test_limit_dibatasi_maksimum(self, db_session, sale_factory):
        """Klien tidak boleh bisa menarik seluruh tabel dengan limit raksasa."""
        db_session.add_all([sale_factory(transaction_id=i) for i in range(1, 10)])
        db_session.commit()

        result = SalesService.get_sales(db=db_session, limit=999999)

        assert len(result) <= SalesService.MAX_LIMIT

    @pytest.mark.parametrize("limit", [0, -1, -100])
    def test_limit_tidak_masuk_akal_dikembalikan_ke_default(self, seeded, limit):
        result = SalesService.get_sales(db=seeded, limit=limit)

        assert len(result) == 4

    def test_offset_negatif_dianggap_nol(self, seeded):
        result = SalesService.get_sales(db=seeded, offset=-5)

        assert len(result) == 4

    def test_count_sales_menghitung_seluruh_hasil_tanpa_limit(self, db_session, sale_factory):
        db_session.add_all([sale_factory(transaction_id=i) for i in range(1, 60)])
        db_session.commit()

        assert SalesService.count_sales(db=db_session) == 59

    def test_count_sales_menghormati_filter(self, seeded):
        assert SalesService.count_sales(db=seeded, outlet="OUTLET_001") == 2
        assert SalesService.count_sales(db=seeded, start_date=date(2026, 1, 15)) == 3


class TestGetSalesColorplate:

    def test_hanya_menghitung_product_group_colorplate(self, seeded):
        result = SalesService.get_sales_colorplate(db=seeded)

        names = {row.product_name for row in result}
        assert "NASI GORENG" not in names
        assert "ES TEH" not in names
        assert names == {"RED", "BLUE"}

    def test_sum_qty_ter_group_per_produk_outlet_tanggal(self, seeded):
        result = SalesService.get_sales_colorplate(db=seeded)

        grouped = {(r.product_name, r.outlet_code, r.sale_date): r.sold for r in result}

        # dua baris RED di transaksi 2 harus ter-SUM jadi 4
        assert grouped[("RED", "OUTLET_001", date(2026, 1, 15))] == 4
        assert grouped[("RED", "OUTLET_001", date(2026, 1, 10))] == 2
        assert grouped[("BLUE", "OUTLET_001", date(2026, 1, 15))] == 5
        assert grouped[("RED", "OUTLET_002", date(2026, 1, 15))] == 7

    def test_tidak_menggabungkan_outlet_berbeda(self, seeded):
        """RED pada 15 Jan ada di dua outlet — harus tetap dua baris terpisah."""
        result = SalesService.get_sales_colorplate(db=seeded, start_date=date(2026, 1, 15), end_date=date(2026, 1, 15))

        red_rows = [r for r in result if r.product_name == "RED"]
        assert len(red_rows) == 2
        assert {r.outlet_code for r in red_rows} == {"OUTLET_001", "OUTLET_002"}

    def test_filter_outlet(self, seeded):
        result = SalesService.get_sales_colorplate(db=seeded, outlet="OUTLET_001")

        assert {r.outlet_code for r in result} == {"OUTLET_001"}
        assert len(result) == 3  # RED 10Jan, RED 15Jan, BLUE 15Jan

    def test_filter_satu_tanggal(self, seeded):
        result = SalesService.get_sales_colorplate(db=seeded, start_date=date(2026, 1, 10), end_date=date(2026, 1, 10))

        assert len(result) == 1
        assert result[0].product_name == "RED"
        assert result[0].sold == 2

    def test_filter_outlet_dan_tanggal_bersamaan(self, seeded):
        result = SalesService.get_sales_colorplate(db=seeded, outlet="OUTLET_001", start_date=date(2026, 1, 15), end_date=date(2026, 1, 15))

        grouped = {r.product_name: r.sold for r in result}
        assert grouped == {"RED": 4, "BLUE": 5}

    def test_outlet_tanpa_data_mengembalikan_kosong(self, seeded):
        result = SalesService.get_sales_colorplate(db=seeded, outlet="OUTLET_TIDAK_ADA")

        assert result == []

    def test_tanggal_tanpa_data_mengembalikan_kosong(self, seeded):
        result = SalesService.get_sales_colorplate(db=seeded, start_date=date(2026, 6, 1), end_date=date(2026, 6, 1))

        assert result == []

    def test_join_tidak_menghasilkan_baris_ganda(self, seeded):
        """Join ke ordertransaction tidak boleh menggandakan hitungan."""
        result = SalesService.get_sales_colorplate(db=seeded)

        keys = [(r.product_name, r.outlet_code, r.sale_date) for r in result]
        assert len(keys) == len(set(keys))

    def test_item_tanpa_transaksi_induk_tidak_muncul(self, db_session, item_factory):
        """INNER JOIN — item yatim harus terbuang, bukan bikin baris tanpa outlet."""
        db_session.add(item_factory(transaction_id=999))
        db_session.commit()

        result = SalesService.get_sales_colorplate(db=db_session)

        assert result == []

    def test_baris_hasil_punya_kolom_yang_dipakai_publish(self, seeded):
        """Route publish membaca product_name, outlet_code, sale_date, sold."""
        row = SalesService.get_sales_colorplate(db=seeded, outlet="OUTLET_002", start_date=date(2026, 1, 15), end_date=date(2026, 1, 15))[0]

        assert row.product_name == "RED"
        assert row.outlet_code == "OUTLET_002"
        assert row.sale_date == date(2026, 1, 15)
        assert int(row.sold) == 7

    @pytest.mark.xfail(
        strict=True,
        reason="TODO 4.5 — transaksi void/Deleted=1 masih ikut terhitung; tentukan perilakunya dulu",
    )
    def test_transaksi_terhapus_tidak_ikut_dihitung(self, db_session, sale_factory, item_factory):
        db_session.add(sale_factory(transaction_id=1, deleted=1))
        db_session.add(item_factory(transaction_id=1, qty=5))
        db_session.commit()

        result = SalesService.get_sales_colorplate(db=db_session)

        assert result == []
