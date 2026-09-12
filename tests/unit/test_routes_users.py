"""Test /api/users — pengelolaan user dashboard lewat frontend.

Selain CRUD biasa, di sini dijaga beberapa pagar yang mencegah admin mengunci
dirinya sendiri keluar dari sistem.
"""

import pytest

from app.core import security
from app.models.user import User
from tests.conftest import bearer


@pytest.fixture()
def manager_headers(make_user, token_for):
    return bearer(token_for(make_user(email="manager@maharasa.id", role="manager")))


@pytest.fixture()
def outlet_headers(make_user, token_for):
    user = make_user(email="kasir@maharasa.id", role="outlet", outlet_code="OUTLET_001")
    return bearer(token_for(user))


def id_dari(app_db, email):
    return app_db.query(User).filter(User.email == email).first().id


class TestListUsers:

    def test_admin_melihat_semua_user(self, client, admin_headers, make_user):
        make_user(email="kasir@maharasa.id", role="outlet", outlet_code="OUTLET_001")

        response = client.get("/api/users", headers=admin_headers)

        assert response.status_code == 200
        assert {u["email"] for u in response.json()["data"]} == {"admin@maharasa.id", "kasir@maharasa.id"}

    def test_password_hash_tidak_ikut(self, client, admin_headers):
        response = client.get("/api/users", headers=admin_headers)

        assert "password" not in response.text.lower()

    def test_terurut_berdasarkan_email(self, client, admin_headers, make_user):
        make_user(email="zulkifli@maharasa.id", role="manager")
        make_user(email="budi@maharasa.id", role="manager")

        data = client.get("/api/users", headers=admin_headers).json()["data"]

        assert [u["email"] for u in data] == sorted(u["email"] for u in data)

    def test_manager_ditolak(self, client, manager_headers):
        assert client.get("/api/users", headers=manager_headers).status_code == 403

    def test_role_outlet_ditolak(self, client, outlet_headers):
        assert client.get("/api/users", headers=outlet_headers).status_code == 403

    def test_butuh_autentikasi(self, client):
        assert client.get("/api/users").status_code == 401


class TestCreateUser:

    BARU = {"email": "baru@maharasa.id", "password": "rahasia123", "role": "manager", "full_name": "Baru"}

    def test_membuat_user(self, client, admin_headers, app_db):
        response = client.post("/api/users", json=self.BARU, headers=admin_headers)

        assert response.status_code == 201
        assert app_db.query(User).filter(User.email == "baru@maharasa.id").first() is not None

    def test_password_disimpan_sebagai_hash(self, client, admin_headers, app_db):
        client.post("/api/users", json=self.BARU, headers=admin_headers)

        user = app_db.query(User).filter(User.email == "baru@maharasa.id").first()
        assert security.verify_password("rahasia123", user.password_hash) is True

    def test_password_tidak_ikut_di_response(self, client, admin_headers):
        response = client.post("/api/users", json=self.BARU, headers=admin_headers)

        assert "rahasia123" not in response.text
        assert "password" not in response.json()["data"]

    def test_user_baru_langsung_bisa_login(self, client, admin_headers):
        client.post("/api/users", json=self.BARU, headers=admin_headers)

        response = client.post(
            "/api/auth/login",
            json={"email": "baru@maharasa.id", "password": "rahasia123"},
        )

        assert response.status_code == 200

    def test_email_disimpan_lowercase(self, client, admin_headers, app_db):
        client.post("/api/users", json=dict(self.BARU, email="  Baru@Maharasa.ID  "), headers=admin_headers)

        assert app_db.query(User).filter(User.email == "baru@maharasa.id").first() is not None

    def test_email_duplikat_ditolak_409(self, client, admin_headers, make_user):
        make_user(email="sudahada@maharasa.id", role="manager")

        response = client.post(
            "/api/users", json=dict(self.BARU, email="sudahada@maharasa.id"), headers=admin_headers
        )

        assert response.status_code == 409

    def test_role_outlet_wajib_punya_outlet_code(self, client, admin_headers):
        """User 'outlet' tanpa outlet akan selalu kena 403 — cegah sejak pembuatan."""
        response = client.post(
            "/api/users", json=dict(self.BARU, role="outlet", outlet_code=None), headers=admin_headers
        )

        assert response.status_code == 422

    def test_role_outlet_dengan_outlet_code_diterima(self, client, admin_headers, app_db):
        response = client.post(
            "/api/users",
            json=dict(self.BARU, role="outlet", outlet_code="OUTLET_001"),
            headers=admin_headers,
        )

        assert response.status_code == 201
        assert app_db.query(User).filter(User.email == "baru@maharasa.id").first().outlet_code == "OUTLET_001"

    def test_outlet_code_diabaikan_untuk_role_admin(self, client, admin_headers, app_db):
        client.post(
            "/api/users", json=dict(self.BARU, role="admin", outlet_code="OUTLET_001"), headers=admin_headers
        )

        assert app_db.query(User).filter(User.email == "baru@maharasa.id").first().outlet_code is None

    def test_role_tidak_dikenal_ditolak_422(self, client, admin_headers):
        response = client.post("/api/users", json=dict(self.BARU, role="superuser"), headers=admin_headers)

        assert response.status_code == 422

    def test_password_terlalu_pendek_ditolak_422(self, client, admin_headers):
        response = client.post("/api/users", json=dict(self.BARU, password="pendek"), headers=admin_headers)

        assert response.status_code == 422

    def test_email_tidak_valid_ditolak_422(self, client, admin_headers):
        response = client.post("/api/users", json=dict(self.BARU, email="bukan-email"), headers=admin_headers)

        assert response.status_code == 422

    def test_manager_ditolak(self, client, manager_headers):
        assert client.post("/api/users", json=self.BARU, headers=manager_headers).status_code == 403


