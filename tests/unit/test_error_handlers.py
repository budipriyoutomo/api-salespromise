"""Database sibuk / query terlalu lama → 503 JSON yang bisa dibaca dashboard.

Sebelumnya error ini keluar sebagai 500 teks polos tanpa petunjuk, dan
frontend mengulangnya dua kali — menambah beban saat database sedang berat.
"""

import psycopg2.errors
import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app.services.sales_service import SalesService


def _query_dibatalkan():
    return OperationalError(
        "SELECT ...", {}, psycopg2.errors.QueryCanceled("canceling statement due to statement timeout")
    )


def _koneksi_putus():
    return OperationalError("SELECT ...", {}, Exception("server closed the connection unexpectedly"))


def _pool_penuh():
    return PoolTimeoutError("QueuePool limit of size 5 overflow 5 reached")


@pytest.fixture()
def summary_gagal(monkeypatch):
    def _pasang(error):
        def gagal(*args, **kwargs):
            raise error

        monkeypatch.setattr(SalesService, "get_summary", staticmethod(gagal))

    return _pasang


class TestDatabaseSibuk:

    def test_statement_timeout_jadi_503_dengan_saran(self, client, admin_headers, summary_gagal):
        summary_gagal(_query_dibatalkan())

        response = client.get("/api/sales/summary", headers=admin_headers)

        assert response.status_code == 503
        assert "rentang tanggal" in response.json()["detail"]

    def test_pool_penuh_jadi_503(self, client, admin_headers, summary_gagal):
        summary_gagal(_pool_penuh())

        response = client.get("/api/sales/summary", headers=admin_headers)

        assert response.status_code == 503
        assert "sibuk" in response.json()["detail"]

    def test_koneksi_database_putus_jadi_503(self, client, admin_headers, summary_gagal):
        summary_gagal(_koneksi_putus())

        response = client.get("/api/sales/summary", headers=admin_headers)

        assert response.status_code == 503
        assert "database" in response.json()["detail"].lower()

    def test_membawa_request_id_untuk_dilacak_di_log(self, client, admin_headers, summary_gagal):
        summary_gagal(_query_dibatalkan())

        response = client.get("/api/sales/summary", headers={**admin_headers, "X-Request-ID": "lacak-123"})

        assert response.headers["X-Request-ID"] == "lacak-123"
        assert response.json()["request_id"] == "lacak-123"

    def test_detail_error_database_tidak_bocor(self, client, admin_headers, summary_gagal):
        summary_gagal(_koneksi_putus())

        body = client.get("/api/sales/summary", headers=admin_headers).text

        assert "server closed" not in body
        assert "SELECT" not in body

    def test_daftar_transaksi_tidak_menelan_timeout_jadi_500(self, client, admin_headers, monkeypatch):
        """`GET /api/sales/` punya try/except sendiri — timeout tetap harus 503."""

        def gagal(*args, **kwargs):
            raise _query_dibatalkan()

        monkeypatch.setattr(SalesService, "get_sales", staticmethod(gagal))

        response = client.get("/api/sales/", headers=admin_headers)

        assert response.status_code == 503
