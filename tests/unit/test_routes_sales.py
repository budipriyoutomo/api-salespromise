"""Test app/routes/sales_routes.py.

Pembagian autentikasi setelah item 1.2:

- `GET /api/sales/` dan `/colorplate` → JWT user (dashboard)
- `POST /api/sales/publish`           → API key outlet (dipicu mesin POS)
"""

from datetime import date
from types import SimpleNamespace

import pytest

from app.routes.sales_routes import get_rabbitmq_client
from tests.conftest import bearer


def colorplate_row(
    product_name="RED",
    outlet_code="OUTLET_001",
    sale_date=date(2026, 1, 15),
    sold=4,
    product_group="COLORPLATE",
):
    """Meniru bentuk baris hasil query agregat (Row dengan atribut bernama)."""
    return SimpleNamespace(
        product_group=product_group,
        product_name=product_name,
        outlet_code=outlet_code,
        sale_date=sale_date,
        sold=sold,
    )


class FakeRabbitMQ:
    def __init__(self, error=None):
        self.published = []
        self._error = error

    def publish(self, exchange, routing_key, payload):
        if self._error:
            raise self._error
        self.published.append({"exchange": exchange, "routing_key": routing_key, "payload": payload})


@pytest.fixture()
def mock_service(monkeypatch):
    """Ganti method SalesService yang dipakai sales_routes, rekam pemanggilannya."""
    calls = {"get_sales": [], "count_sales": [], "get_sales_colorplate": [], "get_sales_by_product_groups": []}

    def _install(get_sales=None, colorplate=None, total=None, get_sales_error=None, colorplate_error=None):
        """`colorplate` / `colorplate_error` dipakai dua query yang sama bentuknya:
        `/colorplate` (get_sales_colorplate) dan publish (get_sales_by_product_groups)."""
        def fake_get_sales(db, outlet=None, start_date=None, end_date=None, limit=None, offset=0):
            calls["get_sales"].append(
                {"outlet": outlet, "start_date": start_date, "end_date": end_date, "limit": limit, "offset": offset}
            )
            if get_sales_error:
                raise get_sales_error
            return get_sales if get_sales is not None else []

        def fake_count(db, outlet=None, start_date=None, end_date=None):
            calls["count_sales"].append({"outlet": outlet, "start_date": start_date, "end_date": end_date})
            if total is not None:
                return total
            return len(get_sales) if get_sales else 0

        def fake_colorplate(db, outlet=None, start_date=None, end_date=None):
            calls["get_sales_colorplate"].append(
                {"outlet": outlet, "start_date": start_date, "end_date": end_date}
            )
            if colorplate_error:
                raise colorplate_error
            return colorplate if colorplate is not None else []

        def fake_by_groups(db, product_groups, outlet=None, start_date=None, end_date=None):
            calls["get_sales_by_product_groups"].append(
                {"product_groups": list(product_groups), "outlet": outlet, "start_date": start_date, "end_date": end_date}
            )
            if colorplate_error:
                raise colorplate_error
            return colorplate if colorplate is not None else []

        monkeypatch.setattr(
            "app.routes.sales_routes.SalesService.get_sales_by_product_groups", staticmethod(fake_by_groups)
        )
        monkeypatch.setattr("app.routes.sales_routes.SalesService.get_sales", staticmethod(fake_get_sales))
        monkeypatch.setattr("app.routes.sales_routes.SalesService.count_sales", staticmethod(fake_count))
        monkeypatch.setattr(
            "app.routes.sales_routes.SalesService.get_sales_colorplate", staticmethod(fake_colorplate)
        )
        return calls

    return _install


@pytest.fixture()
def rabbit():
    """Pasang RabbitMQ palsu lewat dependency override."""
    from app.main import app

    def _install(error=None):
        fake = FakeRabbitMQ(error=error)
        app.dependency_overrides[get_rabbitmq_client] = lambda: fake
        return fake

    return _install


