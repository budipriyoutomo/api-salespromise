"""`payments` di rekap closing dan blokir pembayaran (docs/handoff-sync-api-payments.md 3.6).

Skenario dasar sama dengan `TestPenjualan` di test_closing_export_service.py:
transaksi 1 dine in (SALEMODE 1, grandTotal 130.075) dan transaksi 2 take
away (SALEMODE 2, grandTotal 33.000). Modul diimpor sebagai `dasar` supaya
kelas test-nya tidak ikut terkumpul dua kali.
"""

from decimal import Decimal

from app.core.time import utcnow
from app.models.sales import Sales
from app.models.sales_payments import SalesPayments
from app.services import closing_export_service
from tests.unit import test_closing_export_service as dasar

OUTLET = dasar.OUTLET
HARI_INI = dasar.HARI_INI


def bayar(db, transaction_id, *baris, outlet=OUTLET):
    """Tandai pembayaran transaksi diketahui. `baris` = (pay_type_id, nama, amount)."""
    db.query(Sales).filter_by(transaction_id=transaction_id, outlet_code=outlet).one().payments_received_at = utcnow()
    for n, (pay_type_id, nama, amount) in enumerate(baris, start=1):
        db.add(
            SalesPayments(
                outlet_code=outlet,
                transaction_id=transaction_id,
                computer_id=1,
                pay_detail_id=n,
                sale_date=HARI_INI,
                pay_type_id=pay_type_id,
                pay_type_name=nama,
                amount=Decimal(str(amount)),
                received_at=utcnow(),
            )
        )
    db.commit()


def siapkan(db):
    dasar.TestPenjualan().siapkan(db)


def satu(db):
    (r,) = dasar.rekap(db)
    return r


def payments(r):
    return {s["visitPurposeName"]: (s["paymentTotal"], s["payments"]) for s in closing_export_service.susun_isi(r)["sales"]}


class TestPembayaranDiketahui:
    def test_payments_per_tujuan_kunjungan_dan_jenis_bayar(self, db_session):
        siapkan(db_session)
        # Dine in dibayar dua metode; take away satu metode.
        bayar(db_session, 1, (149, "REEDEM POINT", 30075), (1, "Cash", 100000))
        bayar(db_session, 2, (864, "QRIS BNI", 33000))

        r = satu(db_session)

        assert not r.blokir
        assert payments(r) == {
            "SALEMODE 1": (
                130075,
                [
                    {"paymentMethod": "Cash", "paymentAmount": 100000, "fullPaymentAmount": 100000, "notes": ""},
                    {"paymentMethod": "REEDEM POINT", "paymentAmount": 30075, "fullPaymentAmount": 30075, "notes": ""},
                ],
            ),
            "SALEMODE 2": (
                33000,
                [{"paymentMethod": "QRIS BNI", "paymentAmount": 33000, "fullPaymentAmount": 33000, "notes": ""}],
            ),
        }

    def test_nominal_negatif_ikut_dan_nol_tidak_dikirim(self, db_session):
        siapkan(db_session)
        bayar(db_session, 1, (1, "Cash", 130076), (168, "Voucher Adjustment", -1), (10050, "CC BRI", 0))
        bayar(db_session, 2, (1, "Cash", 33000))

        r = satu(db_session)

        assert not r.blokir
        total, daftar = payments(r)["SALEMODE 1"]
        assert total == 130075
        assert [(p["paymentMethod"], p["paymentAmount"]) for p in daftar] == [
            ("Cash", 130076),
            ("Voucher Adjustment", -1),
        ]

    def test_transaksi_tanpa_pembayaran_tetap_diketahui(self, db_session):
        """`payments: []` = memang tanpa pembayaran, bukan "tidak diketahui"."""
        siapkan(db_session)
        bayar(db_session, 1, (1, "Cash", 130075))
        bayar(db_session, 2)

        r = satu(db_session)

        assert r.blokir.transaksi_tanpa_pembayaran == 0
        assert [(x.visit_purpose_name, x.grand_total, x.payment_total) for x in r.blokir.pembayaran_tidak_sama] == [
            ("SALEMODE 2", 33000, 0)
        ]

    def test_nama_jenis_bayar_kosong_diberi_id(self, db_session):
        siapkan(db_session)
        bayar(db_session, 1, (1, None, 130075))
        bayar(db_session, 2, (1, None, 33000))

        assert payments(satu(db_session))["SALEMODE 2"][1][0]["paymentMethod"] == "PAYTYPE 1"

    def test_selisih_dalam_toleransi_tidak_memblokir(self, db_session):
        siapkan(db_session)
        bayar(db_session, 1, (1, "Cash", Decimal("130075.4")))
        bayar(db_session, 2, (1, "Cash", 33000))

        assert not satu(db_session).blokir


class TestBlokirPembayaran:
    def test_pembayaran_belum_diketahui_memblokir(self, db_session):
        siapkan(db_session)
        bayar(db_session, 1, (1, "Cash", 130075))

        r = satu(db_session)

        assert r.blokir.transaksi_tanpa_pembayaran == 1
        # Belum lengkap: payments tidak disusun dan Σ tidak dibandingkan.
        assert r.blokir.pembayaran_tidak_sama == []
        assert all(s["payments"] == [] for s in closing_export_service.susun_isi(r)["sales"])

    def test_transaksi_void_tidak_dihitung(self, db_session):
        siapkan(db_session)
        bayar(db_session, 1, (1, "Cash", 130075))
        bayar(db_session, 2, (1, "Cash", 33000))
        dasar.transaksi(db_session, 3, [(300, 5, 8000, "Ocha", "DRINK")], sale_mode=2, deleted=1)

        assert not satu(db_session).blokir

    def test_pembayaran_tidak_sama_memblokir(self, db_session):
        siapkan(db_session)
        bayar(db_session, 1, (1, "Cash", 130075))
        bayar(db_session, 2, (1, "Cash", 32000))

        r = satu(db_session)

        assert [(x.visit_purpose_name, x.grand_total, x.payment_total) for x in r.blokir.pembayaran_tidak_sama] == [
            ("SALEMODE 2", 33000, 32000)
        ]

    def test_pembayaran_outlet_lain_tidak_dihitung(self, db_session):
        siapkan(db_session)
        bayar(db_session, 1, (1, "Cash", 130075))
        bayar(db_session, 2, (1, "Cash", 33000))
        # TransactionID sama di outlet lain.
        dasar.transaksi(db_session, 2, [(300, 1, 8000, "Ocha", "DRINK")], sale_mode=2, outlet="OUTLET_002")
        bayar(db_session, 2, (1, "Cash", 8000), outlet="OUTLET_002")

        assert payments(satu(db_session))["SALEMODE 2"][0] == 33000

    def test_status_membawa_blokir_pembayaran(self, db_session):
        siapkan(db_session)

        (s,) = closing_export_service.status_pasangan(db_session, outlet=OUTLET, start_date=HARI_INI, end_date=HARI_INI)

        assert (s.can_send, s.transaksi_tanpa_pembayaran, s.pembayaran_tidak_sama) == (False, 2, [])
