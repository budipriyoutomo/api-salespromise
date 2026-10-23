"""Rentang tanggal laporan dibatasi — query lintas bertahun-tahun memindai
seluruh tabel penjualan dan menahan koneksi database."""

from datetime import date

import pytest
from fastapi import HTTPException

from app.core.rentang_tanggal import cek_rentang_tanggal

ENDPOINT = [
    "/api/sales/",
    "/api/sales/colorplate",
    "/api/sales/by-group?product_group=FOOD",
    "/api/sales/summary",
    "/api/sales/daily",
    "/api/sales/by-outlet",
    "/api/sales/top-products",
    "/api/sales/export",
    "/api/closing-reports/comparison",
    "/api/closing-exports/status",
]


def _gabung(url, **params):
    sambung = "&" if "?" in url else "?"
    return url + sambung + "&".join(f"{k}={v}" for k, v in params.items())


class TestCekRentang:

    def test_rentang_dalam_batas_lolos(self):
        assert cek_rentang_tanggal(date(2026, 1, 1), date(2027, 1, 1), maks_hari=366) is None

    def test_rentang_melewati_batas_ditolak(self):
        with pytest.raises(HTTPException) as exc:
            cek_rentang_tanggal(date(2026, 1, 1), date(2027, 1, 3), maks_hari=366)

        assert exc.value.status_code == 422
        assert "366" in exc.value.detail

    @pytest.mark.parametrize("awal, akhir", [(None, None), (date(2020, 1, 1), None), (None, date(2026, 1, 1))])
    def test_tanpa_salah_satu_tanggal_tidak_dibatasi(self, awal, akhir):
        """Pemanggil lama tanpa rentang tidak diputus; statement_timeout jadi pengaman."""
        assert cek_rentang_tanggal(awal, akhir, maks_hari=366) is None

    def test_rentang_terbalik_tidak_dianggap_melewati_batas(self):
        assert cek_rentang_tanggal(date(2027, 1, 1), date(2020, 1, 1), maks_hari=366) is None


class TestEndpoint:

    @pytest.mark.parametrize("url", ENDPOINT)
    def test_rentang_terlalu_panjang_422(self, client, admin_headers, url):
        response = client.get(_gabung(url, start_date="2024-01-01", end_date="2026-01-01"), headers=admin_headers)

        assert response.status_code == 422, response.text
        assert "rentang" in response.json()["detail"].lower()

    @pytest.mark.parametrize("url", ENDPOINT)
    def test_rentang_setahun_lolos(self, client, admin_headers, url):
        response = client.get(_gabung(url, start_date="2025-01-01", end_date="2026-01-01"), headers=admin_headers)

        assert response.status_code == 200, response.text
