"""Pembayaran di detail transaksi dan ringkasan per jenis bayar.

Seperti test_routes_reports.py, service tidak di-mock: data di-seed ke `app_db`.
"""

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.models.sales_payments import SalesPayments
from tests.conftest import bearer

DITERIMA = datetime(2026, 1, 16, 1, 0, 0)


def bayar(transaction_id, pay_detail_id, pay_type_id, nama, amount, outlet_code="OUTLET_001", **extra):
    return SalesPayments(
        outlet_code=outlet_code,
        transaction_id=transaction_id,
        computer_id=1,
        pay_detail_id=pay_detail_id,
        sale_date=date(2026, 1, 15),
        pay_type_id=pay_type_id,
        pay_type_name=nama,
        amount=Decimal(amount),
        cash_change=Decimal(extra.pop("cash_change", 0)),
        received_at=DITERIMA,
        **extra,
    )


@pytest.fixture()
def seeded(app_db, sale_factory):
    app_db.add_all(
        [
            # Dua jenis bayar dalam satu transaksi.
            sale_factory(transaction_id=1, receipt_pay_price=150000, payments_received_at=DITERIMA),
            sale_factory(transaction_id=2, receipt_pay_price=50000, payments_received_at=DITERIMA),
            # Pembayaran belum diketahui.
            sale_factory(transaction_id=3, receipt_pay_price=70000),
            # Diketahui tanpa pembayaran.
            sale_factory(transaction_id=4, receipt_pay_price=0, payments_received_at=DITERIMA),
            # Terhapus: tidak ikut dihitung.
            sale_factory(transaction_id=5, receipt_pay_price=999000, deleted=1, payments_received_at=DITERIMA),
            # Outlet lain dengan PayTypeID sama tapi nama beda.
            sale_factory(
                transaction_id=1, outlet_code="OUTLET_002", receipt_pay_price=80000, payments_received_at=DITERIMA
            ),
        ]
    )
    app_db.flush()
    app_db.add_all(
        [
            bayar(1, 2, 1, "Cash", 100000, cash_change=20000),
            bayar(1, 1, 5, "QRIS", 50000),
            bayar(2, 1, 1, "Cash", 50000),
            bayar(5, 1, 1, "Cash", 999000),
            bayar(1, 1, 1, "Tunai", 80000, outlet_code="OUTLET_002"),
        ]
    )
    app_db.commit()


@pytest.fixture()
def outlet_headers(make_user, token_for):
    user = make_user(email="kasir@maharasa.id", role="outlet", outlet_code="OUTLET_001")
    return bearer(token_for(user))


class TestDetailPembayaran:

    def test_membawa_baris_pembayaran_terurut(self, client, seeded, admin_headers):
        response = client.get("/api/sales/1", headers={**admin_headers})

        assert response.status_code == 200
        payments = response.json()["data"]["payments"]
        assert [p["pay_detail_id"] for p in payments] == [1, 2]
        assert payments[1]["pay_type_name"] == "Cash"
        assert payments[1]["amount"] == 100000
        assert payments[1]["cash_change"] == 20000

    def test_hanya_pembayaran_outlet_transaksi(self, client, seeded, outlet_headers):
        payments = client.get("/api/sales/1", headers=outlet_headers).json()["data"]["payments"]

        assert {p["pay_type_name"] for p in payments} == {"Cash", "QRIS"}

    def test_belum_diketahui_menjadi_null(self, client, seeded, admin_headers):
        assert client.get("/api/sales/3", headers=admin_headers).json()["data"]["payments"] is None

    def test_diketahui_tanpa_pembayaran_menjadi_list_kosong(self, client, seeded, admin_headers):
        assert client.get("/api/sales/4", headers=admin_headers).json()["data"]["payments"] == []


class TestRingkasanPembayaran:

    def test_per_outlet_dan_jenis_bayar(self, client, seeded, admin_headers):
        response = client.get("/api/sales/payments", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()["data"]
        rows = [(r["outlet_code"], r["pay_type_id"], r["pay_type_name"], r["total_transactions"], r["total_amount"]) for r in data["rows"]]
        assert rows == [
            ("OUTLET_001", 1, "Cash", 2, 150000),
            ("OUTLET_001", 5, "QRIS", 1, 50000),
            ("OUTLET_002", 1, "Tunai", 1, 80000),
        ]
        assert data["total_amount"] == 280000

    def test_transaksi_tanpa_data_pembayaran_dihitung(self, client, seeded, admin_headers):
        data = client.get("/api/sales/payments", headers=admin_headers).json()["data"]

        assert data["transactions_without_payments"] == 1

    def test_di_scope_untuk_role_outlet(self, client, seeded, outlet_headers):
        data = client.get("/api/sales/payments", headers=outlet_headers).json()["data"]

        assert {r["outlet_code"] for r in data["rows"]} == {"OUTLET_001"}
        assert data["total_amount"] == 200000

    def test_filter_rentang_tanggal(self, client, seeded, admin_headers):
        data = client.get(
            "/api/sales/payments",
            params={"start_date": "2026-02-01", "end_date": "2026-02-28"},
            headers=admin_headers,
        ).json()["data"]

        assert data == {"rows": [], "total_amount": 0, "transactions_without_payments": 0}

    def test_butuh_autentikasi(self, client, seeded):
        assert client.get("/api/sales/payments").status_code == 401