class TestGetSales:

    def test_sukses_mengembalikan_data_dan_pagination(self, client, admin_headers, mock_service):
        mock_service(get_sales=[], total=0)

        response = client.get("/api/sales/", headers=admin_headers)

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"] == []
        assert body["pagination"] == {"limit": 50, "offset": 0, "total": 0, "has_more": False}

    def test_query_param_diteruskan_ke_service(self, client, admin_headers, mock_service):
        calls = mock_service()

        client.get(
            "/api/sales/?outlet=OUTLET_001&start_date=2026-01-01&end_date=2026-01-31&limit=10&offset=20",
            headers=admin_headers,
        )

        assert calls["get_sales"][0] == {
            "outlet": "OUTLET_001",
            "start_date": date(2026, 1, 1),
            "end_date": date(2026, 1, 31),
            "limit": 10,
            "offset": 20,
        }

    def test_tanggal_di_parse_jadi_objek_date(self, client, admin_headers, mock_service):
        """Item 1.9 — dulu diteruskan sebagai string mentah tanpa validasi."""
        calls = mock_service()

        client.get("/api/sales/?start_date=2026-01-01", headers=admin_headers)

        assert isinstance(calls["get_sales"][0]["start_date"], date)

    def test_tanggal_format_salah_ditolak_422(self, client, admin_headers, mock_service):
        mock_service()

        response = client.get("/api/sales/?start_date=01-01-2026", headers=admin_headers)

        assert response.status_code == 422

    def test_limit_melebihi_maksimum_ditolak_422(self, client, admin_headers, mock_service):
        mock_service()

        response = client.get("/api/sales/?limit=99999", headers=admin_headers)

        assert response.status_code == 422

    def test_offset_negatif_ditolak_422(self, client, admin_headers, mock_service):
        mock_service()

        response = client.get("/api/sales/?offset=-1", headers=admin_headers)

        assert response.status_code == 422

    def test_has_more_true_saat_masih_ada_halaman_berikutnya(self, client, admin_headers, mock_service, persisted_sales):
        mock_service(get_sales=persisted_sales(3), total=10)

        response = client.get("/api/sales/?limit=3", headers=admin_headers)

        assert response.json()["pagination"]["has_more"] is True
        assert response.json()["pagination"]["total"] == 10

    def test_has_more_false_di_halaman_terakhir(self, client, admin_headers, mock_service, persisted_sales):
        mock_service(get_sales=persisted_sales(1), total=1)

        response = client.get("/api/sales/", headers=admin_headers)

        assert response.json()["pagination"]["has_more"] is False

    def test_bentuk_baris_sesuai_response_model(self, client, admin_headers, mock_service, persisted_sales):
        """Item 1.8 — objek ORM tidak lagi dikirim mentah."""
        mock_service(get_sales=persisted_sales(1, transaction_id=777), total=1)

        row = client.get("/api/sales/", headers=admin_headers).json()["data"][0]

        assert row["transaction_id"] == 777
        assert row["outlet_code"] == "OUTLET_001"
        assert row["receipt_total_amount"] == 150000.0
        # kolom internal tidak ikut bocor ke frontend
        assert "no_print_bill_detail" not in row
        assert "bill_detail_reference_no" not in row

    def test_service_error_mengembalikan_500(self, client, admin_headers, mock_service):
        mock_service(get_sales_error=RuntimeError("db mati"))

        response = client.get("/api/sales/", headers=admin_headers)

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to fetch sales"

    def test_pesan_error_internal_tidak_bocor_ke_client(self, client, admin_headers, mock_service):
        mock_service(get_sales_error=RuntimeError("koneksi ke 10.0.0.5 gagal"))

        response = client.get("/api/sales/", headers=admin_headers)

        assert "10.0.0.5" not in response.text

    def test_count_memakai_filter_yang_sama(self, client, admin_headers, mock_service):
        """Kalau filternya beda, total pagination jadi menyesatkan."""
        calls = mock_service()

        client.get("/api/sales/?outlet=OUTLET_002&start_date=2026-01-01", headers=admin_headers)

        assert calls["count_sales"][0] == {
            "outlet": "OUTLET_002",
            "start_date": date(2026, 1, 1),
            "end_date": None,
        }


