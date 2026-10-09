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


@pytest.fixture(autouse=True)
def brand_bawaan(make_brand):
    """Brand wajib di setiap produk; `_buat` memakainya kalau tidak diberi lain."""
    return make_brand("DEF", "Brand Bawaan")


def _buat(client, headers, **body):
    """Body minimal yang valid: ProductID, Product Code, nama, dan brand.

    Product Code bawaan diturunkan dari ProductID supaya beberapa produk dalam
    satu test tidak bentrok.
    """
    code = body.get("code", "P-001")
    body = {"code": code, "product_code": f"PC-{code.strip().upper()}", "name": "Red Plate", "brand_id": 1, **body}
    return client.post("/api/products", json=body, headers=headers)


# ---------------------------------------------------------------------------
# /api/products
# ---------------------------------------------------------------------------


class TestCreateProduct:

    def test_kode_dinormalisasi_dan_field_opsional_kosong(self, client, admin_headers, app_db, brand_bawaan):
        response = _buat(client, admin_headers, code=" p-001 ", product_code=" sku-9 ", name=" Red Plate ")

        assert response.status_code == 201
        data = response.json()["data"]
        assert (data["code"], data["product_code"], data["name"], data["is_active"]) == (
            "P-001",
            "SKU-9",
            "Red Plate",
            True,
        )
        assert (data["category"], data["subcategory"]) == (None, None)
        assert data["brand"] == {"id": brand_bawaan.id, "code": "DEF", "name": "Brand Bawaan"}
        assert data["pos_mappings"] == []
        # Satuan & harga tidak lagi dipakai API.
        assert "unit" not in data and "price" not in data
        assert app_db.query(Product).one().code == "P-001"

    def test_semua_field(self, client, admin_headers, make_brand):
        brand = make_brand("MHR", "Maharasa")

        response = _buat(
            client, admin_headers, category=" Plate ", subcategory=" Sushi ", brand_id=brand.id, is_active=False
        )

        assert response.status_code == 201
        data = response.json()["data"]
        assert (data["category"], data["subcategory"], data["is_active"]) == ("Plate", "Sushi", False)
        assert data["brand"] == {"id": brand.id, "code": "MHR", "name": "Maharasa"}

    def test_satuan_dan_harga_diabaikan(self, client, admin_headers, app_db):
        """Kolomnya masih ada di database (datanya tidak dihapus), tapi tidak diisi lewat API."""
        response = _buat(client, admin_headers, unit="pcs", price=25000)

        assert response.status_code == 201
        row = app_db.query(Product).one()
        assert (row.unit, row.price) == (None, 0)

    def test_productid_sudah_ada_ditolak_termasuk_yang_nonaktif(self, client, admin_headers):
        _buat(client, admin_headers, is_active=False)

        response = _buat(client, admin_headers, code="p-001 ", product_code="LAIN", name="Lagi")

        assert response.status_code == 409
        assert "P-001" in response.json()["detail"]

    def test_product_code_sudah_dipakai_ditolak(self, client, admin_headers, app_db):
        _buat(client, admin_headers, product_code="SKU-1", is_active=False)

        response = _buat(client, admin_headers, code="P-002", product_code=" sku-1")

        assert response.status_code == 409
        assert "Product Code 'SKU-1'" in response.json()["detail"]
        assert app_db.query(Product).count() == 1

    def test_brand_tidak_ada_ditolak(self, client, admin_headers, app_db):
        response = _buat(client, admin_headers, brand_id=999)

        assert response.status_code == 422
        assert app_db.query(Product).count() == 0

    def test_brand_nonaktif_ditolak(self, client, admin_headers, make_brand):
        brand = make_brand("OFF", is_active=False)

        assert _buat(client, admin_headers, brand_id=brand.id).status_code == 422

    @pytest.mark.parametrize(
        "body",
        [
            {"code": "   ", "product_code": "SKU", "name": "Red", "brand_id": 1},
            {"code": "P-001", "product_code": "   ", "name": "Red", "brand_id": 1},
            {"code": "P-001", "product_code": "SKU", "name": "   ", "brand_id": 1},
            {"code": "X" * 51, "product_code": "SKU", "name": "Red", "brand_id": 1},
            {"code": "P-001", "product_code": "X" * 51, "name": "Red", "brand_id": 1},
            # Field wajib tidak dikirim.
            {"product_code": "SKU", "name": "Red", "brand_id": 1},
            {"code": "P-001", "name": "Red", "brand_id": 1},
            {"code": "P-001", "product_code": "SKU", "brand_id": 1},
            {"code": "P-001", "product_code": "SKU", "name": "Red"},
            {"code": "P-001", "product_code": "SKU", "name": "Red", "brand_id": None},
            {"code": "P-001", "product_code": "SKU", "name": "Red", "brand_id": 1, "subcategory": "X" * 101},
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

    def test_produk_lama_tanpa_product_code_dan_brand_tetap_tampil(self, client, admin_headers, app_db):
        """Produk dari sebelum migrasi 015 belum punya Product Code / brand."""
        app_db.add(Product(code="LAMA", name="Produk Lama", unit="pcs", price=1000))
        app_db.commit()

        [data] = client.get("/api/products", headers=admin_headers).json()["data"]

        assert (data["code"], data["product_code"], data["brand"], data["subcategory"]) == ("LAMA", None, None, None)

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
        assert (response.json()["data"]["code"], response.json()["data"]["product_code"]) == ("P-001", "PC-P-001")

    def test_tidak_ditemukan(self, client, admin_headers):
        assert client.get("/api/products/999", headers=admin_headers).status_code == 404


class TestUpdateProduct:

    def test_ubah_field(self, client, admin_headers, make_brand):
        brand = make_brand("MHR")
        product_id = _buat(client, admin_headers, category="Plate").json()["data"]["id"]

        response = client.patch(
            f"/api/products/{product_id}",
            json={
                "product_code": " sku-baru ",
                "name": "Red Plate Baru",
                "subcategory": "Nigiri",
                "brand_id": brand.id,
                "is_active": False,
            },
            headers=admin_headers,
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert (data["code"], data["product_code"], data["name"], data["subcategory"], data["is_active"]) == (
            "P-001",
            "SKU-BARU",
            "Red Plate Baru",
            "Nigiri",
            False,
        )
        assert data["category"] == "Plate"  # tidak dikirim = tidak berubah
        assert data["brand"]["code"] == "MHR"
        assert data["updated_at"] is not None

    def test_null_mengosongkan_field_opsional(self, client, admin_headers):
        product_id = _buat(client, admin_headers, category="Plate", subcategory="Sushi").json()["data"]["id"]

        response = client.patch(
            f"/api/products/{product_id}",
            json={"category": None, "subcategory": "  "},
            headers=admin_headers,
        )

        data = response.json()["data"]
        assert (data["category"], data["subcategory"]) == (None, None)
        assert data["brand"]["code"] == "DEF"

    def test_product_code_milik_produk_lain_ditolak(self, client, admin_headers):
        _buat(client, admin_headers, code="P-001", product_code="SKU-1")
        dua = _buat(client, admin_headers, code="P-002", product_code="SKU-2").json()["data"]["id"]

        response = client.patch(f"/api/products/{dua}", json={"product_code": "sku-1"}, headers=admin_headers)

        assert response.status_code == 409

    def test_product_code_sendiri_boleh_dikirim_ulang(self, client, admin_headers):
        product_id = _buat(client, admin_headers, product_code="SKU-1").json()["data"]["id"]

        response = client.patch(f"/api/products/{product_id}", json={"product_code": "SKU-1"}, headers=admin_headers)

        assert response.status_code == 200

    def test_produk_lama_dilengkapi_product_code_dan_brand(self, client, admin_headers, app_db, brand_bawaan):
        row = Product(code="LAMA", name="Produk Lama")
        app_db.add(row)
        app_db.commit()

        response = client.patch(
            f"/api/products/{row.id}",
            json={"product_code": "SKU-LAMA", "brand_id": brand_bawaan.id},
            headers=admin_headers,
        )

        assert response.status_code == 200
        assert (response.json()["data"]["product_code"], response.json()["data"]["brand"]["code"]) == (
            "SKU-LAMA",
            "DEF",
        )

    def test_productid_tidak_bisa_diubah(self, client, admin_headers):
        product_id = _buat(client, admin_headers).json()["data"]["id"]

        response = client.patch(
            f"/api/products/{product_id}", json={"code": "LAIN", "is_active": True}, headers=admin_headers
        )

        assert response.json()["data"]["code"] == "P-001"

    def test_brand_nonaktif_ditolak(self, client, admin_headers, make_brand):
        brand = make_brand("OFF", is_active=False)
        product_id = _buat(client, admin_headers).json()["data"]["id"]

        response = client.patch(f"/api/products/{product_id}", json={"brand_id": brand.id}, headers=admin_headers)

        assert response.status_code == 422

    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"name": None},
            {"product_code": None},
            {"product_code": "   "},
            {"brand_id": None},
            {"is_active": None},
        ],
    )
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
        "body",
        [
            {"outlet_code": "OUTLET_001"},
            {"outlet_code": "  ", "pos_product_id": 101},
            {"outlet_code": "OUTLET_001", "pos_product_id": 0},
        ],
    )
    def test_body_tidak_valid_ditolak(self, client, admin_headers, penjualan, body):
        product_id = _buat(client, admin_headers).json()["data"]["id"]

        response = client.post(f"/api/products/{product_id}/pos-mappings", json=body, headers=admin_headers)

        assert response.status_code == 422

    def test_manager_tidak_boleh_memetakan(self, client, admin_headers, manager_headers, penjualan):
        product_id = _buat(client, admin_headers).json()["data"]["id"]

        assert self._petakan(client, manager_headers, product_id).status_code == 403


