"""Test endpoint Fase 6 — product group dinamis.

- `/api/product-groups`         → kelola mapping (khusus admin)
- `/api/sales/by-group`         → rekap penjualan per group (JWT user)
- `/api/sales/product-groups`   → daftar group yang ada di data (JWT user)
"""

from datetime import date

import pytest

from app.models.product_group_mapping import ProductGroupMapping
from tests.conftest import bearer, make_item_row, make_sale_row


@pytest.fixture()
def manager_headers(make_user, token_for):
    return bearer(token_for(make_user(email="manager@maharasa.id", role="manager")))


@pytest.fixture()
def outlet_headers(make_user, token_for):
    user = make_user(email="kasir@maharasa.id", role="outlet", outlet_code="OUTLET_001")
    return bearer(token_for(user))


@pytest.fixture()
def data_penjualan(app_db):
    """Dua outlet; OUTLET_001 menjual colorplate & food, OUTLET_002 colorplate & drink."""
    app_db.add_all(
        [
            make_sale_row(transaction_id=1, outlet_code="OUTLET_001", sale_date=date(2026, 1, 10)),
            make_sale_row(transaction_id=2, outlet_code="OUTLET_001", sale_date=date(2026, 1, 15)),
            make_sale_row(transaction_id=3, outlet_code="OUTLET_002", sale_date=date(2026, 1, 15)),
        ]
    )
    app_db.add_all(
        [
            make_item_row(order_detail_id=1, transaction_id=1, product_name="RED", qty=2, sale_date=date(2026, 1, 10)),
            make_item_row(order_detail_id=1, transaction_id=2, product_name="RED", qty=3, sale_date=date(2026, 1, 15)),
            make_item_row(
                order_detail_id=2,
                transaction_id=2,
                product_group=" food",
                product_name="NASI GORENG",
                qty=5,
                sale_date=date(2026, 1, 15),
            ),
            make_item_row(order_detail_id=1, transaction_id=3, product_name="BLUE", qty=7, sale_date=date(2026, 1, 15)),
            make_item_row(
                order_detail_id=2,
                transaction_id=3,
                product_group="DRINK",
                product_name="ES TEH",
                qty=1,
                sale_date=date(2026, 1, 15),
            ),
        ]
    )
    app_db.commit()


# ---------------------------------------------------------------------------
# /api/product-groups — mapping (admin)
# ---------------------------------------------------------------------------


