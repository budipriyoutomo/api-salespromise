"""Test mapping per menu — `/api/product-menus` dan pengaruhnya ke publish.

Aturan yang dijaga:

- menu dikenali lewat ProductID; nama & group hanya salinan dari data penjualan;
- publish mengirim gabungan group aktif + menu aktif;
- tidak ada penghapusan — menu dimatikan lewat `is_active`.
"""

from datetime import date

import pytest

from app.models.product_menu_mapping import ProductMenuMapping
from tests.conftest import bearer, make_item_row, make_sale_row


@pytest.fixture()
def manager_headers(make_user, token_for):
    return bearer(token_for(make_user(email="manager@maharasa.id", role="manager")))


@pytest.fixture()
def data_promo(app_db):
    """Satu transaksi berisi colorplate, PROMO, dan PROMO BANDUNG — mirip data lokal."""
    app_db.add(make_sale_row(transaction_id=1, outlet_code="OUTLET_001", sale_date=date(2026, 1, 15)))
    app_db.add_all(
        [
            make_item_row(order_detail_id=1, transaction_id=1, product_id=200252, product_name="Blue ", qty=2),
            make_item_row(
                order_detail_id=2,
                transaction_id=1,
                product_id=200300,
                product_group="PROMO",
                product_name="F birthday cake",
                qty=1,
            ),
            make_item_row(
                order_detail_id=3,
                transaction_id=1,
                product_id=309747,
                product_group=" PROMO BANDUNG",
                product_name="Chicken Katsu & Medamayaki Don",
                qty=3,
            ),
        ]
    )
    app_db.commit()


@pytest.fixture()
def data_dua_outlet(app_db, data_promo):
    """OUTLET_002 menjual menu colorplate yang sama plus satu menu miliknya sendiri."""
    app_db.add(make_sale_row(transaction_id=2, outlet_code="OUTLET_002", sale_date=date(2026, 1, 20)))
    app_db.add_all(
        [
            make_item_row(
                order_detail_id=1,
                transaction_id=2,
                product_id=200252,
                product_name="Blue ",
                qty=1,
                sale_date=date(2026, 1, 20),
            ),
            make_item_row(
                order_detail_id=2,
                transaction_id=2,
                product_id=400100,
                product_group="FOOD",
                product_name="Nasi Goreng",
                qty=2,
                sale_date=date(2026, 1, 20),
            ),
        ]
    )
    app_db.commit()


class TestCandidates:

    def test_daftar_menu_dari_data(self, client, admin_headers, data_promo):
        response = client.get("/api/product-menus/candidates", headers=admin_headers)

        assert response.status_code == 200
        assert [(r["product_id"], r["product_name"], r["product_group"]) for r in response.json()["data"]] == [
            (200252, "Blue", "COLORPLATE"),
            (200300, "F birthday cake", "PROMO"),
            (309747, "Chicken Katsu & Medamayaki Don", "PROMO BANDUNG"),
        ]
        assert response.json()["data"][0]["last_sale_date"] == "2026-01-15"

    def test_outlet_tempat_menu_terjual_ikut_dikirim(self, client, admin_headers, data_dua_outlet):
        response = client.get("/api/product-menus/candidates", headers=admin_headers)

        outlet = {r["product_id"]: r["outlet_codes"] for r in response.json()["data"]}
        assert outlet[200252] == ["OUTLET_001", "OUTLET_002"]
        assert outlet[200300] == ["OUTLET_001"]
        assert outlet[400100] == ["OUTLET_002"]

    def test_menu_yang_terjual_di_dua_outlet_tidak_jadi_dua_baris(self, client, admin_headers, data_dua_outlet):
        """Mapping berlaku untuk semua outlet — satu menu harus satu baris."""
        response = client.get("/api/product-menus/candidates", headers=admin_headers)

        data = response.json()["data"]
        assert [r["product_id"] for r in data].count(200252) == 1
        # Tanggal terbaru dari kedua outlet, bukan tanggal outlet pertama.
        assert next(r for r in data if r["product_id"] == 200252)["last_sale_date"] == "2026-01-20"

    def test_filter_outlet(self, client, admin_headers, data_dua_outlet):
        response = client.get("/api/product-menus/candidates?outlet=OUTLET_002", headers=admin_headers)

        data = response.json()["data"]
        assert sorted(r["product_id"] for r in data) == [200252, 400100]
        assert all(r["outlet_codes"] == ["OUTLET_002"] for r in data)

    def test_filter_outlet_digabung_dengan_group(self, client, admin_headers, data_dua_outlet):
        response = client.get(
            "/api/product-menus/candidates?outlet=OUTLET_002&product_group=colorplate",
            headers=admin_headers,
        )

        assert [r["product_id"] for r in response.json()["data"]] == [200252]

    def test_filter_outlet_tidak_dikenal_kosong(self, client, admin_headers, data_dua_outlet):
        response = client.get("/api/product-menus/candidates?outlet=OUTLET_999", headers=admin_headers)

        assert response.json()["data"] == []

    def test_filter_group_tidak_peka_kapitalisasi(self, client, admin_headers, data_promo):
        response = client.get("/api/product-menus/candidates?product_group=promo%20bandung", headers=admin_headers)

        assert [r["product_id"] for r in response.json()["data"]] == [309747]

    def test_cari_nama_atau_product_id(self, client, admin_headers, data_promo):
        by_name = client.get("/api/product-menus/candidates?q=birthday", headers=admin_headers)
        by_id = client.get("/api/product-menus/candidates?q=309747", headers=admin_headers)

        assert [r["product_id"] for r in by_name.json()["data"]] == [200300]
        assert [r["product_id"] for r in by_id.json()["data"]] == [309747]

    def test_manager_ditolak(self, client, manager_headers):
        assert client.get("/api/product-menus/candidates", headers=manager_headers).status_code == 403