# ---------------------------------------------------------------------------
# /api/products/import-candidates & /api/products/import
# ---------------------------------------------------------------------------


@pytest.fixture()
def penjualan_brand(app_db, make_brand, map_outlet_brand):
    """MHR: OUTLET_001 & OUTLET_002. XYZ: OUTLET_003. OUTLET_009 tanpa brand.

    ProductID 101 dijual di ketiga outlet (MHR & XYZ), 202 hanya di OUTLET_001.
    """
    mhr = make_brand("MHR", "Maharasa")
    xyz = make_brand("XYZ", "Brand XYZ")
    map_outlet_brand("OUTLET_001", mhr)
    map_outlet_brand("OUTLET_002", mhr)
    map_outlet_brand("OUTLET_003", xyz)

    def jual(tid, outlet, tanggal, pid, nama, grup="COLORPLATE", dept="SUSHI"):
        app_db.add(make_sale_row(transaction_id=tid, outlet_code=outlet, sale_date=tanggal))
        app_db.add(make_item_row(1, tid, outlet, grup, nama, product_id=pid, sale_date=tanggal, product_dept=dept))

    jual(1, "OUTLET_001", date(2026, 1, 10), 101, "Red Lama")
    jual(2, "OUTLET_001", date(2026, 1, 15), 101, " Red ")
    jual(3, "OUTLET_002", date(2026, 1, 12), 101, "Merah")
    jual(4, "OUTLET_001", date(2026, 1, 15), 202, "Birthday Cake", grup="PROMO", dept="CAKE")
    jual(5, "OUTLET_003", date(2026, 1, 14), 101, "Red XYZ")
    jual(6, "OUTLET_009", date(2026, 1, 14), 303, "Tanpa Brand")
    app_db.commit()
    return {"MHR": mhr, "XYZ": xyz}


