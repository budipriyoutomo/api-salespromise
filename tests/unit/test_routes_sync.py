"""Test app/routes/sync_routes.py — POST /api/sync/sales.

Service di-mock: yang diuji di sini kontrak HTTP-nya, bukan logika upsert.
Autentikasinya API key outlet (mesin POS), bukan JWT user.
"""

import pytest

from tests.conftest import bearer

VALID_BODY = {
    "sales": [
        {
            "transaction_id": 10001,
            "shop_id": 1,
            "sale_date": "2026-01-15",
            "paid_time": "2026-01-15T10:30:00",
            "receipt_total_amount": 150000.0,
            "receipt_pay_price": 150000.0,
            "vat_percent": 11.0,
            "transaction_vat": 14850.0,
            "items": [
                {
                    "order_detail_id": 1,
                    "transaction_id": 10001,
                    "sale_date": "2026-01-15",
                    "product_id": 101,
                    "qty": 2,
                    "price": 75000.0,
                    "retail_price": 75000.0,
                }
            ],
        }
    ]
}


@pytest.fixture()
def mock_sync(monkeypatch):
    """Ganti SalesService.sync_sales dan rekam argumen yang diterimanya."""
    calls = []

    def _install(result=None, error=None):
        def fake_sync(db, outlet, sales_list):
            calls.append({"db": db, "outlet": outlet, "sales_list": sales_list})
            if error:
                raise error
            return result if result is not None else {"sales": 1, "items": 1}

        monkeypatch.setattr("app.routes.sync_routes.SalesService.sync_sales", staticmethod(fake_sync))
        return calls

    return _install


class TestSukses:

    def test_mengembalikan_200_dengan_jumlah_tersimpan(self, client, api_key_headers, mock_sync):
        mock_sync(result={"sales": 3, "items": 7})

        response = client.post("/api/sync/sales", json=VALID_BODY, headers=api_key_headers)

        assert response.status_code == 200
        assert response.json() == {"success": True, "inserted_sales": 3, "inserted_items": 7}

    def test_outlet_diteruskan_dari_api_key_bukan_body(self, client, make_api_key, mock_sync):
        """Kontrak inti: body tidak menentukan outlet."""
        calls = mock_sync()
        raw = make_api_key(outlet_code="OUTLET_009")

        client.post("/api/sync/sales", json=VALID_BODY, headers=bearer(raw))

        assert calls[0]["outlet"] == "OUTLET_009"

    def test_payload_ter_parse_jadi_objek_schema(self, client, api_key_headers, mock_sync):
        calls = mock_sync()

        client.post("/api/sync/sales", json=VALID_BODY, headers=api_key_headers)

        sales_list = calls[0]["sales_list"]
        assert len(sales_list) == 1
        assert sales_list[0].transaction_id == 10001
        assert len(sales_list[0].items) == 1
        assert sales_list[0].items[0].product_id == 101

    def test_sales_kosong_tetap_diterima(self, client, api_key_headers, mock_sync):
        mock_sync(result={"sales": 0, "items": 0})

        response = client.post("/api/sync/sales", json={"sales": []}, headers=api_key_headers)

        assert response.status_code == 200
        assert response.json()["inserted_sales"] == 0

    def test_log_request_memuat_outlet_dan_jumlah(self, client, api_key_headers, mock_sync, caplog):
        mock_sync()

        with caplog.at_level("INFO", logger="sync-api"):
            client.post("/api/sync/sales", json=VALID_BODY, headers=api_key_headers)

        assert "outlet=OUTLET_001" in caplog.text
        assert "sales_count=1" in caplog.text


class TestValidasiBody:

    def test_body_kosong_ditolak_422(self, client, api_key_headers, mock_sync):
        mock_sync()

        response = client.post("/api/sync/sales", json={}, headers=api_key_headers)

        assert response.status_code == 422

    def test_transaction_id_hilang_ditolak_422(self, client, api_key_headers, mock_sync):
        mock_sync()

        response = client.post("/api/sync/sales", json={"sales": [{"shop_id": 1}]}, headers=api_key_headers)

        assert response.status_code == 422

    def test_tanggal_format_salah_ditolak_422(self, client, api_key_headers, mock_sync):
        mock_sync()
        body = {"sales": [{"transaction_id": 1, "sale_date": "15-01-2026"}]}

        response = client.post("/api/sync/sales", json=body, headers=api_key_headers)

        assert response.status_code == 422

    def test_item_tidak_lengkap_ditolak_422(self, client, api_key_headers, mock_sync):
        mock_sync()
        body = {"sales": [{"transaction_id": 1, "items": [{"order_detail_id": 1}]}]}

        response = client.post("/api/sync/sales", json=body, headers=api_key_headers)

        assert response.status_code == 422

    def test_service_tidak_dipanggil_saat_body_invalid(self, client, api_key_headers, mock_sync):
        calls = mock_sync()

        client.post("/api/sync/sales", json={"sales": [{}]}, headers=api_key_headers)

        assert calls == []


class TestPenangananError:

    def test_service_error_mengembalikan_500(self, client, api_key_headers, mock_sync):
        mock_sync(error=RuntimeError("database mati"))

        response = client.post("/api/sync/sales", json=VALID_BODY, headers=api_key_headers)

        assert response.status_code == 500

    def test_bentuk_detail_error_sesuai_readme(self, client, api_key_headers, mock_sync):
        mock_sync(error=RuntimeError("database mati"))

        response = client.post("/api/sync/sales", json=VALID_BODY, headers=api_key_headers)
        detail = response.json()["detail"]

        assert detail["success"] is False
        assert detail["message"] == "database mati"

    def test_error_dicatat_di_log(self, client, api_key_headers, mock_sync, caplog):
        mock_sync(error=RuntimeError("database mati"))

        with caplog.at_level("ERROR", logger="sync-api"):
            client.post("/api/sync/sales", json=VALID_BODY, headers=api_key_headers)

        assert "SYNC ROUTE ERROR" in caplog.text
        assert "OUTLET_001" in caplog.text


class TestAutentikasi:

    def test_tanpa_api_key_tidak_memanggil_service(self, client, mock_sync):
        calls = mock_sync()

        response = client.post("/api/sync/sales", json=VALID_BODY)

        assert response.status_code == 401
        assert calls == []

    def test_jwt_user_tidak_bisa_sync(self, client, make_user, token_for, mock_sync):
        """Endpoint sync khusus mesin POS, bukan dashboard."""
        calls = mock_sync()
        token = token_for(make_user(role="admin"))

        response = client.post("/api/sync/sales", json=VALID_BODY, headers=bearer(token))

        assert response.status_code == 401
        assert calls == []


class TestHealth:

    def test_root_terbuka_tanpa_autentikasi(self, client):
        """Monitoring tidak boleh dipaksa membawa API key."""
        response = client.get("/")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_health_alias_terbuka_tanpa_autentikasi(self, client):
        response = client.get("/health")

        assert response.status_code == 200