class TestCreate:

    def test_nama_dan_group_diambil_dari_data(self, client, admin_headers, data_promo):
        response = client.post("/api/product-menus", json={"product_id": 200300}, headers=admin_headers)

        assert response.status_code == 201
        data = response.json()["data"]
        assert (data["product_id"], data["product_name"], data["product_group"], data["is_active"]) == (
            200300,
            "F birthday cake",
            "PROMO",
            True,
        )

    def test_product_id_tidak_ada_di_data_422(self, client, admin_headers, data_promo):
        response = client.post("/api/product-menus", json={"product_id": 999999}, headers=admin_headers)

        assert response.status_code == 422

    @pytest.mark.parametrize("product_id", [0, -1])
    def test_product_id_tidak_valid_422(self, client, admin_headers, product_id):
        assert client.post("/api/product-menus", json={"product_id": product_id}, headers=admin_headers).status_code == 422

    def test_duplikat_409(self, client, admin_headers, data_promo, make_product_menu):
        make_product_menu(product_id=200300, is_active=False)

        response = client.post("/api/product-menus", json={"product_id": 200300}, headers=admin_headers)

        assert response.status_code == 409

    def test_manager_ditolak(self, client, manager_headers, data_promo):
        assert client.post("/api/product-menus", json={"product_id": 200300}, headers=manager_headers).status_code == 403


class TestListDanUpdate:

    def test_list_termasuk_nonaktif(self, client, admin_headers, make_product_menu):
        make_product_menu(product_id=200300, product_name="F birthday cake", product_group="PROMO")
        make_product_menu(product_id=309747, product_name="Chicken Katsu", product_group="PROMO BANDUNG", is_active=False)

        response = client.get("/api/product-menus", headers=admin_headers)

        assert [(r["product_id"], r["is_active"]) for r in response.json()["data"]] == [(200300, True), (309747, False)]

    def test_menonaktifkan(self, client, admin_headers, make_product_menu, app_db):
        row = make_product_menu(product_id=200300)

        response = client.patch(f"/api/product-menus/{row.id}", json={"is_active": False}, headers=admin_headers)

        assert response.status_code == 200
        app_db.expire_all()
        assert app_db.get(ProductMenuMapping, row.id).is_active is False

    def test_id_tidak_dikenal_404(self, client, admin_headers):
        assert client.patch("/api/product-menus/999", json={"is_active": False}, headers=admin_headers).status_code == 404

    def test_tidak_ada_endpoint_hapus(self, client, admin_headers, make_product_menu, app_db):
        row = make_product_menu(product_id=200300)

        assert client.delete(f"/api/product-menus/{row.id}", headers=admin_headers).status_code == 405
        assert app_db.query(ProductMenuMapping).count() == 1


class TestPublishDenganMenu:
    """Query publish dijalankan sungguhan di SQLite, hanya RabbitMQ yang dipalsukan."""

    @pytest.fixture()
    def rabbit(self):
        from app.main import app
        from app.routes.sales_routes import get_rabbitmq_client

        class Fake:
            def __init__(self):
                self.published = []

            def publish(self, exchange, routing_key, payload):
                self.published.append(payload)

        fake = Fake()
        app.dependency_overrides[get_rabbitmq_client] = lambda: fake
        yield fake
        app.dependency_overrides.pop(get_rabbitmq_client, None)

    def _publish(self, client, api_key_headers):
        return client.post("/api/sales/publish", json={"date": "2026-01-15"}, headers=api_key_headers)

    def test_menu_saja_tanpa_group_aktif(self, client, api_key_headers, data_promo, make_product_menu, rabbit):
        make_product_menu(product_id=200300, product_name="F birthday cake", product_group="PROMO")

        response = self._publish(client, api_key_headers)

        assert response.json()["published"] == 1
        assert rabbit.published[0]["data"] == {
            "group": "PROMO",
            "product": "F birthday cake",
            "outlet": "OUTLET_001",
            "date": "2026-01-15",
            "sold": 1,
        }

    def test_gabungan_group_dan_menu(self, client, api_key_headers, data_promo, make_product_group, make_product_menu, rabbit):
        make_product_group("COLORPLATE")
        make_product_menu(product_id=309747)

        self._publish(client, api_key_headers)

        data = [e["data"] for e in rabbit.published]
        assert {"platecolor", "group"} == {next(iter(d)) for d in data}
        assert sorted(d.get("platecolor") or d.get("product") for d in data) == [
            "Blue ",
            "Chicken Katsu & Medamayaki Don",
        ]

    def test_menu_nonaktif_tidak_dipublish(self, client, api_key_headers, data_promo, make_product_menu, rabbit):
        make_product_menu(product_id=200300, is_active=False)

        response = self._publish(client, api_key_headers)

        assert response.json()["message"] == "No active product groups to publish"
        assert rabbit.published == []
