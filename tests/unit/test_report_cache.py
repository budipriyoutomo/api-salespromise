"""Cache TTL untuk endpoint laporan dashboard (TODO 9.12).

Yang paling penting dijaga di sini bukan hemat query-nya, tapi isolasi: kunci
cache memakai outlet hasil `resolve_outlet_scope`, jadi user role outlet tidak
pernah bisa menerima data yang di-cache untuk outlet lain atau untuk "semua
outlet".
"""

import pytest
from sqlalchemy.exc import OperationalError

from app.routes import sales_routes
from app.services.sales_service import SalesService
from tests.conftest import bearer

# Endpoint → (method SalesService yang dipanggil, query string minimal).
ENDPOINT = {
    "/api/sales/summary": ("get_summary", ""),
    "/api/sales/daily": ("get_daily_sales", ""),
    "/api/sales/payments": ("get_payment_summary", ""),
    "/api/sales/by-outlet": ("get_sales_by_outlet", ""),
    "/api/sales/top-products": ("get_top_products", ""),
    "/api/sales/by-group": ("get_sales_by_product_groups", "product_group=COLORPLATE"),
    "/api/sales/product-groups": ("list_product_groups", ""),
}

# Endpoint yang ter-scope outlet (by-outlet khusus admin/manager).
ENDPOINT_BER_SCOPE = [p for p in ENDPOINT if p != "/api/sales/by-outlet"]


@pytest.fixture()
def seeded(app_db, sale_factory, item_factory):
    from datetime import date

    app_db.add_all(
        [
            sale_factory(transaction_id=1, outlet_code="OUTLET_001", sale_date=date(2026, 1, 10), receipt_pay_price=100000),
            sale_factory(transaction_id=2, outlet_code="OUTLET_002", sale_date=date(2026, 1, 15), receipt_pay_price=300000),
        ]
    )
    app_db.add_all(
        [
            item_factory(order_detail_id=1, transaction_id=1, product_id=101, product_name="RED", qty=2, product_group="COLORPLATE"),
            item_factory(
                order_detail_id=1,
                transaction_id=2,
                outlet_code="OUTLET_002",
                product_id=102,
                product_name="RAHASIA_OUTLET_002",
                qty=7,
                product_group="COLORPLATE",
            ),
        ]
    )
    app_db.commit()


@pytest.fixture()
def outlet_headers(make_user, token_for):
    return bearer(token_for(make_user(email="kasir@maharasa.id", role="outlet", outlet_code="OUTLET_001")))


@pytest.fixture()
def hitung(monkeypatch):
    """Rekam setiap panggilan method SalesService (query sungguhan tetap jalan)."""
    panggilan: dict[str, list[dict]] = {}

    def _pasang(nama):
        asli = getattr(SalesService, nama)
        panggilan[nama] = []

        def bungkus(*args, **kwargs):
            panggilan[nama].append(kwargs)
            return asli(*args, **kwargs)

        monkeypatch.setattr(SalesService, nama, staticmethod(bungkus))
        return panggilan[nama]

    return _pasang


def _url(path, qs="", extra=""):
    bagian = "&".join(x for x in (qs, extra) if x)
    return f"{path}?{bagian}" if bagian else path


class TestDipakaiUlang:

    @pytest.mark.parametrize("path", list(ENDPOINT))
    def test_request_kedua_tidak_query_ulang_dan_isinya_sama(self, client, seeded, admin_headers, hitung, path):
        nama, qs = ENDPOINT[path]
        dipanggil = hitung(nama)

        pertama = client.get(_url(path, qs), headers=admin_headers)
        kedua = client.get(_url(path, qs), headers=admin_headers)

        assert pertama.status_code == 200
        assert pertama.json() == kedua.json()
        assert len(dipanggil) == 1

    @pytest.mark.parametrize(
        "path, a, b",
        [
            ("/api/sales/summary", "start_date=2026-01-01", "start_date=2026-01-02"),
            ("/api/sales/daily", "end_date=2026-01-31", "end_date=2026-01-30"),
            ("/api/sales/payments", "brand=A", "brand=B"),
            ("/api/sales/by-outlet", "brand=A", "brand=B"),
            ("/api/sales/top-products", "limit=5", "limit=6"),
            ("/api/sales/top-products", "product_group=COLORPLATE", "product_group=MINUMAN"),
            ("/api/sales/by-group", "product_group=COLORPLATE", "product_group=MINUMAN"),
            ("/api/sales/product-groups", "start_date=2026-01-01", "start_date=2026-01-15"),
        ],
    )
    def test_filter_berbeda_tidak_berbagi_cache(self, client, seeded, admin_headers, hitung, path, a, b):
        nama, _ = ENDPOINT[path]
        dipanggil = hitung(nama)

        client.get(f"{path}?{a}", headers=admin_headers)
        client.get(f"{path}?{b}", headers=admin_headers)

        assert len(dipanggil) == 2

    def test_endpoint_berbeda_tidak_berbagi_cache(self, client, seeded, admin_headers):
        """Filter sama, endpoint beda → bentuk response beda; jangan tertukar."""
        summary = client.get("/api/sales/summary", headers=admin_headers).json()
        daily = client.get("/api/sales/daily", headers=admin_headers).json()

        assert summary != daily
        assert isinstance(daily["data"], list)