class TestGetSalesColorplate:

    def test_sukses_mengembalikan_data(self, client, admin_headers, mock_service):
        mock_service(colorplate=[colorplate_row()])

        response = client.get("/api/sales/colorplate", headers=admin_headers)

        assert response.status_code == 200
        assert response.json()["success"] is True
        assert response.json()["data"][0]["product_name"] == "RED"

    def test_outlet_di_scope_dari_identitas(self, client, make_user, token_for, mock_service):
        """Dulu route ini memakai class `Request` sehingga selalu 500."""
        calls = mock_service(colorplate=[])
        user = make_user(email="kasir@maharasa.id", role="outlet", outlet_code="OUTLET_007")

        response = client.get("/api/sales/colorplate", headers=bearer(token_for(user)))

        assert response.status_code == 200
        assert calls["get_sales_colorplate"][0]["outlet"] == "OUTLET_007"

    def test_rentang_tanggal_diteruskan(self, client, admin_headers, mock_service):
        calls = mock_service(colorplate=[])

        client.get(
            "/api/sales/colorplate?start_date=2026-01-01&end_date=2026-01-31",
            headers=admin_headers,
        )

        assert calls["get_sales_colorplate"][0]["start_date"] == date(2026, 1, 1)
        assert calls["get_sales_colorplate"][0]["end_date"] == date(2026, 1, 31)

    def test_user_outlet_tidak_bisa_meminta_outlet_lain(self, client, make_user, token_for, mock_service):
        mock_service(colorplate=[])
        user = make_user(email="kasir@maharasa.id", role="outlet", outlet_code="OUTLET_001")

        response = client.get("/api/sales/colorplate?outlet=OUTLET_002", headers=bearer(token_for(user)))

        assert response.status_code == 403

    def test_service_error_mengembalikan_500(self, client, admin_headers, mock_service):
        mock_service(colorplate_error=RuntimeError("db mati"))

        response = client.get("/api/sales/colorplate", headers=admin_headers)

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to fetch colorplate sales"


