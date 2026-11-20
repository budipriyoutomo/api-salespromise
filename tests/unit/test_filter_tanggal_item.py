"""Filter tanggal redundan di `orderdetail."SaleDate"` (TODO 9.13).

`get_top_products`, `get_sales_by_product_groups`, dan `get_sales_by_product_ids`
memfilter rentang di `ordertransaction."SaleDate"`. Tanpa filter yang sama di
sisi `orderdetail`, planner tidak bisa memakai `ix_orderdetail_saledate_outlet`
dan membaca `orderdetail` jauh melebihi rentangnya — di salinan produksi
(883 ribu baris) `top_products` sampai memindai seluruh tabel.

Filter ini hanya aman karena tanggal item = tanggal transaksinya (0 selisih di
salinan produksi 2026-11-20, `migrations/checks/saledate_konsisten.sql`).
Item yang tanggalnya berbeda dari transaksinya kini TIDAK ikut terhitung; test
di bawah membuktikan filternya benar-benar ada dengan memakai item seperti itu.
"""

from datetime import date

import pytest

from app.services.sales_service import SalesService

DALAM = date(2026, 1, 15)
LUAR = date(2026, 2, 20)


@pytest.fixture()
def item_beda_tanggal(db_session, sale_factory, item_factory):
    """Transaksi tanggal 15 Jan dengan dua item: satu bertanggal sama, satu
    (anomali) bertanggal 20 Feb."""
    db_session.add(sale_factory(transaction_id=1, outlet_code="OUTLET_001", sale_date=DALAM))
    db_session.flush()
    db_session.add_all(
        [
            item_factory(order_detail_id=1, transaction_id=1, sale_date=DALAM, product_id=101, product_name="RED", qty=2),
            item_factory(order_detail_id=2, transaction_id=1, sale_date=LUAR, product_id=102, product_name="BLUE", qty=5),
        ]
    )
    db_session.commit()
    return db_session


RENTANG = dict(start_date=date(2026, 1, 1), end_date=date(2026, 1, 31))


class TestRentangJugaMemfilterTanggalItem:

    def test_top_products(self, item_beda_tanggal):
        rows = SalesService.get_top_products(item_beda_tanggal, **RENTANG)

        assert [r.product_id for r in rows] == [101]

    def test_sales_by_product_groups(self, item_beda_tanggal):
        rows = SalesService.get_sales_by_product_groups(item_beda_tanggal, ["COLORPLATE"], **RENTANG)

        assert [r.product_name for r in rows] == ["RED"]

    def test_sales_by_product_ids(self, item_beda_tanggal):
        rows = SalesService.get_sales_by_product_ids(item_beda_tanggal, [101, 102], **RENTANG)

        assert [r.product_id for r in rows] == [101]

    @pytest.mark.parametrize(
        "rentang",
        [dict(start_date=date(2026, 1, 1)), dict(end_date=date(2026, 1, 31))],
        ids=["hanya_awal", "hanya_akhir"],
    )
    def test_batas_satu_sisi_juga_diterapkan(self, item_beda_tanggal, rentang):
        rows = SalesService.get_top_products(item_beda_tanggal, **rentang)

        # hanya_awal: BLUE (20 Feb) >= 1 Jan tetap ikut; hanya_akhir: BLUE > 31 Jan dibuang.
        harapan = {"start_date": {101, 102}, "end_date": {101}}[next(iter(rentang))]
        assert {r.product_id for r in rows} == harapan


class TestTanpaRentangTidakBerubah:

    def test_tanpa_tanggal_semua_item_ikut(self, item_beda_tanggal):
        assert {r.product_id for r in SalesService.get_top_products(item_beda_tanggal)} == {101, 102}
        assert {r.product_id for r in SalesService.get_sales_by_product_ids(item_beda_tanggal, [101, 102])} == {101, 102}
