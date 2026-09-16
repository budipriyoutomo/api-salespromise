"""Test query laporan SalesService — ringkasan, time series, ranking, detail.

Semua dijalankan di SQLite in-memory: hanya SQL standar (agregat + group by).

CATATAN PERILAKU
----------------
Endpoint laporan MENGECUALIKAN transaksi `Deleted=1` — transaksi yang dibatalkan
bukan pendapatan. Ini berbeda dari `get_sales` dan `get_sales_colorplate` yang
masih ikut menghitungnya (lihat TODO 4.5, keputusan yang belum diambil).
Perbedaan itu disengaja: endpoint lama tidak diubah supaya angka yang sudah
dipublish ke RabbitMQ tidak berubah diam-diam.
"""

from datetime import date

import pytest

from app.services.sales_service import SalesService


@pytest.fixture()
def seeded(db_session, sale_factory, item_factory):
    """Dua outlet, empat transaksi, satu di antaranya sudah dihapus.

    `receipt_total_amount` sengaja diisi angka KECIL yang berbeda jauh dari
    `receipt_pay_price`. Kolom itu bukan uang — isinya jumlah item, terbukti
    di database produksi `ReceiptTotalAmount == sum(orderdetail.Amount)` pada
    14 dari 14 baris. Laporan yang salah menjumlahkannya akan menghasilkan
    omzet "Rp 20" dan bukan "Rp 600.000", tanpa error apa pun.

    Nilai keduanya dibuat berjauhan supaya kekeliruan kolom langsung terlihat
    sebagai test merah, bukan lolos diam-diam.
    """
    db_session.add_all(
        [
            sale_factory(
                transaction_id=1,
                outlet_code="OUTLET_001",
                sale_date=date(2026, 1, 10),
                receipt_pay_price=100000,
                receipt_total_amount=2,
                receipt_discount=10000,
            ),
            sale_factory(
                transaction_id=2,
                outlet_code="OUTLET_001",
                sale_date=date(2026, 1, 15),
                receipt_pay_price=200000,
                receipt_total_amount=17,
                receipt_discount=0,
            ),
            sale_factory(
                transaction_id=3,
                outlet_code="OUTLET_002",
                sale_date=date(2026, 1, 15),
                receipt_pay_price=300000,
                receipt_total_amount=1,
                receipt_discount=5000,
            ),
            # transaksi dibatalkan — tidak boleh ikut dihitung di laporan
            sale_factory(
                transaction_id=4,
                outlet_code="OUTLET_001",
                sale_date=date(2026, 1, 15),
                receipt_pay_price=999000,
                receipt_total_amount=500,
                deleted=1,
            ),
        ]
    )
    db_session.add_all(
        [
            item_factory(order_detail_id=1, transaction_id=1, product_id=101, product_name="RED", qty=2),
            item_factory(order_detail_id=1, transaction_id=2, product_id=101, product_name="RED", qty=3),
            item_factory(order_detail_id=2, transaction_id=2, product_id=102, product_name="BLUE", qty=10),
            item_factory(order_detail_id=1, transaction_id=3, product_id=101, product_name="RED", qty=1),
            item_factory(
                order_detail_id=3,
                transaction_id=2,
                product_id=201,
                product_group="FOOD",
                product_name="NASI",
                qty=4,
            ),
            # item milik transaksi terhapus
            item_factory(order_detail_id=1, transaction_id=4, product_id=101, product_name="RED", qty=500),
        ]
    )
    db_session.commit()
    return db_session


