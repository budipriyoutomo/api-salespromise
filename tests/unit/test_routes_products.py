"""Test master data product.

- `/api/products`                          → list & detail: admin & manager, tulis: admin
- `/api/products/pos-candidates`           → ProductID POS per outlet, untuk dipetakan (admin)
- `/api/products/{id}/pos-mappings`        → petakan ProductID POS outlet → produk master (admin)
"""

from datetime import date

import pytest

from app.models.product import Product, ProductPosMapping
from tests.conftest import bearer, make_item_row, make_sale_row


@pytest.fixture()
def manager_headers(make_user, token_for):
    return bearer(token_for(make_user(email="manager@maharasa.id", role="manager")))


@pytest.fixture()
def outlet_headers(make_user, token_for):
    user = make_user(email="kasir@maharasa.id", role="outlet", outlet_code="OUTLET_001")
    return bearer(token_for(user))


@pytest.fixture()
def penjualan(app_db):
    """ProductID 101 di dua outlet (nama berbeda), 202 hanya di OUTLET_001."""
    app_db.add_all(
        [
            make_sale_row(transaction_id=1, outlet_code="OUTLET_001", sale_date=date(2026, 1, 10)),
            make_sale_row(transaction_id=2, outlet_code="OUTLET_001", sale_date=date(2026, 1, 15)),
            make_sale_row(transaction_id=1, outlet_code="OUTLET_002", sale_date=date(2026, 1, 12)),
        ]
    )
    app_db.add_all(
        [
            make_item_row(1, 1, "OUTLET_001", "COLORPLATE", "Red Lama", product_id=101, sale_date=date(2026, 1, 10)),
            make_item_row(2, 2, "OUTLET_001", "COLORPLATE", " Red ", product_id=101, sale_date=date(2026, 1, 15)),
            make_item_row(3, 2, "OUTLET_001", "PROMO", "Birthday Cake", product_id=202, sale_date=date(2026, 1, 15)),
            make_item_row(1, 1, "OUTLET_002", "COLORPLATE", "Merah", product_id=101, sale_date=date(2026, 1, 12)),
        ]
    )
    app_db.commit()


def _buat(client, headers, **body):
    body = {"code": "P-001", "name": "Red Plate", **body}
    return client.post("/api/products", json=body, headers=headers)


# ---------------------------------------------------------------------------
# /api/products
# ---------------------------------------------------------------------------


class TestCreateProduct:

    def test_kode_dinormalisasi_dan_field_opsional_kosong(self, client, admin_headers, app_db):
        response = _buat(client, admin_headers, code=" p-001 ", name=" Red Plate ")

        assert response.status_code == 201
        data = response.json()["data"]
        assert (data["code"], data["name"], data["is_active"]) == ("P-001", "Red Plate", True)
        assert (data["category"], data["unit"], data["price"], data["brand"]) == (None, None, 0, None)
        assert data["pos_mappings"] == []
        assert app_db.query(Product).one().code == "P-001"

    def test_semua_field(self, client, admin_headers, make_brand):
        brand = make_brand("MHR", "Maharasa")

        response = _buat(
            client, admin_headers, category=" Plate ", unit=" pcs ", price=25000.5, brand_id=brand.id, is_active=False
        )

        assert response.status_code == 201
        data = response.json()["data"]
        assert (data["category"], data["unit"], data["price"], data["is_active"]) == ("Plate", "pcs", 25000.5, False)
        assert data["brand"] == {"id": brand.id, "code": "MHR", "name": "Maharasa"}

    def test_kode_sudah_ada_ditolak_termasuk_yang_nonaktif(self, client, admin_headers):
        _buat(client, admin_headers, is_active=False)

        response = _buat(client, admin_headers, code="p-001 ", name="Lagi")

        assert response.status_code == 409

    def test_brand_tidak_ada_ditolak(self, client, admin_headers, app_db):
        response = _buat(client, admin_headers, brand_id=999)

        assert response.status_code == 422
        assert app_db.query(Product).count() == 0

    def test_brand_nonaktif_ditolak(self, client, admin_headers, make_brand):
        brand = make_brand(is_active=False)

        assert _buat(client, admin_headers, brand_id=brand.id).status_code == 422

    @pytest.mark.parametrize(
        "body",
        [
            {"code": "   ", "name": "Red"},
            {"code": "P-001", "name": "   "},
            {"code": "X" * 51, "name": "Red"},
            {"code": "P-001"},
            {"code": "P-001", "name": "Red", "price": -1},
        ],
    )
    def test_data_tidak_valid_ditolak(self, client, admin_headers, app_db, body):
        response = client.post("/api/products", json=body, headers=admin_headers)

        assert response.status_code == 422
        assert app_db.query(Product).count() == 0

    def test_manager_tidak_boleh_menulis(self, client, manager_headers):
        assert _buat(client, manager_headers).status_code == 403