class TestUpdateUser:

    def test_mengubah_nama(self, client, admin_headers, make_user, app_db):
        make_user(email="budi@maharasa.id", role="manager")
        uid = id_dari(app_db, "budi@maharasa.id")

        response = client.patch(f"/api/users/{uid}", json={"full_name": "Budi Baru"}, headers=admin_headers)

        assert response.status_code == 200
        assert response.json()["data"]["full_name"] == "Budi Baru"

    def test_mengubah_role(self, client, admin_headers, make_user, app_db):
        make_user(email="budi@maharasa.id", role="manager")
        uid = id_dari(app_db, "budi@maharasa.id")

        client.patch(f"/api/users/{uid}", json={"role": "admin"}, headers=admin_headers)

        app_db.expire_all()
        assert app_db.query(User).get(uid).role == "admin"

    def test_menurunkan_ke_role_outlet_wajib_sertakan_outlet_code(self, client, admin_headers, make_user, app_db):
        make_user(email="budi@maharasa.id", role="manager")
        uid = id_dari(app_db, "budi@maharasa.id")

        response = client.patch(f"/api/users/{uid}", json={"role": "outlet"}, headers=admin_headers)

        assert response.status_code == 422

    def test_menonaktifkan_user(self, client, admin_headers, make_user, app_db):
        make_user(email="budi@maharasa.id", role="manager")
        uid = id_dari(app_db, "budi@maharasa.id")

        client.patch(f"/api/users/{uid}", json={"is_active": False}, headers=admin_headers)

        app_db.expire_all()
        assert app_db.query(User).get(uid).is_active is False

    def test_user_nonaktif_langsung_tidak_bisa_akses(self, client, admin_headers, make_user, token_for, app_db):
        budi = make_user(email="budi@maharasa.id", role="manager")
        token = token_for(budi)
        uid = id_dari(app_db, "budi@maharasa.id")

        client.patch(f"/api/users/{uid}", json={"is_active": False}, headers=admin_headers)

        assert client.get("/api/sales/", headers=bearer(token)).status_code == 401

    def test_admin_tidak_bisa_menonaktifkan_dirinya_sendiri(self, client, admin_headers, app_db):
        """Pagar anti-terkunci: kalau ini lolos, admin bisa mengeluarkan dirinya sendiri."""
        uid = id_dari(app_db, "admin@maharasa.id")

        response = client.patch(f"/api/users/{uid}", json={"is_active": False}, headers=admin_headers)

        assert response.status_code == 400

    def test_admin_tidak_bisa_menurunkan_role_dirinya_sendiri(self, client, admin_headers, app_db):
        uid = id_dari(app_db, "admin@maharasa.id")

        response = client.patch(
            f"/api/users/{uid}", json={"role": "outlet", "outlet_code": "OUTLET_001"}, headers=admin_headers
        )

        assert response.status_code == 400

    def test_admin_terakhir_tidak_bisa_diturunkan(self, client, admin_headers, make_user, app_db, token_for):
        """Sistem harus selalu punya minimal satu admin aktif."""
        lain = make_user(email="admin2@maharasa.id", role="admin")
        uid_lain = lain.id

        # admin kedua menurunkan admin pertama → boleh, karena masih ada dia
        uid_pertama = id_dari(app_db, "admin@maharasa.id")
        r1 = client.patch(
            f"/api/users/{uid_pertama}", json={"role": "manager"}, headers=bearer(token_for(lain))
        )
        assert r1.status_code == 200

        # sekarang admin2 satu-satunya; dia tidak boleh menurunkan admin manapun
        app_db.expire_all()
        r2 = client.patch(f"/api/users/{uid_lain}", json={"role": "manager"}, headers=bearer(token_for(lain)))
        assert r2.status_code == 400

    def test_email_tidak_bisa_diubah(self, client, admin_headers, make_user, app_db):
        """Email adalah subject token — mengubahnya membuat token berjalan jadi yatim."""
        make_user(email="budi@maharasa.id", role="manager")
        uid = id_dari(app_db, "budi@maharasa.id")

        client.patch(f"/api/users/{uid}", json={"email": "lain@maharasa.id"}, headers=admin_headers)

        app_db.expire_all()
        assert app_db.query(User).get(uid).email == "budi@maharasa.id"

    def test_user_tidak_ada_menghasilkan_404(self, client, admin_headers):
        assert client.patch("/api/users/99999", json={"full_name": "X"}, headers=admin_headers).status_code == 404

    def test_manager_ditolak(self, client, manager_headers, make_user, app_db):
        make_user(email="budi@maharasa.id", role="manager")
        uid = id_dari(app_db, "budi@maharasa.id")

        assert client.patch(f"/api/users/{uid}", json={"full_name": "X"}, headers=manager_headers).status_code == 403