class TestListMapping:

    def test_admin_melihat_semua_termasuk_nonaktif(self, client, admin_headers, make_product_group):
        make_product_group("COLORPLATE")
        make_product_group("FOOD", is_active=False)

        response = client.get("/api/product-groups", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()["data"]
        assert [(r["product_group"], r["is_active"]) for r in data] == [("COLORPLATE", True), ("FOOD", False)]
        assert {"id", "created_at", "updated_at"} <= set(data[0])

    def test_manager_ditolak(self, client, manager_headers):
        assert client.get("/api/product-groups", headers=manager_headers).status_code == 403

    def test_role_outlet_ditolak(self, client, outlet_headers):
        assert client.get("/api/product-groups", headers=outlet_headers).status_code == 403

    def test_butuh_autentikasi(self, client):
        assert client.get("/api/product-groups").status_code == 401


class TestCreateMapping:

    def test_membuat_mapping_dalam_bentuk_normal(self, client, admin_headers, app_db):
        response = client.post("/api/product-groups", json={"product_group": " food "}, headers=admin_headers)

        assert response.status_code == 201
        assert response.json()["data"]["product_group"] == "FOOD"
        assert response.json()["data"]["is_active"] is True
        assert app_db.query(ProductGroupMapping).filter(ProductGroupMapping.product_group == "FOOD").count() == 1

    def test_bisa_dibuat_nonaktif(self, client, admin_headers):
        response = client.post(
            "/api/product-groups",
            json={"product_group": "FOOD", "is_active": False},
            headers=admin_headers,
        )

        assert response.json()["data"]["is_active"] is False

    def test_duplikat_beda_kapitalisasi_ditolak_409(self, client, admin_headers, make_product_group):
        make_product_group("COLORPLATE")

        response = client.post("/api/product-groups", json={"product_group": "colorplate"}, headers=admin_headers)

        assert response.status_code == 409

    @pytest.mark.parametrize("nama", ["", "   "])
    def test_nama_kosong_ditolak_422(self, client, admin_headers, nama):
        response = client.post("/api/product-groups", json={"product_group": nama}, headers=admin_headers)

        assert response.status_code == 422

    def test_nama_terlalu_panjang_ditolak_422(self, client, admin_headers):
        response = client.post("/api/product-groups", json={"product_group": "X" * 256}, headers=admin_headers)

        assert response.status_code == 422

    def test_manager_ditolak(self, client, manager_headers):
        response = client.post("/api/product-groups", json={"product_group": "FOOD"}, headers=manager_headers)

        assert response.status_code == 403


class TestUpdateMapping:

    def test_menonaktifkan(self, client, admin_headers, make_product_group, app_db):
        row = make_product_group("FOOD")

        response = client.patch(f"/api/product-groups/{row.id}", json={"is_active": False}, headers=admin_headers)

        assert response.status_code == 200
        assert response.json()["data"]["is_active"] is False
        app_db.expire_all()
        assert app_db.get(ProductGroupMapping, row.id).is_active is False

    def test_mengaktifkan_kembali(self, client, admin_headers, make_product_group):
        row = make_product_group("FOOD", is_active=False)

        response = client.patch(f"/api/product-groups/{row.id}", json={"is_active": True}, headers=admin_headers)

        assert response.json()["data"]["is_active"] is True

    def test_is_active_wajib_dikirim(self, client, admin_headers, make_product_group):
        row = make_product_group("FOOD")

        assert client.patch(f"/api/product-groups/{row.id}", json={}, headers=admin_headers).status_code == 422

    def test_id_tidak_dikenal_404(self, client, admin_headers):
        assert client.patch("/api/product-groups/999", json={"is_active": False}, headers=admin_headers).status_code == 404

    def test_manager_ditolak(self, client, manager_headers, make_product_group):
        row = make_product_group("FOOD")

        response = client.patch(f"/api/product-groups/{row.id}", json={"is_active": False}, headers=manager_headers)

        assert response.status_code == 403

    def test_tidak_ada_endpoint_hapus(self, client, admin_headers, make_product_group, app_db):
        """Mapping dimatikan, tidak pernah dihapus — jejaknya tetap ada."""
        row = make_product_group("FOOD")

        response = client.delete(f"/api/product-groups/{row.id}", headers=admin_headers)

        assert response.status_code == 405
        assert app_db.query(ProductGroupMapping).count() == 1


# ---------------------------------------------------------------------------
# /api/sales/by-group
# ---------------------------------------------------------------------------


class TestSalesByGroup:

    def test_rekap_satu_group(self, client, admin_headers, data_penjualan):
        response = client.get("/api/sales/by-group?product_group=FOOD", headers=admin_headers)

        assert response.status_code == 200
        assert response.json()["data"] == [
            {
                "product_group": "FOOD",
                "product_name": "NASI GORENG",
                "outlet_code": "OUTLET_001",
                "sale_date": "2026-01-15",
                "sold": 5.0,
            }
        ]

    def test_beberapa_group_sekaligus(self, client, admin_headers, data_penjualan):
        response = client.get(
            "/api/sales/by-group?product_group=COLORPLATE&product_group=drink",
            headers=admin_headers,
        )

        assert {r["product_group"] for r in response.json()["data"]} == {"COLORPLATE", "DRINK"}

    def test_nama_group_dinormalisasi(self, client, admin_headers, data_penjualan):
        response = client.get("/api/sales/by-group?product_group=%20food%20", headers=admin_headers)

        assert [r["product_name"] for r in response.json()["data"]] == ["NASI GORENG"]

    def test_product_group_wajib_422(self, client, admin_headers):
        assert client.get("/api/sales/by-group", headers=admin_headers).status_code == 422

    def test_product_group_spasi_saja_ditolak_422(self, client, admin_headers):
        assert client.get("/api/sales/by-group?product_group=%20%20", headers=admin_headers).status_code == 422

    def test_user_outlet_hanya_melihat_outletnya(self, client, outlet_headers, data_penjualan):
        response = client.get("/api/sales/by-group?product_group=COLORPLATE", headers=outlet_headers)

        assert response.status_code == 200
        assert {r["outlet_code"] for r in response.json()["data"]} == {"OUTLET_001"}

    def test_user_outlet_tidak_bisa_meminta_outlet_lain(self, client, outlet_headers, data_penjualan):
        response = client.get(
            "/api/sales/by-group?product_group=COLORPLATE&outlet=OUTLET_002",
            headers=outlet_headers,
        )

        assert response.status_code == 403

    def test_filter_tanggal(self, client, admin_headers, data_penjualan):
        response = client.get(
            "/api/sales/by-group?product_group=COLORPLATE&start_date=2026-01-10&end_date=2026-01-10",
            headers=admin_headers,
        )

        data = response.json()["data"]
        assert [(r["product_name"], r["sold"]) for r in data] == [("RED", 2.0)]

    def test_butuh_autentikasi(self, client):
        assert client.get("/api/sales/by-group?product_group=FOOD").status_code == 401


# ---------------------------------------------------------------------------
# /api/sales/product-groups
# ---------------------------------------------------------------------------


class TestDaftarProductGroup:

    def test_daftar_group_dari_data(self, client, admin_headers, data_penjualan):
        response = client.get("/api/sales/product-groups", headers=admin_headers)

        assert response.status_code == 200
        assert response.json()["data"] == ["COLORPLATE", "DRINK", "FOOD"]

    def test_user_outlet_hanya_melihat_group_outletnya(self, client, outlet_headers, data_penjualan):
        response = client.get("/api/sales/product-groups", headers=outlet_headers)

        assert response.json()["data"] == ["COLORPLATE", "FOOD"]

    def test_butuh_autentikasi(self, client):
        assert client.get("/api/sales/product-groups").status_code == 401