class TestGetSummary:

    def test_menghitung_jumlah_transaksi_dan_omzet(self, seeded):
        hasil = SalesService.get_summary(db=seeded)

        assert hasil["total_transactions"] == 3
        assert hasil["total_amount"] == 600000

    def test_transaksi_terhapus_tidak_ikut_dihitung(self, seeded):
        """Transaksi dibatalkan bukan pendapatan."""
        hasil = SalesService.get_summary(db=seeded)

        assert hasil["total_amount"] == 600000  # 999000 tidak ikut

    def test_rata_rata_per_struk(self, seeded):
        hasil = SalesService.get_summary(db=seeded)

        assert hasil["average_per_transaction"] == 200000

    def test_total_diskon(self, seeded):
        hasil = SalesService.get_summary(db=seeded)

        assert hasil["total_discount"] == 15000

    def test_filter_outlet(self, seeded):
        hasil = SalesService.get_summary(db=seeded, outlet="OUTLET_001")

        assert hasil["total_transactions"] == 2
        assert hasil["total_amount"] == 300000

    def test_filter_rentang_tanggal(self, seeded):
        hasil = SalesService.get_summary(db=seeded, start_date=date(2026, 1, 15), end_date=date(2026, 1, 15))

        assert hasil["total_transactions"] == 2
        assert hasil["total_amount"] == 500000

    def test_tanpa_data_mengembalikan_nol_bukan_none(self, db_session):
        """Frontend tidak boleh kebagian null lalu menampilkan 'NaN'."""
        hasil = SalesService.get_summary(db=db_session)

        assert hasil == {
            "total_transactions": 0,
            "total_amount": 0.0,
            "total_discount": 0.0,
            "average_per_transaction": 0.0,
        }

    def test_include_deleted_bisa_diaktifkan(self, seeded):
        hasil = SalesService.get_summary(db=seeded, include_deleted=True)

        assert hasil["total_transactions"] == 4
        assert hasil["total_amount"] == 1599000


class TestGetDailySales:

    def test_satu_baris_per_tanggal(self, seeded):
        hasil = SalesService.get_daily_sales(db=seeded)

        tanggal = [row.sale_date for row in hasil]
        assert tanggal == [date(2026, 1, 10), date(2026, 1, 15)]

    def test_terurut_menaik_untuk_grafik(self, seeded):
        """Grafik time series butuh urutan kronologis."""
        hasil = SalesService.get_daily_sales(db=seeded)

        tanggal = [row.sale_date for row in hasil]
        assert tanggal == sorted(tanggal)

    def test_menjumlahkan_omzet_per_tanggal(self, seeded):
        hasil = {row.sale_date: row.total_amount for row in SalesService.get_daily_sales(db=seeded)}

        assert hasil[date(2026, 1, 10)] == 100000
        assert hasil[date(2026, 1, 15)] == 500000

    def test_menghitung_jumlah_transaksi_per_tanggal(self, seeded):
        hasil = {row.sale_date: row.total_transactions for row in SalesService.get_daily_sales(db=seeded)}

        assert hasil[date(2026, 1, 10)] == 1
        assert hasil[date(2026, 1, 15)] == 2

    def test_filter_outlet(self, seeded):
        hasil = SalesService.get_daily_sales(db=seeded, outlet="OUTLET_002")

        assert len(hasil) == 1
        assert hasil[0].total_amount == 300000

    def test_tanpa_data_mengembalikan_list_kosong(self, db_session):
        assert SalesService.get_daily_sales(db=db_session) == []


class TestGetSalesByOutlet:

    def test_satu_baris_per_outlet(self, seeded):
        hasil = SalesService.get_sales_by_outlet(db=seeded)

        assert {row.outlet_code for row in hasil} == {"OUTLET_001", "OUTLET_002"}

    def test_menjumlahkan_omzet_per_outlet(self, seeded):
        hasil = {row.outlet_code: row.total_amount for row in SalesService.get_sales_by_outlet(db=seeded)}

        assert hasil["OUTLET_001"] == 300000
        assert hasil["OUTLET_002"] == 300000

    def test_terurut_dari_omzet_terbesar(self, seeded, sale_factory):
        seeded.add(
            sale_factory(
                transaction_id=9,
                outlet_code="OUTLET_003",
                receipt_pay_price=1000000,
                receipt_total_amount=3,
            )
        )
        seeded.commit()

        hasil = SalesService.get_sales_by_outlet(db=seeded)

        assert hasil[0].outlet_code == "OUTLET_003"

    def test_filter_rentang_tanggal(self, seeded):
        hasil = SalesService.get_sales_by_outlet(db=seeded, start_date=date(2026, 1, 10), end_date=date(2026, 1, 10))

        assert len(hasil) == 1
        assert hasil[0].outlet_code == "OUTLET_001"