class TestImportCandidates:

    URL = "/api/products/import-candidates"

    def _data(self, client, headers, **params):
        response = client.get(self.URL, params=params, headers=headers)
        assert response.status_code == 200, response.text
        return response.json()["data"]

    def test_digabung_per_brand_dan_productid(self, client, admin_headers, penjualan_brand):
        data = self._data(client, admin_headers)

        assert [(d["brand_code"], d["pos_product_id"], d["proposed_code"]) for d in data] == [
            ("MHR", 101, "MHR-101"),
            ("MHR", 202, "MHR-202"),
            ("XYZ", 101, "XYZ-101"),
        ]
        mhr_101 = data[0]
        # Nama / Group / Dept dari penjualan terakhir di brand itu.
        assert (mhr_101["pos_product_name"], mhr_101["pos_product_group"], mhr_101["pos_product_dept"]) == (
            "Red",
            "COLORPLATE",
            "SUSHI",
        )
        assert mhr_101["outlet_codes"] == ["OUTLET_001", "OUTLET_002"]
        assert mhr_101["unmapped_outlet_codes"] == ["OUTLET_001", "OUTLET_002"]
        assert (mhr_101["status"], mhr_101["existing_product_id"], mhr_101["last_sale_date"]) == (
            "baru",
            None,
            "2026-01-15",
        )

    def test_outlet_tanpa_brand_atau_brand_nonaktif_tidak_ikut(self, client, admin_headers, penjualan_brand, app_db):
        penjualan_brand["XYZ"].is_active = False
        app_db.commit()

        data = self._data(client, admin_headers)

        assert {d["brand_code"] for d in data} == {"MHR"}
        assert 303 not in {d["pos_product_id"] for d in data}

    def test_filter_brand_dan_pencarian(self, client, admin_headers, penjualan_brand):
        xyz = penjualan_brand["XYZ"].id

        assert [d["proposed_code"] for d in self._data(client, admin_headers, brand_id=xyz)] == ["XYZ-101"]
        assert [d["proposed_code"] for d in self._data(client, admin_headers, q="cake")] == ["MHR-202"]
        assert [d["proposed_code"] for d in self._data(client, admin_headers, q="202")] == ["MHR-202"]

    def test_outlet_yang_sudah_dipetakan_tidak_dihitung(self, client, admin_headers, penjualan_brand, app_db):
        produk = Product(code="P-001", product_code="P-001", name="Red", brand_id=penjualan_brand["MHR"].id)
        app_db.add(produk)
        app_db.flush()
        app_db.add(ProductPosMapping(product_id=produk.id, outlet_code="OUTLET_001", pos_product_id=101))
        app_db.add(ProductPosMapping(product_id=produk.id, outlet_code="OUTLET_001", pos_product_id=202))
        app_db.commit()

        data = self._data(client, admin_headers, brand_id=penjualan_brand["MHR"].id)

        # 202 hanya di OUTLET_001 yang sudah dipetakan → tidak jadi kandidat.
        [mhr_101] = data
        assert (mhr_101["outlet_codes"], mhr_101["unmapped_outlet_codes"]) == (
            ["OUTLET_001", "OUTLET_002"],
            ["OUTLET_002"],
        )

    def test_produk_dengan_kode_usulan_sudah_ada(self, client, admin_headers, penjualan_brand, app_db):
        mhr, xyz = penjualan_brand["MHR"].id, penjualan_brand["XYZ"].id
        app_db.add_all(
            [
                Product(code="MHR-101", product_code="MHR-101", name="Red", brand_id=mhr),
                Product(code="MHR-202", product_code="LAIN", name="Cake", brand_id=mhr, is_active=False),
                Product(code="ZZZ", product_code="XYZ-101", name="Lain", brand_id=xyz),
            ]
        )
        app_db.commit()

        status = {d["proposed_code"]: (d["status"], d["reason"]) for d in self._data(client, admin_headers)}

        assert status["MHR-101"] == ("tambah_outlet", None)
        assert status["MHR-202"] == ("bentrok", "Produk MHR-202 sudah ada tetapi nonaktif")
        assert status["XYZ-101"] == ("bentrok", "Product Code XYZ-101 sudah dipakai produk lain")

    def test_brand_lain_dengan_kode_sama_bentrok(self, client, admin_headers, penjualan_brand, app_db):
        app_db.add(Product(code="MHR-202", product_code="MHR-202", name="Cake", brand_id=penjualan_brand["XYZ"].id))
        app_db.commit()

        [d] = self._data(client, admin_headers, q="202")
        assert (d["status"], d["reason"]) == ("bentrok", "Produk MHR-202 sudah ada dengan brand lain")

    def test_hanya_admin(self, client, manager_headers):
        assert client.get(self.URL, headers=manager_headers).status_code == 403


