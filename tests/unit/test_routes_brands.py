"""Test brand & mapping outlet → brand.

- `/api/brands`                     → kelola brand (list: admin & manager, tulis: admin)
- `/api/brands/outlets`             → mapping outlet → brand (admin)
- `/api/outlets`                    → ikut menampilkan brand
- `?brand=` di laporan `/api/sales` → hanya outlet milik brand itu
"""

from datetime import date

import pytest

from app.models.brand import Brand, OutletBrandMapping
from tests.conftest import bearer, make_item_row, make_sale_row


@pytest.fixture()
def manager_headers(make_user, token_for):
    return bearer(token_for(make_user(email="manager@maharasa.id", role="manager")))


@pytest.fixture()
def outlet_headers(make_user, token_for):
    user = make_user(email="kasir@maharasa.id", role="outlet", outlet_code="OUTLET_001")
    return bearer(token_for(user))


@pytest.fixture()
def tiga_outlet(make_api_key):
    for kode in ["OUTLET_001", "OUTLET_002", "OUTLET_003"]:
        make_api_key(outlet_code=kode)


# ---------------------------------------------------------------------------
# /api/brands
# ---------------------------------------------------------------------------


class TestListBrand:

    def test_admin_melihat_semua_beserta_outletnya(self, client, admin_headers, make_brand, map_outlet_brand):
        mhr = make_brand("MHR", "Maharasa")
        make_brand("OLD", "Brand Lama", is_active=False)
        map_outlet_brand("OUTLET_002", mhr)
        map_outlet_brand("OUTLET_001", mhr)

        response = client.get("/api/brands", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()["data"]
        assert [(b["code"], b["is_active"], b["outlet_codes"]) for b in data] == [
            ("MHR", True, ["OUTLET_001", "OUTLET_002"]),
            ("OLD", False, []),
        ]

    def test_outlet_yang_dilepas_tidak_ikut(self, client, admin_headers, make_brand, map_outlet_brand):
        make_brand("MHR")
        map_outlet_brand("OUTLET_001", None)

        data = client.get("/api/brands", headers=admin_headers).json()["data"]

        assert data[0]["outlet_codes"] == []

    def test_manager_boleh_membaca(self, client, manager_headers, make_brand):
        make_brand()

        assert client.get("/api/brands", headers=manager_headers).status_code == 200

    def test_role_outlet_ditolak(self, client, outlet_headers):
        assert client.get("/api/brands", headers=outlet_headers).status_code == 403

    def test_tanpa_token_ditolak(self, client):
        assert client.get("/api/brands").status_code == 401


class TestCreateBrand:

    def test_kode_dinormalisasi(self, client, admin_headers, app_db):
        response = client.post("/api/brands", json={"code": " mhr ", "name": " Maharasa "}, headers=admin_headers)

        assert response.status_code == 201
        data = response.json()["data"]
        assert (data["code"], data["name"], data["is_active"], data["outlet_codes"]) == ("MHR", "Maharasa", True, [])
        assert app_db.query(Brand).one().code == "MHR"

    def test_kode_sudah_ada_ditolak_termasuk_yang_nonaktif(self, client, admin_headers, make_brand):
        make_brand("MHR", is_active=False)

        response = client.post("/api/brands", json={"code": "mhr", "name": "Lagi"}, headers=admin_headers)

        assert response.status_code == 409

    @pytest.mark.parametrize(
        "body",
        [
            {"code": "   ", "name": "Maharasa"},
            {"code": "MHR", "name": "   "},
            {"code": "X" * 21, "name": "Maharasa"},
            {"code": "MHR"},
        ],
    )
    def test_data_tidak_valid_ditolak(self, client, admin_headers, app_db, body):
        response = client.post("/api/brands", json=body, headers=admin_headers)

        assert response.status_code == 422
        assert app_db.query(Brand).count() == 0

    def test_manager_tidak_boleh_menulis(self, client, manager_headers):
        response = client.post("/api/brands", json={"code": "MHR", "name": "Maharasa"}, headers=manager_headers)

        assert response.status_code == 403


class TestUpdateBrand:

    def test_ubah_nama_dan_status(self, client, admin_headers, make_brand):
        brand = make_brand("MHR", "Maharasa")

        response = client.patch(
            f"/api/brands/{brand.id}", json={"name": "Maharasa Baru", "is_active": False}, headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert (data["code"], data["name"], data["is_active"]) == ("MHR", "Maharasa Baru", False)
        assert data["updated_at"] is not None

    def test_kode_tidak_bisa_diubah(self, client, admin_headers, make_brand):
        brand = make_brand("MHR")

        response = client.patch(f"/api/brands/{brand.id}", json={"code": "LAIN", "is_active": True}, headers=admin_headers)

        assert response.status_code == 200
        assert response.json()["data"]["code"] == "MHR"

    def test_body_kosong_ditolak(self, client, admin_headers, make_brand):
        brand = make_brand()

        assert client.patch(f"/api/brands/{brand.id}", json={}, headers=admin_headers).status_code == 422

    def test_tidak_ditemukan(self, client, admin_headers):
        assert client.patch("/api/brands/999", json={"is_active": False}, headers=admin_headers).status_code == 404


# ---------------------------------------------------------------------------
# /api/brands/outlets
# ---------------------------------------------------------------------------


class TestMappingOutlet:

    def test_semua_outlet_tampil_termasuk_yang_belum_dipetakan(
        self, client, admin_headers, tiga_outlet, make_brand, map_outlet_brand
    ):
        map_outlet_brand("OUTLET_002", make_brand("MHR", "Maharasa"))

        response = client.get("/api/brands/outlets", headers=admin_headers)

        assert response.status_code == 200
        assert [(o["outlet_code"], o["brand_code"], o["brand_name"]) for o in response.json()["data"]] == [
            ("OUTLET_001", None, None),
            ("OUTLET_002", "MHR", "Maharasa"),
            ("OUTLET_003", None, None),
        ]

    def test_petakan_pindahkan_lalu_lepas(self, client, admin_headers, tiga_outlet, make_brand, app_db):
        mhr = make_brand("MHR")
        lain = make_brand("LAIN")

        response = client.put("/api/brands/outlets/OUTLET_001", json={"brand_id": mhr.id}, headers=admin_headers)
        assert response.status_code == 200
        assert response.json()["data"]["brand_code"] == "MHR"

        response = client.put("/api/brands/outlets/OUTLET_001", json={"brand_id": lain.id}, headers=admin_headers)
        assert response.json()["data"]["brand_code"] == "LAIN"

        response = client.put("/api/brands/outlets/OUTLET_001", json={"brand_id": None}, headers=admin_headers)
        assert response.status_code == 200
        assert response.json()["data"]["brand_id"] is None

        # Satu baris per outlet — dipindah & dilepas, tidak pernah dihapus.
        rows = app_db.query(OutletBrandMapping).all()
        assert [(r.outlet_code, r.brand_id) for r in rows] == [("OUTLET_001", None)]

    def test_outlet_tanpa_api_key_ditolak(self, client, admin_headers, make_brand):
        brand = make_brand()

        response = client.put("/api/brands/outlets/TIDAK_ADA", json={"brand_id": brand.id}, headers=admin_headers)

        assert response.status_code == 404

    def test_brand_tidak_ada_ditolak(self, client, admin_headers, tiga_outlet):
        response = client.put("/api/brands/outlets/OUTLET_001", json={"brand_id": 999}, headers=admin_headers)

        assert response.status_code == 422

    def test_brand_nonaktif_ditolak(self, client, admin_headers, tiga_outlet, make_brand, app_db):
        brand = make_brand(is_active=False)

        response = client.put("/api/brands/outlets/OUTLET_001", json={"brand_id": brand.id}, headers=admin_headers)

        assert response.status_code == 422
        assert app_db.query(OutletBrandMapping).count() == 0

    def test_body_kosong_tidak_melepas_outlet(self, client, admin_headers, tiga_outlet):
        response = client.put("/api/brands/outlets/OUTLET_001", json={}, headers=admin_headers)

        assert response.status_code == 422

    def test_manager_tidak_boleh(self, client, manager_headers, tiga_outlet):
        assert client.get("/api/brands/outlets", headers=manager_headers).status_code == 403
        assert (
            client.put("/api/brands/outlets/OUTLET_001", json={"brand_id": None}, headers=manager_headers).status_code
            == 403
        )


def test_daftar_outlet_menampilkan_brand(client, admin_headers, tiga_outlet, make_brand, map_outlet_brand):
    map_outlet_brand("OUTLET_001", make_brand("MHR", "Maharasa"))

    data = client.get("/api/outlets", headers=admin_headers).json()["data"]

    assert data[0] == {"outlet_code": "OUTLET_001", "is_active": True, "brand_code": "MHR", "brand_name": "Maharasa"}
    assert data[1]["brand_code"] is None


# ---------------------------------------------------------------------------
# Filter ?brand= di laporan
# ---------------------------------------------------------------------------


@pytest.fixture()
def penjualan_dua_brand(app_db, make_brand, map_outlet_brand):
    """OUTLET_001 & OUTLET_002 milik MHR, OUTLET_003 milik LAIN."""
    mhr = make_brand("MHR")
    lain = make_brand("LAIN")
    map_outlet_brand("OUTLET_001", mhr)
    map_outlet_brand("OUTLET_002", mhr)
    map_outlet_brand("OUTLET_003", lain)

    app_db.add_all(
        [
            make_sale_row(transaction_id=1, outlet_code="OUTLET_001", receipt_pay_price=100),
            make_sale_row(transaction_id=2, outlet_code="OUTLET_002", receipt_pay_price=200),
            make_sale_row(transaction_id=3, outlet_code="OUTLET_003", receipt_pay_price=400),
        ]
    )
    app_db.add_all(
        [
            make_item_row(order_detail_id=1, transaction_id=1, product_id=1, product_name="A", qty=1),
            make_item_row(order_detail_id=1, transaction_id=2, outlet_code="OUTLET_002", product_id=1, product_name="A", qty=2),
            make_item_row(order_detail_id=1, transaction_id=3, outlet_code="OUTLET_003", product_id=2, product_name="B", qty=9),
        ]
    )
    app_db.commit()


class TestFilterBrand:

    def test_summary(self, client, admin_headers, penjualan_dua_brand):
        data = client.get("/api/sales/summary?brand=MHR", headers=admin_headers).json()["data"]

        assert (data["total_transactions"], data["total_amount"]) == (2, 300)

    def test_kode_tidak_peka_huruf_besar_kecil(self, client, admin_headers, penjualan_dua_brand):
        data = client.get("/api/sales/summary?brand=%20mhr", headers=admin_headers).json()["data"]

        assert data["total_transactions"] == 2

    def test_list_sales_dan_total_pagination(self, client, admin_headers, penjualan_dua_brand):
        body = client.get("/api/sales/?brand=LAIN", headers=admin_headers).json()

        assert [r["transaction_id"] for r in body["data"]] == [3]
        assert body["pagination"]["total"] == 1

    def test_by_outlet(self, client, admin_headers, penjualan_dua_brand):
        data = client.get("/api/sales/by-outlet?brand=MHR", headers=admin_headers).json()["data"]

        assert [r["outlet_code"] for r in data] == ["OUTLET_002", "OUTLET_001"]

    def test_daily(self, client, admin_headers, penjualan_dua_brand):
        data = client.get("/api/sales/daily?brand=LAIN", headers=admin_headers).json()["data"]

        assert [(r["sale_date"], r["total_amount"]) for r in data] == [(str(date(2026, 1, 15)), 400)]

    def test_top_products(self, client, admin_headers, penjualan_dua_brand):
        data = client.get("/api/sales/top-products?brand=MHR", headers=admin_headers).json()["data"]

        assert [(r["product_id"], r["total_qty"]) for r in data] == [(1, 3)]

    def test_export(self, client, admin_headers, penjualan_dua_brand):
        response = client.get("/api/sales/export?brand=LAIN", headers=admin_headers)

        baris = response.text.strip().splitlines()
        assert len(baris) == 2
        assert baris[1].startswith("3,OUTLET_003")

    def test_by_group(self, client, admin_headers, penjualan_dua_brand):
        data = client.get("/api/sales/by-group?product_group=COLORPLATE&brand=MHR", headers=admin_headers).json()[
            "data"
        ]

        assert sorted((r["outlet_code"], r["sold"]) for r in data) == [("OUTLET_001", 1), ("OUTLET_002", 2)]

    def test_brand_tidak_dikenal_hasilnya_kosong(self, client, admin_headers, penjualan_dua_brand):
        data = client.get("/api/sales/summary?brand=TIDAKADA", headers=admin_headers).json()["data"]

        assert data["total_transactions"] == 0

    def test_digabung_dengan_filter_outlet(self, client, admin_headers, penjualan_dua_brand):
        data = client.get("/api/sales/summary?brand=MHR&outlet=OUTLET_003", headers=admin_headers).json()["data"]

        assert data["total_transactions"] == 0

    def test_role_outlet_tidak_bisa_membaca_outlet_lain_lewat_brand(
        self, client, outlet_headers, penjualan_dua_brand
    ):
        """OUTLET_001 memfilter brand LAIN: kosong, bukan data OUTLET_003."""
        data = client.get("/api/sales/summary?brand=LAIN", headers=outlet_headers).json()["data"]
        assert data["total_transactions"] == 0

        data = client.get("/api/sales/summary?brand=MHR", headers=outlet_headers).json()["data"]
        assert (data["total_transactions"], data["total_amount"]) == (1, 100)

    def test_tanpa_brand_semua_outlet(self, client, admin_headers, penjualan_dua_brand):
        data = client.get("/api/sales/summary", headers=admin_headers).json()["data"]

        assert data["total_transactions"] == 3
