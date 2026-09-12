"""Test app/dependencies/auth.py — dua jalur autentikasi yang terpisah.

- API key outlet  → hanya untuk mesin POS (`/api/sync/*`, `/api/sales/publish`)
- JWT user        → untuk endpoint yang dipakai frontend dashboard

Sengaja diuji lewat HTTP, karena yang dijamin di sini bukan cuma nilai kembalian
dependency-nya, tapi juga status code yang sampai ke klien.
"""

import pytest

from app.core import security
from tests.conftest import bearer


class TestApiKeyDependency:
    """Diuji lewat POST /api/sync/sales yang memakai require_api_key."""

    BODY = {"sales": []}

    def test_tanpa_header_menghasilkan_401(self, client):
        response = client.post("/api/sync/sales", json=self.BODY)

        assert response.status_code == 401

    def test_response_401_berbentuk_json(self, client):
        """Dulu HTTPException dari middleware jadi 500 — sekarang harus 401 rapi."""
        response = client.post("/api/sync/sales", json=self.BODY)

        assert response.headers["content-type"].startswith("application/json")
        assert "detail" in response.json()

    @pytest.mark.parametrize(
        "header",
        ["token-tanpa-skema", "Basic dXNlcjpwYXNz", "bearer huruf-kecil", "Bearer", "BearerTanpaSpasi"],
    )
    def test_skema_selain_bearer_ditolak(self, client, header):
        response = client.post("/api/sync/sales", json=self.BODY, headers={"Authorization": header})

        assert response.status_code == 401

    def test_key_tidak_terdaftar_ditolak(self, client, app_db):
        response = client.post("/api/sync/sales", json=self.BODY, headers=bearer("key-ngawur"))

        assert response.status_code == 401

    def test_key_nonaktif_ditolak(self, client, make_api_key):
        raw = make_api_key(outlet_code="OUTLET_001", is_active=False)

        response = client.post("/api/sync/sales", json=self.BODY, headers=bearer(raw))

        assert response.status_code == 401

    def test_key_aktif_diterima(self, client, make_api_key):
        raw = make_api_key(outlet_code="OUTLET_001")

        response = client.post("/api/sync/sales", json=self.BODY, headers=bearer(raw))

        assert response.status_code == 200

    def test_key_disimpan_sebagai_hash_bukan_plaintext(self, client, app_db, make_api_key):
        """Key mentah tidak boleh ada di database sama sekali."""
        from app.models.api_key import ApiKey

        raw = make_api_key(outlet_code="OUTLET_001")

        tersimpan = app_db.query(ApiKey).first()
        assert tersimpan.key_hash != raw
        assert tersimpan.key_hash == security.hash_api_key(raw)

    def test_jwt_user_tidak_bisa_dipakai_untuk_endpoint_sync(self, client, make_user, token_for):
        """Pemisahan auth: token dashboard tidak boleh membuka jalur sync."""
        token = token_for(make_user(role="admin"))

        response = client.post("/api/sync/sales", json=self.BODY, headers=bearer(token))

        assert response.status_code == 401


class TestJwtDependency:
    """Diuji lewat GET /api/sales/ yang memakai get_current_user."""

    def test_tanpa_header_menghasilkan_401(self, client):
        response = client.get("/api/sales/")

        assert response.status_code == 401

    def test_token_ngawur_ditolak(self, client):
        response = client.get("/api/sales/", headers=bearer("bukan.token.jwt"))

        assert response.status_code == 401

    def test_token_kedaluwarsa_ditolak(self, client, make_user):
        from datetime import timedelta

        user = make_user(role="admin")
        token = security.create_access_token(
            subject=user.email,
            role=user.role,
            outlet_code=None,
            expires_delta=timedelta(minutes=-1),
        )

        response = client.get("/api/sales/", headers=bearer(token))

        assert response.status_code == 401

    def test_token_bertandatangan_secret_lain_ditolak(self, client, make_user):
        import jwt

        make_user(email="admin@maharasa.id", role="admin")
        palsu = jwt.encode(
            {"sub": "admin@maharasa.id", "role": "admin", "type": "access", "exp": 9999999999},
            "secret-palsu",
            algorithm="HS256",
        )

        response = client.get("/api/sales/", headers=bearer(palsu))

        assert response.status_code == 401

    def test_refresh_token_tidak_bisa_dipakai_sebagai_access_token(self, client, make_user):
        """Refresh token berumur panjang — tidak boleh membuka endpoint data."""
        user = make_user(role="admin")
        refresh = security.create_refresh_token(subject=user.email)

        response = client.get("/api/sales/", headers=bearer(refresh))

        assert response.status_code == 401

    def test_user_yang_sudah_dihapus_ditolak(self, client, make_user, token_for, app_db):
        from app.models.user import User

        user = make_user(role="admin")
        token = token_for(user)
        app_db.query(User).delete()
        app_db.commit()

        response = client.get("/api/sales/", headers=bearer(token))

        assert response.status_code == 401

    def test_user_nonaktif_ditolak_walau_token_masih_berlaku(self, client, make_user, token_for, app_db):
        """Menonaktifkan user harus langsung berlaku, tidak menunggu token kedaluwarsa."""
        from app.models.user import User

        user = make_user(role="admin")
        token = token_for(user)
        app_db.query(User).update({User.is_active: False})
        app_db.commit()

        response = client.get("/api/sales/", headers=bearer(token))

        assert response.status_code == 401

    def test_token_valid_diterima(self, client, make_user, token_for):
        token = token_for(make_user(role="admin"))

        response = client.get("/api/sales/", headers=bearer(token))

        assert response.status_code == 200

    def test_api_key_outlet_tidak_bisa_dipakai_untuk_endpoint_dashboard(self, client, make_api_key):
        """Sisi sebaliknya dari pemisahan auth."""
        raw = make_api_key(outlet_code="OUTLET_001")

        response = client.get("/api/sales/", headers=bearer(raw))

        assert response.status_code == 401