class TestResetPassword:

    def test_admin_mengatur_ulang_password_user_lain(self, client, admin_headers, make_user, app_db):
        make_user(email="budi@maharasa.id", password="lamalama123", role="manager")
        uid = id_dari(app_db, "budi@maharasa.id")

        response = client.post(
            f"/api/users/{uid}/password", json={"password": "barubaru123"}, headers=admin_headers
        )

        assert response.status_code == 200
        assert client.post(
            "/api/auth/login", json={"email": "budi@maharasa.id", "password": "barubaru123"}
        ).status_code == 200

    def test_password_lama_tidak_berlaku_lagi(self, client, admin_headers, make_user, app_db):
        make_user(email="budi@maharasa.id", password="lamalama123", role="manager")
        uid = id_dari(app_db, "budi@maharasa.id")

        client.post(f"/api/users/{uid}/password", json={"password": "barubaru123"}, headers=admin_headers)

        assert client.post(
            "/api/auth/login", json={"email": "budi@maharasa.id", "password": "lamalama123"}
        ).status_code == 401

    def test_password_terlalu_pendek_ditolak_422(self, client, admin_headers, make_user, app_db):
        make_user(email="budi@maharasa.id", role="manager")
        uid = id_dari(app_db, "budi@maharasa.id")

        response = client.post(f"/api/users/{uid}/password", json={"password": "pendek"}, headers=admin_headers)

        assert response.status_code == 422

    def test_manager_ditolak(self, client, manager_headers, make_user, app_db):
        make_user(email="budi@maharasa.id", role="manager")
        uid = id_dari(app_db, "budi@maharasa.id")

        response = client.post(f"/api/users/{uid}/password", json={"password": "barubaru123"}, headers=manager_headers)

        assert response.status_code == 403


class TestChangeOwnPassword:
    """Ganti password sendiri — tersedia untuk semua role, bukan cuma admin."""

    def test_mengganti_password_sendiri(self, client, make_user, token_for):
        user = make_user(email="kasir@maharasa.id", password="lamalama123", role="outlet", outlet_code="OUTLET_001")

        response = client.post(
            "/api/auth/change-password",
            json={"current_password": "lamalama123", "new_password": "barubaru123"},
            headers=bearer(token_for(user)),
        )

        assert response.status_code == 200
        assert client.post(
            "/api/auth/login", json={"email": "kasir@maharasa.id", "password": "barubaru123"}
        ).status_code == 200

    def test_password_lama_salah_ditolak(self, client, make_user, token_for):
        """Tanpa ini, token yang dicuri bisa dipakai mengunci pemilik akun."""
        user = make_user(email="kasir@maharasa.id", password="lamalama123", role="outlet", outlet_code="OUTLET_001")

        response = client.post(
            "/api/auth/change-password",
            json={"current_password": "salah", "new_password": "barubaru123"},
            headers=bearer(token_for(user)),
        )

        assert response.status_code == 401

    def test_password_tidak_berubah_saat_ditolak(self, client, make_user, token_for):
        user = make_user(email="kasir@maharasa.id", password="lamalama123", role="outlet", outlet_code="OUTLET_001")

        client.post(
            "/api/auth/change-password",
            json={"current_password": "salah", "new_password": "barubaru123"},
            headers=bearer(token_for(user)),
        )

        assert client.post(
            "/api/auth/login", json={"email": "kasir@maharasa.id", "password": "lamalama123"}
        ).status_code == 200

    def test_password_baru_terlalu_pendek_ditolak_422(self, client, make_user, token_for):
        user = make_user(email="kasir@maharasa.id", password="lamalama123", role="outlet", outlet_code="OUTLET_001")

        response = client.post(
            "/api/auth/change-password",
            json={"current_password": "lamalama123", "new_password": "pendek"},
            headers=bearer(token_for(user)),
        )

        assert response.status_code == 422

    def test_butuh_autentikasi(self, client):
        response = client.post(
            "/api/auth/change-password",
            json={"current_password": "a", "new_password": "barubaru123"},
        )

        assert response.status_code == 401