class TestIsolasiOutlet:

    @pytest.mark.parametrize("path", ENDPOINT_BER_SCOPE)
    def test_outlet_tidak_menerima_cache_semua_outlet(self, client, seeded, admin_headers, outlet_headers, hitung, path):
        """Admin memanaskan cache "semua outlet" lebih dulu; user outlet yang
        datang sesudahnya harus tetap memicu query ber-scope miliknya sendiri."""
        nama, qs = ENDPOINT[path]
        dipanggil = hitung(nama)

        client.get(_url(path, qs), headers=admin_headers)
        punya_outlet = client.get(_url(path, qs), headers=outlet_headers)

        assert punya_outlet.status_code == 200
        assert [k["outlet"] for k in dipanggil] == [None, "OUTLET_001"]
        assert "OUTLET_002" not in punya_outlet.text
        assert "RAHASIA_OUTLET_002" not in punya_outlet.text

    @pytest.mark.parametrize("path", ENDPOINT_BER_SCOPE)
    def test_outlet_tidak_menerima_cache_outlet_lain(self, client, seeded, admin_headers, outlet_headers, hitung, path):
        nama, qs = ENDPOINT[path]
        dipanggil = hitung(nama)

        client.get(_url(path, qs, "outlet=OUTLET_002"), headers=admin_headers)
        punya_outlet = client.get(_url(path, qs), headers=outlet_headers)

        assert [k["outlet"] for k in dipanggil] == ["OUTLET_002", "OUTLET_001"]
        assert "RAHASIA_OUTLET_002" not in punya_outlet.text

    @pytest.mark.parametrize("path", ENDPOINT_BER_SCOPE)
    def test_param_outlet_lain_tetap_403_walau_cachenya_hangat(self, client, seeded, admin_headers, outlet_headers, path):
        """Scope diperiksa SEBELUM cache — cache tidak boleh jadi jalan pintas."""
        _, qs = ENDPOINT[path]
        assert client.get(_url(path, qs, "outlet=OUTLET_002"), headers=admin_headers).status_code == 200

        response = client.get(_url(path, qs, "outlet=OUTLET_002"), headers=outlet_headers)

        assert response.status_code == 403

    def test_kunci_memakai_scope_hasil_resolve_bukan_param_mentah(self, client, seeded, outlet_headers, hitung):
        """Untuk user outlet, tanpa `?outlet=` dan `?outlet=OUTLET_001` adalah
        scope yang sama — satu entri cache, bukan dua."""
        dipanggil = hitung("get_summary")

        client.get("/api/sales/summary", headers=outlet_headers)
        client.get("/api/sales/summary?outlet=OUTLET_001", headers=outlet_headers)

        assert len(dipanggil) == 1

    def test_by_outlet_tetap_403_untuk_role_outlet(self, client, seeded, admin_headers, outlet_headers):
        client.get("/api/sales/by-outlet", headers=admin_headers)

        assert client.get("/api/sales/by-outlet", headers=outlet_headers).status_code == 403


class TestTidakDiCache:

    def test_error_tidak_disimpan(self, client, seeded, admin_headers, monkeypatch):
        asli = SalesService.get_summary
        percobaan = []

        def kadang_gagal(*args, **kwargs):
            percobaan.append(1)
            if len(percobaan) == 1:
                raise OperationalError("SELECT", {}, Exception("statement timeout"))
            return asli(*args, **kwargs)

        monkeypatch.setattr(SalesService, "get_summary", staticmethod(kadang_gagal))

        assert client.get("/api/sales/summary", headers=admin_headers).status_code == 503
        assert client.get("/api/sales/summary", headers=admin_headers).status_code == 200
        assert len(percobaan) == 2

    def test_ttl_nol_mematikan_cache(self, client, seeded, admin_headers, hitung, monkeypatch):
        monkeypatch.setattr(sales_routes._cache_laporan, "ttl", 0)
        dipanggil = hitung("get_summary")

        client.get("/api/sales/summary", headers=admin_headers)
        client.get("/api/sales/summary", headers=admin_headers)

        assert len(dipanggil) == 2

    def test_ttl_diambil_dari_settings(self):
        from app.config import settings

        assert sales_routes._cache_laporan.ttl == settings.REPORT_CACHE_TTL_SECONDS

    def test_colorplate_tidak_di_cache(self, client, seeded, admin_headers, hitung):
        dipanggil = hitung("get_sales_colorplate")

        client.get("/api/sales/colorplate", headers=admin_headers)
        client.get("/api/sales/colorplate", headers=admin_headers)

        assert len(dipanggil) == 2

    def test_colorplate_dan_publish_tidak_menyentuh_cache_laporan(self, client, seeded, admin_headers, api_key_headers, monkeypatch):
        disentuh = []
        asli = sales_routes._cache_laporan.get_or_set

        def rekam(key, hitung):
            disentuh.append(key)
            return asli(key, hitung)

        monkeypatch.setattr(sales_routes._cache_laporan, "get_or_set", rekam)

        class RabbitPalsu:
            def publish(self, **_):
                pass

        from app.main import app

        app.dependency_overrides[sales_routes.get_rabbitmq_client] = lambda: RabbitPalsu()

        client.get("/api/sales/colorplate", headers=admin_headers)
        response = client.post("/api/sales/publish", json={"date": "2026-01-15"}, headers=api_key_headers)

        assert response.status_code == 200
        assert disentuh == []