class TestGetTopProducts:

    def test_terurut_dari_qty_terbanyak(self, seeded):
        hasil = SalesService.get_top_products(db=seeded)

        assert hasil[0].product_name == "BLUE"  # qty 10
        assert float(hasil[0].total_qty) == 10

    def test_menjumlahkan_qty_lintas_transaksi(self, seeded):
        hasil = {row.product_name: float(row.total_qty) for row in SalesService.get_top_products(db=seeded)}

        assert hasil["RED"] == 6  # 2 + 3 + 1, item transaksi terhapus tidak ikut

    def test_item_transaksi_terhapus_tidak_ikut(self, seeded):
        hasil = {row.product_name: float(row.total_qty) for row in SalesService.get_top_products(db=seeded)}

        assert hasil["RED"] != 506

    def test_limit_membatasi_jumlah_baris(self, seeded):
        hasil = SalesService.get_top_products(db=seeded, limit=1)

        assert len(hasil) == 1

    def test_filter_outlet(self, seeded):
        hasil = {
            row.product_name: float(row.total_qty)
            for row in SalesService.get_top_products(db=seeded, outlet="OUTLET_002")
        }

        assert hasil == {"RED": 1}

    def test_filter_product_group(self, seeded):
        hasil = SalesService.get_top_products(db=seeded, product_group="FOOD")

        assert len(hasil) == 1
        assert hasil[0].product_name == "NASI"

    def test_membawa_product_id_untuk_drilldown(self, seeded):
        hasil = SalesService.get_top_products(db=seeded, product_group="FOOD")

        assert hasil[0].product_id == 201

    def test_filter_product_group_tidak_peka_kapitalisasi_dan_spasi(self, seeded, item_factory):
        """Sama dengan `/by-group` (Fase 6 A4) — dropdown mengirim nama ter-normalisasi,
        sedangkan POS bisa menyimpan ` Food` apa adanya."""
        seeded.add(
            item_factory(order_detail_id=4, transaction_id=2, product_id=202, product_group=" Food", product_name="MIE", qty=1)
        )
        seeded.commit()

        hasil = SalesService.get_top_products(db=seeded, product_group="food ")

        assert {row.product_name for row in hasil} == {"NASI", "MIE"}

    def test_varian_nama_group_produk_yang_sama_digabung_satu_baris(self, seeded, item_factory):
        """Tanpa ini NASI muncul dua kali di ranking: sekali sebagai FOOD, sekali sebagai `food `."""
        seeded.add(
            item_factory(order_detail_id=2, transaction_id=3, product_id=201, product_group="food ", product_name="NASI", qty=2)
        )
        seeded.commit()

        nasi = [row for row in SalesService.get_top_products(db=seeded) if row.product_name == "NASI"]

        assert len(nasi) == 1
        assert nasi[0].product_group == "FOOD"
        assert float(nasi[0].total_qty) == 6

    def test_product_group_spasi_saja_dianggap_tanpa_filter(self, seeded):
        semua = SalesService.get_top_products(db=seeded)

        assert SalesService.get_top_products(db=seeded, product_group="   ") == semua

    def test_tanpa_data_mengembalikan_list_kosong(self, db_session):
        assert SalesService.get_top_products(db=db_session) == []


class TestGetSaleDetail:

    def test_mengembalikan_transaksi_beserta_itemnya(self, seeded):
        sale, items = SalesService.get_sale_detail(db=seeded, transaction_id=2, outlet="OUTLET_001")

        assert sale.transaction_id == 2
        assert len(items) == 3

    def test_transaksi_tidak_ada_mengembalikan_none(self, seeded):
        sale, items = SalesService.get_sale_detail(db=seeded, transaction_id=99999, outlet="OUTLET_001")

        assert sale is None
        assert items == []

    def test_outlet_lain_tidak_bisa_diambil(self, seeded):
        """TransactionID unik per outlet — outlet salah harus dianggap tidak ada."""
        sale, items = SalesService.get_sale_detail(db=seeded, transaction_id=3, outlet="OUTLET_001")

        assert sale is None

    def test_tanpa_outlet_mengambil_lintas_outlet(self, seeded):
        """Untuk admin yang tidak memfilter outlet."""
        sale, _ = SalesService.get_sale_detail(db=seeded, transaction_id=3, outlet=None)

        assert sale.outlet_code == "OUTLET_002"

    def test_item_hanya_milik_transaksi_itu(self, seeded):
        _, items = SalesService.get_sale_detail(db=seeded, transaction_id=1, outlet="OUTLET_001")

        assert len(items) == 1
        assert all(i.transaction_id == 1 for i in items)