class TestPublishSales:
    """Tetap memakai API key outlet — dipicu mesin POS, bukan dashboard.

    Sejak Fase 6 group yang dipublish dibaca dari `product_group_mappings`.
    DB test tidak menjalankan migrasi, jadi seed COLORPLATE dibuat di sini.
    """

    @pytest.fixture(autouse=True)
    def colorplate_aktif(self, make_product_group):
        return make_product_group("COLORPLATE")

    def test_tanpa_data_tidak_mempublish_apa_pun(self, client, api_key_headers, mock_service, rabbit):
        mock_service(colorplate=[])
        fake = rabbit()

        response = client.post("/api/sales/publish", json={"date": "2026-01-15"}, headers=api_key_headers)

        assert response.status_code == 200
        assert response.json()["message"] == "No sales data to publish"
        assert response.json()["published"] == 0
        assert fake.published == []

    def test_mempublish_satu_event_per_baris(self, client, api_key_headers, mock_service, rabbit):
        mock_service(colorplate=[colorplate_row(product_name="RED"), colorplate_row(product_name="BLUE")])
        fake = rabbit()

        response = client.post("/api/sales/publish", json={"date": "2026-01-15"}, headers=api_key_headers)

        assert response.status_code == 200
        assert response.json()["message"] == "2 event(s) published"
        assert response.json()["published"] == 2
        assert len(fake.published) == 2

    def test_outlet_dan_tanggal_ada_di_response(self, client, api_key_headers, mock_service, rabbit):
        mock_service(colorplate=[colorplate_row()])
        rabbit()

        response = client.post("/api/sales/publish", json={"date": "2026-01-15"}, headers=api_key_headers)

        assert response.json()["outlet"] == "OUTLET_001"
        assert response.json()["date"] == "2026-01-15"

    def test_outlet_diambil_dari_api_key(self, client, make_api_key, mock_service, rabbit):
        calls = mock_service(colorplate=[])
        rabbit()
        raw = make_api_key(outlet_code="OUTLET_003")

        client.post("/api/sales/publish", json={"date": "2026-01-15"}, headers=bearer(raw))

        assert calls["get_sales_by_product_groups"][0]["outlet"] == "OUTLET_003"

    def test_tanggal_diteruskan_sebagai_rentang_satu_hari(self, client, api_key_headers, mock_service, rabbit):
        calls = mock_service(colorplate=[])
        rabbit()

        client.post("/api/sales/publish", json={"date": "2026-01-15"}, headers=api_key_headers)

        assert calls["get_sales_by_product_groups"][0]["start_date"] == date(2026, 1, 15)
        assert calls["get_sales_by_product_groups"][0]["end_date"] == date(2026, 1, 15)

    def test_struktur_event_yang_dipublish(self, client, api_key_headers, mock_service, rabbit):
        """Kontrak dengan consumer — kalau berubah, consumer ikut rusak."""
        mock_service(colorplate=[colorplate_row(product_name="RED", outlet_code="OUTLET_001", sold=4)])
        fake = rabbit()

        client.post("/api/sales/publish", json={"date": "2026-01-15"}, headers=api_key_headers)
        event = fake.published[0]["payload"]

        assert event["event"] == "posdata.created"
        assert event["data"] == {
            "platecolor": "RED",
            "outlet": "OUTLET_001",
            "date": "2026-01-15",
            "sold": 4,
        }
        assert event["meta"]["source"] == "sync-sales-service"
        assert event["meta"]["version"] == "1.0"
        assert "timestamp" in event["meta"]

    def test_exchange_dan_routing_key_default(self, client, api_key_headers, mock_service, rabbit):
        mock_service(colorplate=[colorplate_row()])
        fake = rabbit()

        client.post("/api/sales/publish", json={"date": "2026-01-15"}, headers=api_key_headers)

        assert fake.published[0]["exchange"] == "posdata_exchange"
        assert fake.published[0]["routing_key"] == "posdata.created"

    def test_exchange_dan_routing_key_bisa_dioverride(self, client, api_key_headers, mock_service, rabbit):
        mock_service(colorplate=[colorplate_row()])
        fake = rabbit()

        client.post(
            "/api/sales/publish",
            json={"date": "2026-01-15", "exchange": "lain_exchange", "routing_key": "lain.created"},
            headers=api_key_headers,
        )

        assert fake.published[0]["exchange"] == "lain_exchange"
        assert fake.published[0]["routing_key"] == "lain.created"
        assert fake.published[0]["payload"]["event"] == "lain.created"

    def test_sold_dikonversi_ke_integer(self, client, api_key_headers, mock_service, rabbit):
        """`int()` memotong desimal, bukan membulatkan — 2.9 jadi 2."""
        mock_service(colorplate=[colorplate_row(sold=2.9)])
        fake = rabbit()

        client.post("/api/sales/publish", json={"date": "2026-01-15"}, headers=api_key_headers)

        assert fake.published[0]["payload"]["data"]["sold"] == 2

    def test_tanggal_event_diformat_iso(self, client, api_key_headers, mock_service, rabbit):
        mock_service(colorplate=[colorplate_row(sale_date=date(2026, 3, 7))])
        fake = rabbit()

        client.post("/api/sales/publish", json={"date": "2026-03-07"}, headers=api_key_headers)

        assert fake.published[0]["payload"]["data"]["date"] == "2026-03-07"

    def test_date_wajib_di_body(self, client, api_key_headers, mock_service, rabbit):
        mock_service(colorplate=[])
        rabbit()

        response = client.post("/api/sales/publish", json={}, headers=api_key_headers)

        assert response.status_code == 422

    def test_rabbitmq_error_mengembalikan_500(self, client, api_key_headers, mock_service, rabbit):
        mock_service(colorplate=[colorplate_row()])
        rabbit(error=RuntimeError("broker tidak terjangkau"))

        response = client.post("/api/sales/publish", json={"date": "2026-01-15"}, headers=api_key_headers)

        assert response.status_code == 500
        assert response.json()["detail"]["message"] == "Failed to publish sales data"

    def test_service_error_mengembalikan_500(self, client, api_key_headers, mock_service, rabbit):
        mock_service(colorplate_error=RuntimeError("db mati"))
        rabbit()

        response = client.post("/api/sales/publish", json={"date": "2026-01-15"}, headers=api_key_headers)

        assert response.status_code == 500

    def test_tanpa_api_key_ditolak(self, client, mock_service, rabbit):
        mock_service(colorplate=[])
        rabbit()

        response = client.post("/api/sales/publish", json={"date": "2026-01-15"})

        assert response.status_code == 401

    def test_jwt_user_tidak_bisa_publish(self, client, make_user, token_for, mock_service, rabbit):
        mock_service(colorplate=[])
        rabbit()
        token = token_for(make_user(role="admin"))

        response = client.post("/api/sales/publish", json={"date": "2026-01-15"}, headers=bearer(token))

        assert response.status_code == 401

    def test_gagal_di_tengah_tidak_mengulang_dari_awal(self, client, api_key_headers, mock_service, rabbit):
        """Penanda TODO 3.4: publish belum idempoten — kirim dua kali, event dobel."""
        mock_service(colorplate=[colorplate_row(product_name=n) for n in ("RED", "BLUE", "GREEN")])
        fake = rabbit()

        client.post("/api/sales/publish", json={"date": "2026-01-15"}, headers=api_key_headers)
        client.post("/api/sales/publish", json={"date": "2026-01-15"}, headers=api_key_headers)

        assert len(fake.published) == 6  # duplikat — belum ada penjagaan idempotensi

    # ------------------------------------------------------------------
    # Fase 6 — group dari tabel mapping
    # ------------------------------------------------------------------

    def test_hanya_group_aktif_yang_diminta(self, client, api_key_headers, mock_service, rabbit, make_product_group):
        make_product_group("FOOD")
        make_product_group("BEVERAGE", is_active=False)
        calls = mock_service(colorplate=[])
        rabbit()

        client.post("/api/sales/publish", json={"date": "2026-01-15"}, headers=api_key_headers)

        assert calls["get_sales_by_product_groups"][0]["product_groups"] == ["COLORPLATE", "FOOD"]

    def test_tanpa_group_aktif_tidak_mempublish_apa_pun(
        self, client, api_key_headers, mock_service, rabbit, colorplate_aktif, app_db
    ):
        """Semua group dimatikan admin = sengaja berhenti publish, bukan "publish semua"."""
        colorplate_aktif.is_active = False
        app_db.commit()
        calls = mock_service(colorplate=[colorplate_row()])
        fake = rabbit()

        response = client.post("/api/sales/publish", json={"date": "2026-01-15"}, headers=api_key_headers)

        assert response.status_code == 200
        assert response.json()["published"] == 0
        assert response.json()["message"] == "No active product groups to publish"
        assert calls["get_sales_by_product_groups"] == []
        assert fake.published == []

    def test_event_group_lain_memakai_bentuk_generik(self, client, api_key_headers, mock_service, rabbit):
        mock_service(colorplate=[colorplate_row(product_group="FOOD", product_name="NASI GORENG", sold=3)])
        fake = rabbit()

        client.post("/api/sales/publish", json={"date": "2026-01-15"}, headers=api_key_headers)
        event = fake.published[0]["payload"]

        assert event["data"] == {
            "group": "FOOD",
            "product": "NASI GORENG",
            "outlet": "OUTLET_001",
            "date": "2026-01-15",
            "sold": 3,
        }
        assert event["meta"]["source"] == "sync-sales-service"

    def test_event_colorplate_tidak_ikut_berubah_ke_bentuk_generik(self, client, api_key_headers, mock_service, rabbit):
        """Consumer lama membaca `platecolor` — field generik tidak boleh ikut menempel."""
        mock_service(colorplate=[colorplate_row()])
        fake = rabbit()

        client.post("/api/sales/publish", json={"date": "2026-01-15"}, headers=api_key_headers)

        assert set(fake.published[0]["payload"]["data"]) == {"platecolor", "outlet", "date", "sold"}

    def test_campuran_group_dipublish_semua_dengan_bentuk_masing_masing(
        self, client, api_key_headers, mock_service, rabbit
    ):
        mock_service(
            colorplate=[
                colorplate_row(product_name="RED"),
                colorplate_row(product_group="FOOD", product_name="NASI GORENG"),
            ]
        )
        fake = rabbit()

        response = client.post("/api/sales/publish", json={"date": "2026-01-15"}, headers=api_key_headers)

        assert response.json()["published"] == 2
        data = [e["payload"]["data"] for e in fake.published]
        assert data[0]["platecolor"] == "RED"
        assert data[1]["product"] == "NASI GORENG"
