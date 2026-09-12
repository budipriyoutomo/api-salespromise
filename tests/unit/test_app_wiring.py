"""Test perakitan aplikasi — CORS, endpoint publik, dan penjagaan auth.

Test di file ini yang menangkap kalau ada endpoint baru ditambahkan tanpa
autentikasi. Lebih murah daripada menemukannya lewat insiden.
"""

import pytest

from app.config import settings
from app.main import app

PUBLIC_PATHS = {
    "/",
    "/health",
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
    "/api/auth/login",
    "/api/auth/refresh",
}


def _auth_dependency_names(route):
    """Nama semua dependency sebuah route, ditelusuri sampai level terdalam.

    Dependency bisa terpasang di route, di router, atau jadi turunan dependency
    lain (`require_roles` memanggil `get_current_user`) — semuanya harus terbaca.
    """
    names = set()

    def walk(dependant):
        for sub in dependant.dependencies:
            call = sub.call
            if call is not None:
                names.add(getattr(call, "__name__", type(call).__name__))
            walk(sub)

    dependant = getattr(route, "dependant", None)
    if dependant is not None:
        walk(dependant)

    return names


class TestPenjagaAuth:

    def test_semua_endpoint_api_punya_autentikasi(self):
        """Endpoint di bawah /api wajib memakai require_api_key atau get_current_user."""
        tanpa_auth = []

        for route in app.routes:
            path = getattr(route, "path", "")
            if not path.startswith("/api") or path in PUBLIC_PATHS:
                continue

            names = _auth_dependency_names(route)
            if not ({"require_api_key", "get_current_user", "_checker"} & names):
                tanpa_auth.append(path)

        assert tanpa_auth == [], f"Endpoint tanpa autentikasi: {tanpa_auth}"

    def test_endpoint_sync_memakai_api_key_bukan_jwt(self):
        for route in app.routes:
            if getattr(route, "path", "").startswith("/api/sync"):
                assert "require_api_key" in _auth_dependency_names(route)

    def test_endpoint_baca_sales_memakai_jwt_bukan_api_key(self):
        for route in app.routes:
            path = getattr(route, "path", "")
            if path in ("/api/sales/", "/api/sales/colorplate"):
                names = _auth_dependency_names(route)
                assert "get_current_user" in names
                assert "require_api_key" not in names


class TestEndpointPublik:

    @pytest.mark.parametrize("path", ["/", "/health"])
    def test_health_terbuka(self, client, path):
        response = client.get(path)

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_openapi_terbuka(self, client):
        """Frontend men-generate tipe dari sini — tidak boleh terkunci."""
        response = client.get("/openapi.json")

        assert response.status_code == 200

    def test_docs_terbuka(self, client):
        response = client.get("/docs")

        assert response.status_code == 200


class TestCors:

    ORIGIN = "http://localhost:3000"

    def test_origin_terdaftar_diizinkan(self, client):
        response = client.get("/", headers={"Origin": self.ORIGIN})

        assert response.headers.get("access-control-allow-origin") == self.ORIGIN

    def test_preflight_dijawab(self, client):
        """Tanpa ini, request dengan header Authorization diblokir browser."""
        response = client.options(
            "/api/sales/",
            headers={
                "Origin": self.ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )

        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == self.ORIGIN

    def test_header_authorization_diizinkan(self, client):
        response = client.options(
            "/api/sales/",
            headers={
                "Origin": self.ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )

        allowed = response.headers.get("access-control-allow-headers", "").lower()
        assert "authorization" in allowed

    def test_origin_tidak_terdaftar_tidak_diizinkan(self, client):
        response = client.get("/", headers={"Origin": "https://situs-asing.example"})

        assert response.headers.get("access-control-allow-origin") is None

    def test_bukan_wildcard(self):
        """`*` akan mengizinkan situs mana pun memanggil API atas nama user."""
        assert "*" not in settings.CORS_ORIGINS

    def test_allow_credentials_dimatikan(self):
        """Token dikirim lewat header Authorization, bukan cookie — jadi tidak perlu."""
        cors = [m for m in app.user_middleware if "CORS" in m.cls.__name__]

        assert cors, "CORSMiddleware tidak terpasang"
        assert cors[0].kwargs["allow_credentials"] is False

    def test_origin_dibaca_dari_env(self):
        assert settings.CORS_ORIGINS == ["http://localhost:3000", "https://dashboard.maharasa.id"]


class TestOpenApi:
    """Item 1.8 — frontend men-generate client dari skema ini."""

    def test_endpoint_utama_terdokumentasi(self, client):
        paths = client.get("/openapi.json").json()["paths"]

        for path in ["/api/auth/login", "/api/auth/me", "/api/sales/", "/api/sync/sales", "/api/outlets"]:
            assert path in paths, f"{path} tidak ada di OpenAPI"

    def test_response_schema_terdefinisi_bukan_objek_bebas(self, client):
        spec = client.get("/openapi.json").json()
        response_200 = spec["paths"]["/api/sales/"]["get"]["responses"]["200"]

        schema = response_200["content"]["application/json"]["schema"]
        assert "$ref" in schema or schema.get("type") == "object"

    def test_schema_sales_list_terdaftar(self, client):
        schemas = client.get("/openapi.json").json()["components"]["schemas"]

        assert "SalesListResponse" in schemas
        assert "SaleResponse" in schemas
        assert "TokenResponse" in schemas

    def test_password_hash_tidak_muncul_di_schema_user(self, client):
        schemas = client.get("/openapi.json").json()["components"]["schemas"]

        assert "password_hash" not in schemas["UserResponse"]["properties"]