class TestListProduct:

    def test_semua_produk_terurut_kode_termasuk_nonaktif(self, client, admin_headers):
        _buat(client, admin_headers, code="P-002", name="Blue")
        _buat(client, admin_headers, code="P-001", name="Red", is_active=False)

        response = client.get("/api/products", headers=admin_headers)

        assert response.status_code == 200
        assert [(p["code"], p["is_active"]) for p in response.json()["data"]] == [("P-001", False), ("P-002", True)]

    def test_manager_boleh_membaca(self, client, manager_headers):
        assert client.get("/api/products", headers=manager_headers).status_code == 200

    def test_role_outlet_ditolak(self, client, outlet_headers):
        assert client.get("/api/products", headers=outlet_headers).status_code == 403

    def test_tanpa_token_ditolak(self, client):
        assert client.get("/api/products").status_code == 401


class TestDetailProduct:

    def test_detail(self, client, admin_headers, manager_headers):
        product_id = _buat(client, admin_headers).json()["data"]["id"]

        response = client.get(f"/api/products/{product_id}", headers=manager_headers)

        assert response.status_code == 200
        assert response.json()["data"]["code"] == "P-001"

    def test_tidak_ditemukan(self, client, admin_headers):
        assert client.get("/api/products/999", headers=admin_headers).status_code == 404