class TestImportProducts:

    URL = "/api/products/import"

    def _impor(self, client, headers, *items):
        body = {"items": [{"brand_id": b, "pos_product_id": p} for b, p in items]}
        return client.post(self.URL, json=body, headers=headers)

    def test_membuat_produk_dan_memetakan_semua_outlet_brand(self, client, admin_headers, penjualan_brand, app_db):
        mhr = penjualan_brand["MHR"].id

        response = self._impor(client, admin_headers, (mhr, 101))

        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert (data["created"], data["added"], data["skipped"]) == (1, 0, 0)
        [hasil] = data["results"]
        assert (hasil["status"], hasil["code"], hasil["mapped_outlets"]) == (
            "dibuat",
            "MHR-101",
            ["OUTLET_001", "OUTLET_002"],
        )

        produk = app_db.get(Product, hasil["product_id"])
        assert (produk.code, produk.product_code, produk.name, produk.category, produk.subcategory) == (
            "MHR-101",
            "MHR-101",
            "Red",
            "COLORPLATE",
            "SUSHI",
        )
        assert (produk.brand_id, produk.is_active) == (mhr, True)
        assert sorted(
            (m.outlet_code, m.pos_product_id, m.pos_product_name, m.is_active) for m in produk.pos_mappings
        ) == [
            ("OUTLET_001", 101, "Red", True),
            ("OUTLET_002", 101, "Merah", True),
        ]

        # Sudah dipetakan semua → tidak muncul lagi sebagai kandidat.
        sisa = client.get("/api/products/import-candidates", headers=admin_headers).json()["data"]
        assert "MHR-101" not in {d["proposed_code"] for d in sisa}

    def test_outlet_baru_ditambahkan_ke_produk_yang_sudah_ada(
        self, client, admin_headers, penjualan_brand, app_db, map_outlet_brand
    ):
        mhr = penjualan_brand["MHR"]
        self._impor(client, admin_headers, (mhr.id, 101))
        map_outlet_brand("OUTLET_004", mhr)
        app_db.add(make_sale_row(transaction_id=7, outlet_code="OUTLET_004", sale_date=date(2026, 1, 20)))
        app_db.add(make_item_row(1, 7, "OUTLET_004", "COLORPLATE", "Red", product_id=101, sale_date=date(2026, 1, 20)))
        app_db.commit()

        data = self._impor(client, admin_headers, (mhr.id, 101)).json()["data"]

        assert (data["created"], data["added"]) == (0, 1)
        assert data["results"][0]["mapped_outlets"] == ["OUTLET_004"]
        assert app_db.query(Product).filter_by(code="MHR-101").count() == 1
        assert app_db.query(ProductPosMapping).filter_by(pos_product_id=101, is_active=True).count() == 3

    def test_mapping_nonaktif_dipakai_ulang(self, client, admin_headers, penjualan_brand, app_db):
        lama = Product(code="P-LAMA", product_code="P-LAMA", name="Lama", brand_id=penjualan_brand["MHR"].id)
        app_db.add(lama)
        app_db.flush()
        app_db.add(ProductPosMapping(product_id=lama.id, outlet_code="OUTLET_002", pos_product_id=101, is_active=False))
        app_db.commit()

        self._impor(client, admin_headers, (penjualan_brand["MHR"].id, 101))

        [row] = app_db.query(ProductPosMapping).filter_by(outlet_code="OUTLET_002", pos_product_id=101).all()
        assert (row.product.code, row.is_active) == ("MHR-101", True)

    def test_yang_bentrok_atau_basi_dilewati_yang_lain_tetap_tersimpan(
        self, client, admin_headers, penjualan_brand, app_db
    ):
        mhr = penjualan_brand["MHR"].id
        app_db.add(Product(code="MHR-202", product_code="MHR-202", name="Cake", brand_id=mhr, is_active=False))
        app_db.commit()

        data = self._impor(client, admin_headers, (mhr, 101), (mhr, 202), (mhr, 999)).json()["data"]

        assert (data["created"], data["added"], data["skipped"]) == (1, 0, 2)
        alasan = {h["pos_product_id"]: (h["status"], h["reason"]) for h in data["results"]}
        assert alasan[101] == ("dibuat", None)
        assert alasan[202] == ("dilewati", "Produk MHR-202 sudah ada tetapi nonaktif")
        assert alasan[999] == ("dilewati", "Tidak ada outlet brand ini yang belum dipetakan")
        assert app_db.query(Product).filter_by(code="MHR-101").count() == 1

    def test_item_ganda_hanya_diproses_sekali(self, client, admin_headers, penjualan_brand):
        mhr = penjualan_brand["MHR"].id

        data = self._impor(client, admin_headers, (mhr, 101), (mhr, 101)).json()["data"]

        assert len(data["results"]) == 1

    def test_teks_panjang_dipotong_sesuai_kolom(self, client, admin_headers, penjualan_brand, app_db):
        mhr = penjualan_brand["MHR"].id
        app_db.add(make_sale_row(transaction_id=8, outlet_code="OUTLET_002", sale_date=date(2026, 1, 20)))
        app_db.add(
            make_item_row(
                1,
                8,
                "OUTLET_002",
                "G" * 150,
                "Panjang",
                product_id=505,
                sale_date=date(2026, 1, 20),
                product_dept="D" * 150,
            )
        )
        app_db.commit()

        [hasil] = self._impor(client, admin_headers, (mhr, 505)).json()["data"]["results"]

        produk = app_db.get(Product, hasil["product_id"])
        assert (len(produk.category), len(produk.subcategory)) == (100, 100)

    @pytest.mark.parametrize("body", [{"items": []}, {"items": [{"brand_id": 0, "pos_product_id": 1}]}, {}])
    def test_body_tidak_valid_ditolak(self, client, admin_headers, body):
        assert client.post(self.URL, json=body, headers=admin_headers).status_code == 422

    def test_hanya_admin(self, client, manager_headers):
        assert self._impor(client, manager_headers, (1, 101)).status_code == 403