class TestOutletScoping:
    """Item 1.5 — outlet ditentukan identitas, bukan query param."""

    @pytest.fixture()
    def seeded(self, app_db, sale_factory):
        app_db.add_all(
            [
                sale_factory(transaction_id=1, outlet_code="OUTLET_001"),
                sale_factory(transaction_id=2, outlet_code="OUTLET_001"),
                sale_factory(transaction_id=3, outlet_code="OUTLET_002"),
            ]
        )
        app_db.commit()

    def test_user_outlet_hanya_melihat_outletnya_sendiri(self, client, seeded, make_user, token_for):
        user = make_user(email="kasir@maharasa.id", role="outlet", outlet_code="OUTLET_001")

        response = client.get("/api/sales/", headers=bearer(token_for(user)))
        data = response.json()["data"]

        assert len(data) == 2
        assert {row["outlet_code"] for row in data} == {"OUTLET_001"}

    def test_user_outlet_tidak_bisa_meminta_outlet_lain(self, client, seeded, make_user, token_for):
        """Ini celah yang ditutup: dulu `?outlet=` diteruskan apa adanya."""
        user = make_user(email="kasir@maharasa.id", role="outlet", outlet_code="OUTLET_001")

        response = client.get("/api/sales/?outlet=OUTLET_002", headers=bearer(token_for(user)))

        assert response.status_code == 403

    def test_user_outlet_boleh_menyebut_outletnya_sendiri(self, client, seeded, make_user, token_for):
        user = make_user(email="kasir@maharasa.id", role="outlet", outlet_code="OUTLET_001")

        response = client.get("/api/sales/?outlet=OUTLET_001", headers=bearer(token_for(user)))

        assert response.status_code == 200

    def test_admin_melihat_semua_outlet(self, client, seeded, make_user, token_for):
        user = make_user(email="admin@maharasa.id", role="admin")

        response = client.get("/api/sales/", headers=bearer(token_for(user)))

        assert len(response.json()["data"]) == 3

    def test_admin_bisa_memfilter_outlet_tertentu(self, client, seeded, make_user, token_for):
        user = make_user(email="admin@maharasa.id", role="admin")

        response = client.get("/api/sales/?outlet=OUTLET_002", headers=bearer(token_for(user)))

        assert len(response.json()["data"]) == 1

    def test_manager_melihat_semua_outlet(self, client, seeded, make_user, token_for):
        user = make_user(email="manager@maharasa.id", role="manager")

        response = client.get("/api/sales/", headers=bearer(token_for(user)))

        assert len(response.json()["data"]) == 3

    def test_user_outlet_tanpa_outlet_code_ditolak(self, client, seeded, make_user, token_for):
        """Konfigurasi user yang tidak konsisten harus gagal tertutup, bukan terbuka."""
        user = make_user(email="kasir@maharasa.id", role="outlet", outlet_code=None)

        response = client.get("/api/sales/", headers=bearer(token_for(user)))

        assert response.status_code == 403


class TestRequireRoles:

    def test_role_yang_diizinkan_diterima(self, client, make_user, token_for):
        user = make_user(email="admin@maharasa.id", role="admin")

        response = client.get("/api/auth/me", headers=bearer(token_for(user)))

        assert response.status_code == 200

    def test_role_tidak_dikenal_ditolak_saat_akses_endpoint_admin(self, client, make_user, token_for):
        user = make_user(email="kasir@maharasa.id", role="outlet", outlet_code="OUTLET_001")

        response = client.get("/api/outlets", headers=bearer(token_for(user)))

        assert response.status_code == 403

    def test_admin_boleh_akses_endpoint_admin(self, client, make_user, token_for):
        user = make_user(email="admin@maharasa.id", role="admin")

        response = client.get("/api/outlets", headers=bearer(token_for(user)))

        assert response.status_code == 200
