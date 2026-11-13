"""`sales` dan `prices` kirim rekap closing (kontrak revisi 3, bagian 2.2–2.5)."""

from decimal import Decimal

import pytest

from app.services.closing_export_penjualan import HeaderMode, angka, bagi, nama_tujuan, susun

D = Decimal


class TestBagi:
    def test_sebanding_bobot(self):
        assert bagi(D(100), [D(1), D(3)]) == [D("25.00"), D("75.00")]

    def test_sisa_pembulatan_ke_baris_terbesar(self):
        hasil = bagi(D(100), [D(1), D(1), D(2)])

        assert sum(hasil) == D(100)
        assert hasil == [D("25.00"), D("25.00"), D("50.00")]
        assert bagi(D(10), [D(1), D(1), D(1)]) == [D("3.34"), D("3.33"), D("3.33")]

    def test_bobot_nol_dibagi_rata(self):
        assert bagi(D(10), [D(0), D(0)]) == [D(5), D(5)]

    def test_tanpa_baris(self):
        assert bagi(D(10), []) == []

    def test_total_dibulatkan_dua_desimal(self):
        assert sum(bagi(D("10.006"), [D(1), D(2)])) == D("10.01")


@pytest.mark.parametrize(("nilai", "hasil"), [(D("15000.0000"), 15000), (D("12.345"), 12.35), (D(0), 0)])
def test_angka(nilai, hasil):
    assert angka(nilai) == hasil
    assert type(angka(nilai)) is type(hasil)


def test_nama_tujuan_belum_dipetakan():
    assert nama_tujuan(6) == "SALEMODE 6"


def _jumlah(prices, sales, field):
    return sum(
        D(str(p[field]))
        for daftar in prices.values()
        for p in daftar
        if p["visitPurposeName"] == sales["visitPurposeName"]
    )


class TestSusun:
    def test_outlet_st_eksklusif(self):
        """Pola outlet ST: SC 7,5%, PPN 10% dari subtotal + SC."""
        baris = {"salmon": {(1, D(15000), D(15000)): D(3)}, "red": {(1, D(20000), D(20000)): D(4)}}
        header = {
            1: HeaderMode(
                pax=4, service_charge=D(9375), ppn=D("13437.5"), persen_service_charge=D("7.5"), persen_ppn=D(10)
            )
        }

        prices, (sales,) = susun(baris, header)

        assert (sales["subtotal"], sales["otherTaxTotal"], sales["vatTotal"], sales["grandTotal"]) == (
            125000,
            9375,
            13437.5,
            147812.5,
        )
        assert sales["paymentTotal"] == sales["grandTotal"]
        assert sales["payments"] == []
        assert prices["salmon"][0] == {
            "visitPurposeName": "SALEMODE 1",
            "qty": 3,
            "originalPrice": 15000,
            "price": 15000,
            "discount": 0,
            "discountValue": 0,
            "otherTax": 7.5,
            "otherTaxValue": 3375,
            "vat": 10,
            "vatValue": 4837.5,
            "otherVat": 0,
            "otherVatValue": 0,
            "otherTaxOnVat": 0,
            "total": 53212.5,
        }
        assert prices["red"][0]["total"] == 94600

    def test_outlet_ts_grand_total_termasuk_sc_dan_ppn(self):
        """Contoh TSSMB: ReceiptSalePrice 99.000, tetapi tamu membayar 114.345."""
        baris = {"ramen": {(1, D(99000), D(99000)): D(1)}}
        header = {1: HeaderMode(service_charge=D(4950), ppn=D(10395))}

        prices, (sales,) = susun(baris, header)

        assert sales["grandTotal"] == 114345
        assert prices["ramen"][0]["total"] == 114345

    def test_dipecah_per_sale_mode(self):
        baris = {
            "salmon": {(1, D(15000), D(15000)): D(2), (2, D(15000), D(15000)): D(1)},
            "ocha": {(2, D(8000), D(8000)): D(1)},
        }
        header = {1: HeaderMode(pax=2, ppn=D(3000)), 2: HeaderMode(pax=1, ppn=D(2300))}

        prices, sales = susun(baris, header)

        assert [(s["visitPurposeName"], s["subtotal"], s["paxTotal"], s["grandTotal"]) for s in sales] == [
            ("SALEMODE 1", 30000, 2, 33000),
            ("SALEMODE 2", 23000, 1, 25300),
        ]
        assert [(p["visitPurposeName"], p["qty"]) for p in prices["salmon"]] == [("SALEMODE 1", 2), ("SALEMODE 2", 1)]

    def test_jumlah_prices_sama_dengan_sales(self):
        """Diskon & pajak header dibagi ke baris; sisa pembulatan tidak hilang."""
        baris = {
            "a": {(1, D(10000), D(10000)): D(1), (1, D(12000), D(9000)): D(2)},
            "b": {(1, D(7000), D(7000)): D(3)},
            "c": {(1, D(3333), D(3333)): D(1)},
        }
        header = {
            1: HeaderMode(diskon=D("1000.01"), service_charge=D("3333.33"), ppn=D("4999.99"), pendapatan_lain=D(500))
        }

        prices, (sales,) = susun(baris, header)

        assert _jumlah(prices, sales, "discountValue") == D("1000.01")
        assert _jumlah(prices, sales, "otherTaxValue") == D("3333.33")
        assert _jumlah(prices, sales, "vatValue") == D("4999.99")
        assert _jumlah(prices, sales, "total") + D(500) == D(str(sales["grandTotal"]))
        assert sales["orderFee"] == 500

    def test_dua_harga_satu_item(self):
        baris = {"a": {(1, D(12000), D(9000)): D(2), (1, D(12000), D(12000)): D(1)}}

        prices, _ = susun(baris, {1: HeaderMode()})

        assert [(p["originalPrice"], p["price"], p["qty"], p["total"]) for p in prices["a"]] == [
            (12000, 9000, 2, 18000),
            (12000, 12000, 1, 12000),
        ]

    def test_persen_diskon_efektif(self):
        prices, _ = susun({"a": {(1, D(10000), D(10000)): D(2)}}, {1: HeaderMode(diskon=D(2000))})

        assert (prices["a"][0]["discount"], prices["a"][0]["discountValue"], prices["a"][0]["total"]) == (
            10,
            2000,
            18000,
        )

    def test_qty_nol_dibuang(self):
        prices, (sales,) = susun({"a": {(1, D(5000), D(5000)): D(0)}}, {1: HeaderMode()})

        assert prices == {}
        assert sales["subtotal"] == 0

    def test_qty_desimal_dua_digit(self):
        prices, _ = susun({"a": {(1, D(10000), D(10000)): D("1.5")}}, {})

        assert (prices["a"][0]["qty"], prices["a"][0]["total"]) == (1.5, 15000)

    def test_tanpa_penjualan(self):
        assert susun({}, {}) == ({}, [])
