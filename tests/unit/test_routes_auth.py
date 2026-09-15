"""Test app/routes/auth_routes.py — login, refresh, me, logout."""

from datetime import timedelta

import pytest

from app.core import security
from tests.conftest import bearer


class TestLogin:

    def test_kredensial_benar_mengembalikan_token(self, client, make_user):
        make_user(email="budi@maharasa.id", password="rahasia123", role="admin")

        response = client.post(
            "/api/auth/login",
            json={"email": "budi@maharasa.id", "password": "rahasia123"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["access_token"]
        assert body["refresh_token"]
        assert body["token_type"] == "bearer"

    def test_token_memuat_identitas_user(self, client, make_user):
        make_user(email="kasir@maharasa.id", password="rahasia123", role="outlet", outlet_code="OUTLET_001")

        response = client.post(
            "/api/auth/login",
            json={"email": "kasir@maharasa.id", "password": "rahasia123"},
        )
        payload = security.decode_token(response.json()["access_token"])

        assert payload["sub"] == "kasir@maharasa.id"
        assert payload["role"] == "outlet"
        assert payload["outlet_code"] == "OUTLET_001"

    def test_response_memuat_data_user(self, client, make_user):
        make_user(email="budi@maharasa.id", password="rahasia123", role="admin", full_name="Budi")

        response = client.post(
            "/api/auth/login",
            json={"email": "budi@maharasa.id", "password": "rahasia123"},
        )
        user = response.json()["user"]

        assert user["email"] == "budi@maharasa.id"
        assert user["full_name"] == "Budi"
        assert user["role"] == "admin"

    def test_password_hash_tidak_ikut_di_response(self, client, make_user):
        """Kebocoran hash mempermudah serangan offline."""
        make_user(email="budi@maharasa.id", password="rahasia123")

        response = client.post(
            "/api/auth/login",
            json={"email": "budi@maharasa.id", "password": "rahasia123"},
        )

        assert "password_hash" not in response.text
        assert "password" not in response.json()["user"]

    def test_password_salah_ditolak(self, client, make_user):
        make_user(email="budi@maharasa.id", password="rahasia123")

        response = client.post(
            "/api/auth/login",
            json={"email": "budi@maharasa.id", "password": "salah"},
        )

        assert response.status_code == 401

    def test_email_tidak_terdaftar_ditolak(self, client):
        response = client.post(
            "/api/auth/login",
            json={"email": "hantu@maharasa.id", "password": "apa saja"},
        )

        assert response.status_code == 401

    def test_pesan_error_sama_untuk_email_salah_dan_password_salah(self, client, make_user):
        """Kalau pesannya beda, penyerang bisa memetakan email mana yang terdaftar."""
        make_user(email="budi@maharasa.id", password="rahasia123")

        password_salah = client.post(
            "/api/auth/login",
            json={"email": "budi@maharasa.id", "password": "salah"},
        )
        email_salah = client.post(
            "/api/auth/login",
            json={"email": "hantu@maharasa.id", "password": "salah"},
        )

        assert password_salah.json() == email_salah.json()

    def test_user_nonaktif_tidak_bisa_login(self, client, make_user):
        make_user(email="mantan@maharasa.id", password="rahasia123", is_active=False)

        response = client.post(
            "/api/auth/login",
            json={"email": "mantan@maharasa.id", "password": "rahasia123"},
        )

        assert response.status_code == 401

    def test_email_tidak_case_sensitive(self, client, make_user):
        make_user(email="budi@maharasa.id", password="rahasia123")

        response = client.post(
            "/api/auth/login",
            json={"email": "BUDI@Maharasa.ID", "password": "rahasia123"},
        )

        assert response.status_code == 200

    @pytest.mark.parametrize("body", [{}, {"email": "budi@maharasa.id"}, {"password": "x"}])
    def test_body_tidak_lengkap_ditolak_422(self, client, body):
        response = client.post("/api/auth/login", json=body)

        assert response.status_code == 422

    def test_email_tidak_valid_ditolak_422(self, client):
        response = client.post("/api/auth/login", json={"email": "bukan-email", "password": "x"})

        assert response.status_code == 422

    def test_login_tidak_butuh_autentikasi(self, client, make_user):
        """Endpoint ini harus terbuka — kalau tidak, frontend tidak bisa login sama sekali."""
        make_user(email="budi@maharasa.id", password="rahasia123")

        response = client.post(
            "/api/auth/login",
            json={"email": "budi@maharasa.id", "password": "rahasia123"},
        )

        assert response.status_code != 401


class TestRefresh:

    def test_refresh_token_valid_menghasilkan_access_token_baru(self, client, make_user):
        user = make_user(email="budi@maharasa.id", role="admin")
        refresh = security.create_refresh_token(subject=user.email)

        response = client.post("/api/auth/refresh", json={"refresh_token": refresh})

        assert response.status_code == 200
        assert security.decode_token(response.json()["access_token"])["sub"] == "budi@maharasa.id"

    def test_access_token_baru_membawa_role_terkini(self, client, make_user, app_db):
        """Role yang berubah harus langsung tercermin saat refresh."""
        from app.models.user import User

        user = make_user(email="budi@maharasa.id", role="outlet", outlet_code="OUTLET_001")
        refresh = security.create_refresh_token(subject=user.email)
        app_db.query(User).update({User.role: "admin", User.outlet_code: None})
        app_db.commit()

        response = client.post("/api/auth/refresh", json={"refresh_token": refresh})

        assert security.decode_token(response.json()["access_token"])["role"] == "admin"

    def test_access_token_tidak_bisa_dipakai_untuk_refresh(self, client, make_user, token_for):
        user = make_user(email="budi@maharasa.id", role="admin")

        response = client.post("/api/auth/refresh", json={"refresh_token": token_for(user)})

        assert response.status_code == 401

    def test_refresh_token_kedaluwarsa_ditolak(self, client, make_user):
        user = make_user(email="budi@maharasa.id", role="admin")
        kedaluwarsa = security.create_refresh_token(subject=user.email, expires_delta=timedelta(days=-1))

        response = client.post("/api/auth/refresh", json={"refresh_token": kedaluwarsa})

        assert response.status_code == 401

    def test_refresh_token_ngawur_ditolak(self, client):
        response = client.post("/api/auth/refresh", json={"refresh_token": "ngawur"})

        assert response.status_code == 401

    def test_user_nonaktif_tidak_bisa_refresh(self, client, make_user, app_db):
        from app.models.user import User

        user = make_user(email="budi@maharasa.id", role="admin")
        refresh = security.create_refresh_token(subject=user.email)
        app_db.query(User).update({User.is_active: False})
        app_db.commit()

        response = client.post("/api/auth/refresh", json={"refresh_token": refresh})

        assert response.status_code == 401


class TestMe:

    def test_mengembalikan_user_yang_sedang_login(self, client, make_user, token_for):
        user = make_user(email="budi@maharasa.id", role="manager", full_name="Budi")

        response = client.get("/api/auth/me", headers=bearer(token_for(user)))

        assert response.status_code == 200
        assert response.json()["email"] == "budi@maharasa.id"
        assert response.json()["role"] == "manager"
        assert response.json()["full_name"] == "Budi"

    def test_tanpa_token_ditolak(self, client):
        response = client.get("/api/auth/me")

        assert response.status_code == 401

    def test_tidak_membocorkan_password_hash(self, client, make_user, token_for):
        user = make_user(email="budi@maharasa.id")

        response = client.get("/api/auth/me", headers=bearer(token_for(user)))

        # Diperiksa spesifik, bukan lewat substring "password": ada field sah
        # yang memuat kata itu (`must_change_password`), dan pencarian tumpul
        # akan menuduhnya bocor. Yang benar-benar berbahaya adalah hash-nya.
        assert "password_hash" not in response.json()
        assert user.password_hash not in response.text
        assert "$2b$" not in response.text  # awalan hash bcrypt

    def test_memuat_outlet_code_untuk_user_outlet(self, client, make_user, token_for):
        user = make_user(email="kasir@maharasa.id", role="outlet", outlet_code="OUTLET_001")

        response = client.get("/api/auth/me", headers=bearer(token_for(user)))

        assert response.json()["outlet_code"] == "OUTLET_001"


class TestLogout:

    def test_mengembalikan_200(self, client, make_user, token_for):
        user = make_user()

        response = client.post("/api/auth/logout", headers=bearer(token_for(user)))

        assert response.status_code == 200

    def test_tanpa_token_ditolak(self, client):
        response = client.post("/api/auth/logout")

        assert response.status_code == 401

    def test_menjelaskan_bahwa_token_dibuang_di_sisi_klien(self, client, make_user, token_for):
        """JWT stateless — server tidak menyimpan sesi, jadi ini sekadar penanda.

        Kalau nanti perlu pencabutan token sungguhan, butuh blacklist/denylist.
        """
        user = make_user()

        response = client.post("/api/auth/logout", headers=bearer(token_for(user)))

        assert response.json()["success"] is True