class TestUpdateProduct:

    def test_ubah_field(self, client, admin_headers, make_brand):
        brand = make_brand("MHR")
        product_id = _buat(client, admin_headers, category="Plate").json()["data"]["id"]

        response = client.patch(
            f"/api/products/{product_id}",
            json={"name": "Red Plate Baru", "unit": "porsi", "price": 30000, "brand_id": brand.id, "is_active": False},
            headers=admin_headers,
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert (data["code"], data["name"], data["unit"], data["price"], data["is_active"]) == (
            "P-001",
            "Red Plate Baru",
            "porsi",
            30000,
            False,
        )
        assert data["category"] == "Plate"  # tidak dikirim = tidak berubah
        assert data["brand"]["code"] == "MHR"
        assert data["updated_at"] is not None

    def test_null_mengosongkan_field_opsional(self, client, admin_headers, make_brand):
        brand = make_brand()
        product_id = _buat(client, admin_headers, category="Plate", unit="pcs", brand_id=brand.id).json()["data"]["id"]

        response = client.patch(
            f"/api/products/{product_id}",
            json={"category": None, "unit": "  ", "brand_id": None},
            headers=admin_headers,
        )

        data = response.json()["data"]
        assert (data["category"], data["unit"], data["brand"]) == (None, None, None)

    def test_kode_tidak_bisa_diubah(self, client, admin_headers):
        product_id = _buat(client, admin_headers).json()["data"]["id"]

        response = client.patch(
            f"/api/products/{product_id}", json={"code": "LAIN", "is_active": True}, headers=admin_headers
        )

        assert response.json()["data"]["code"] == "P-001"

    def test_brand_nonaktif_ditolak(self, client, admin_headers, make_brand):
        brand = make_brand(is_active=False)
        product_id = _buat(client, admin_headers).json()["data"]["id"]

        response = client.patch(f"/api/products/{product_id}", json={"brand_id": brand.id}, headers=admin_headers)

        assert response.status_code == 422

    @pytest.mark.parametrize("body", [{}, {"name": None}, {"price": None}, {"price": -5}, {"is_active": None}])
    def test_body_tidak_valid_ditolak(self, client, admin_headers, body):
        product_id = _buat(client, admin_headers).json()["data"]["id"]

        assert client.patch(f"/api/products/{product_id}", json=body, headers=admin_headers).status_code == 422

    def test_tidak_ditemukan(self, client, admin_headers):
        assert client.patch("/api/products/999", json={"is_active": False}, headers=admin_headers).status_code == 404

    def test_manager_tidak_boleh_menulis(self, client, admin_headers, manager_headers):
        product_id = _buat(client, admin_headers).json()["data"]["id"]

        response = client.patch(f"/api/products/{product_id}", json={"is_active": False}, headers=manager_headers)

        assert response.status_code == 403


# ---------------------------------------------------------------------------
# /api/products/pos-candidates
# ---------------------------------------------------------------------------


class TestPosCandidates:

    def test_satu_baris_per_outlet_dan_productid_dengan_nama_terbaru(self, client, admin_headers, penjualan):
        response = client.get("/api/products/pos-candidates", headers=admin_headers)

        assert response.status_code == 200
        assert [
            (c["outlet_code"], c["pos_product_id"], c["pos_product_name"], c["pos_product_group"], c["last_sale_date"])
            for c in response.json()["data"]
        ] == [
            ("OUTLET_001", 101, "Red", "COLORPLATE", "2026-01-15"),
            ("OUTLET_001", 202, "Birthday Cake", "PROMO", "2026-01-15"),
            ("OUTLET_002", 101, "Merah", "COLORPLATE", "2026-01-12"),
        ]

    def test_filter_outlet_dan_pencarian(self, client, admin_headers, penjualan):
        response = client.get(
            "/api/products/pos-candidates", params={"outlet": "OUTLET_001", "q": "cake"}, headers=admin_headers
        )
        assert [c["pos_product_id"] for c in response.json()["data"]] == [202]

        response = client.get("/api/products/pos-candidates", params={"q": "101"}, headers=admin_headers)
        assert [(c["outlet_code"], c["pos_product_id"]) for c in response.json()["data"]] == [
            ("OUTLET_001", 101),
            ("OUTLET_002", 101),
        ]

    def test_menampilkan_produk_master_yang_sudah_dipetakan(self, client, admin_headers, penjualan):
        product_id = _buat(client, admin_headers).json()["data"]["id"]
        client.post(
            f"/api/products/{product_id}/pos-mappings",
            json={"outlet_code": "OUTLET_002", "pos_product_id": 101},
            headers=admin_headers,
        )

        data = client.get("/api/products/pos-candidates", params={"q": "101"}, headers=admin_headers).json()["data"]

        assert [(c["outlet_code"], c["mapped_product_code"]) for c in data] == [
            ("OUTLET_001", None),
            ("OUTLET_002", "P-001"),
        ]

    def test_manager_ditolak(self, client, manager_headers):
        assert client.get("/api/products/pos-candidates", headers=manager_headers).status_code == 403


# ---------------------------------------------------------------------------
# /api/products/{id}/pos-mappings
# ---------------------------------------------------------------------------


class TestPosMapping:

    def _petakan(self, client, headers, product_id, outlet_code="OUTLET_001", pos_product_id=101):
        return client.post(
            f"/api/products/{product_id}/pos-mappings",
            json={"outlet_code": outlet_code, "pos_product_id": pos_product_id},
            headers=headers,
        )

    def test_petakan_menyalin_nama_terbaru_dari_penjualan(self, client, admin_headers, penjualan):
        product_id = _buat(client, admin_headers).json()["data"]["id"]

        response = self._petakan(client, admin_headers, product_id)

        assert response.status_code == 201
        mapping = response.json()["data"]["pos_mappings"][0]
        assert (
            mapping["outlet_code"],
            mapping["pos_product_id"],
            mapping["pos_product_name"],
            mapping["pos_product_group"],
            mapping["is_active"],
        ) == ("OUTLET_001", 101, "Red", "COLORPLATE", True)

    def test_productid_sama_di_outlet_lain_boleh_ke_produk_yang_sama(self, client, admin_headers, penjualan):
        product_id = _buat(client, admin_headers).json()["data"]["id"]
        self._petakan(client, admin_headers, product_id, "OUTLET_001")

        response = self._petakan(client, admin_headers, product_id, "OUTLET_002")

        assert [(m["outlet_code"], m["pos_product_name"]) for m in response.json()["data"]["pos_mappings"]] == [
            ("OUTLET_001", "Red"),
            ("OUTLET_002", "Merah"),
        ]

    def test_productid_yang_tidak_ada_di_penjualan_outlet_itu_ditolak(self, client, admin_headers, penjualan):
        product_id = _buat(client, admin_headers).json()["data"]["id"]

        assert self._petakan(client, admin_headers, product_id, "OUTLET_002", 202).status_code == 422
        assert self._petakan(client, admin_headers, product_id, "OUTLET_009", 101).status_code == 422

    def test_sudah_aktif_di_produk_lain_ditolak(self, client, admin_headers, penjualan, app_db):
        satu = _buat(client, admin_headers, code="P-001").json()["data"]["id"]
        dua = _buat(client, admin_headers, code="P-002").json()["data"]["id"]
        self._petakan(client, admin_headers, satu)

        response = self._petakan(client, admin_headers, dua)

        assert response.status_code == 409
        assert "P-001" in response.json()["detail"]
        assert app_db.query(ProductPosMapping).one().product_id == satu

    def test_sudah_aktif_di_produk_yang_sama_ditolak(self, client, admin_headers, penjualan):
        product_id = _buat(client, admin_headers).json()["data"]["id"]
        self._petakan(client, admin_headers, product_id)

        assert self._petakan(client, admin_headers, product_id).status_code == 409

    def test_nonaktifkan_lalu_pindahkan_memakai_baris_yang_sama(self, client, admin_headers, penjualan, app_db):
        satu = _buat(client, admin_headers, code="P-001").json()["data"]["id"]
        dua = _buat(client, admin_headers, code="P-002").json()["data"]["id"]
        mapping_id = self._petakan(client, admin_headers, satu).json()["data"]["pos_mappings"][0]["id"]

        response = client.patch(
            f"/api/products/{satu}/pos-mappings/{mapping_id}", json={"is_active": False}, headers=admin_headers
        )
        assert response.status_code == 200
        assert response.json()["data"]["pos_mappings"][0]["is_active"] is False

        response = self._petakan(client, admin_headers, dua)
        assert response.status_code == 201
        assert response.json()["data"]["pos_mappings"][0]["is_active"] is True

        # Tidak ada penghapusan: satu baris per (outlet, ProductID), dipindah.
        rows = app_db.query(ProductPosMapping).all()
        assert [(r.outlet_code, r.pos_product_id, r.product_id, r.is_active) for r in rows] == [
            ("OUTLET_001", 101, dua, True)
        ]
        assert client.get(f"/api/products/{satu}", headers=admin_headers).json()["data"]["pos_mappings"] == []

    def test_mapping_milik_produk_lain_tidak_ditemukan(self, client, admin_headers, penjualan):
        satu = _buat(client, admin_headers, code="P-001").json()["data"]["id"]
        dua = _buat(client, admin_headers, code="P-002").json()["data"]["id"]
        mapping_id = self._petakan(client, admin_headers, satu).json()["data"]["pos_mappings"][0]["id"]

        response = client.patch(
            f"/api/products/{dua}/pos-mappings/{mapping_id}", json={"is_active": False}, headers=admin_headers
        )

        assert response.status_code == 404

    def test_produk_tidak_ditemukan(self, client, admin_headers, penjualan):
        assert self._petakan(client, admin_headers, 999).status_code == 404

    def test_produk_nonaktif_ditolak(self, client, admin_headers, penjualan):
        product_id = _buat(client, admin_headers, is_active=False).json()["data"]["id"]

        assert self._petakan(client, admin_headers, product_id).status_code == 422

    @pytest.mark.parametrize(
        "body", [{"outlet_code": "OUTLET_001"}, {"outlet_code": "  ", "pos_product_id": 101}, {"outlet_code": "OUTLET_001", "pos_product_id": 0}]
    )
    def test_body_tidak_valid_ditolak(self, client, admin_headers, penjualan, body):
        product_id = _buat(client, admin_headers).json()["data"]["id"]

        response = client.post(f"/api/products/{product_id}/pos-mappings", json=body, headers=admin_headers)

        assert response.status_code == 422

    def test_manager_tidak_boleh_memetakan(self, client, admin_headers, manager_headers, penjualan):
        product_id = _buat(client, admin_headers).json()["data"]["id"]

        assert self._petakan(client, manager_headers, product_id).status_code == 403