class TestGetSyncStatus:

    def test_satu_baris_per_outlet(self, seeded):
        hasil = SalesService.get_sync_status(db=seeded)

        assert {row.outlet_code for row in hasil} == {"OUTLET_001", "OUTLET_002"}

    def test_membawa_tanggal_penjualan_terakhir(self, seeded):
        hasil = {row.outlet_code: row.last_sale_date for row in SalesService.get_sync_status(db=seeded)}

        assert hasil["OUTLET_001"] == date(2026, 1, 15)
        assert hasil["OUTLET_002"] == date(2026, 1, 15)

    def test_membawa_jumlah_transaksi(self, seeded):
        hasil = {row.outlet_code: row.total_transactions for row in SalesService.get_sync_status(db=seeded)}

        assert hasil["OUTLET_001"] == 3  # termasuk yang deleted — ini status sync, bukan laporan omzet
        assert hasil["OUTLET_002"] == 1

    def test_filter_outlet(self, seeded):
        hasil = SalesService.get_sync_status(db=seeded, outlet="OUTLET_002")

        assert len(hasil) == 1
        assert hasil[0].outlet_code == "OUTLET_002"

    def test_outlet_yang_belum_pernah_sync_tidak_muncul(self, seeded):
        """Sumber datanya transaksi — outlet tanpa transaksi memang tidak ada barisnya."""
        hasil = SalesService.get_sync_status(db=seeded, outlet="OUTLET_TIDAK_ADA")

        assert hasil == []


class TestOmzetPakaiKolomUang:
    """Regresi: laporan sempat menjumlahkan kolom yang bukan uang.

    `ReceiptTotalAmount` namanya terdengar seperti total rupiah, padahal isinya
    jumlah item. Di database produksi terbukti persis sama dengan
    `sum(orderdetail.Amount)` pada 14 dari 14 baris.

    Akibatnya `/api/sales/summary` melaporkan omzet Rp 109 untuk 14 transaksi
    yang sebenarnya bernilai Rp 4.418.375 — salah 40.000 kali lipat, tanpa
    error, tanpa peringatan. Kolom yang benar adalah `ReceiptPayPrice`:
    jumlah yang betul-betul dibayar pelanggan.

    Test di kelas ini mengunci pilihan kolom itu, bukan sekadar angkanya.
    """

    def test_summary_memakai_pay_price_bukan_jumlah_item(self, seeded):
        hasil = SalesService.get_summary(db=seeded)

        assert hasil["total_amount"] == 600000, "omzet harus dari ReceiptPayPrice"
        assert hasil["total_amount"] != 20, "ini jumlah item, bukan rupiah"

    def test_daily_memakai_pay_price_bukan_jumlah_item(self, seeded):
        hasil = {r.sale_date: r.total_amount for r in SalesService.get_daily_sales(db=seeded)}

        assert hasil[date(2026, 1, 10)] == 100000
        assert hasil[date(2026, 1, 15)] == 500000

    def test_by_outlet_memakai_pay_price_bukan_jumlah_item(self, seeded):
        hasil = {r.outlet_code: r.total_amount for r in SalesService.get_sales_by_outlet(db=seeded)}

        assert hasil["OUTLET_001"] == 300000
        assert hasil["OUTLET_002"] == 300000

    def test_rata_rata_ikut_memakai_kolom_uang(self, seeded):
        """Rata-rata dihitung dari total_amount, jadi ikut salah kalau kolomnya salah."""
        hasil = SalesService.get_summary(db=seeded)

        assert hasil["average_per_transaction"] == 200000
