"""Test /api/api-keys — pengelolaan API key outlet lewat dashboard.

Sebelumnya hanya bisa lewat CLI `manage_keys.py`, sehingga halaman admin di
frontend tidak mungkin dibuat.

Aturan yang dijaga di sini: key mentah HANYA muncul sekali, di response yang
membuatnya. Tidak pernah muncul lagi di endpoint mana pun.
"""

import pytest

from app.core import security
from app.models.api_key import ApiKey
from tests.conftest import bearer


@pytest.fixture()
def manager_headers(make_user, token_for):
    return bearer(token_for(make_user(email="manager@maharasa.id", role="manager")))


@pytest.fixture()
def outlet_headers(make_user, token_for):
    user = make_user(email="kasir@maharasa.id", role="outlet", outlet_code="OUTLET_001")
    return bearer(token_for(user))


class TestListApiKeys:

    def test_admin_melihat_daftar_key(self, client, admin_headers, make_api_key):
        make_api_key(outlet_code="OUTLET_001")
        make_api_key(outlet_code="OUTLET_002")

        response = client.get("/api/api-keys", headers=admin_headers)

        assert response.status_code == 200
        assert {row["outlet_code"] for row in response.json()["data"]} == {"OUTLET_001", "OUTLET_002"}

    def test_key_mentah_tidak_pernah_ikut(self, client, admin_headers, make_api_key):
        raw = make_api_key(outlet_code="OUTLET_001")

        response = client.get("/api/api-keys", headers=admin_headers)

        assert raw not in response.text

    def test_hash_juga_tidak_ikut(self, client, admin_headers, make_api_key):
        raw = make_api_key(outlet_code="OUTLET_001")

        response = client.get("/api/api-keys", headers=admin_headers)

        assert security.hash_api_key(raw) not in response.text

    def test_membawa_prefix_untuk_identifikasi(self, client, admin_headers, make_api_key):
        raw = make_api_key(outlet_code="OUTLET_001")

        data = client.get("/api/api-keys", headers=admin_headers).json()["data"]

        assert data[0]["key_prefix"] == raw[:8]

    def test_membawa_status_aktif(self, client, admin_headers, make_api_key):
        make_api_key(outlet_code="OUTLET_001", is_active=False)

        data = client.get("/api/api-keys", headers=admin_headers).json()["data"]

        assert data[0]["is_active"] is False

    def test_terurut_berdasarkan_outlet(self, client, admin_headers, make_api_key):
        make_api_key(outlet_code="OUTLET_003")
        make_api_key(outlet_code="OUTLET_001")
        make_api_key(outlet_code="OUTLET_002")

        data = client.get("/api/api-keys", headers=admin_headers).json()["data"]

        assert [r["outlet_code"] for r in data] == ["OUTLET_001", "OUTLET_002", "OUTLET_003"]

    def test_manager_ditolak(self, client, manager_headers, make_api_key):
        """Kredensial mesin POS hanya urusan admin."""
        assert client.get("/api/api-keys", headers=manager_headers).status_code == 403

    def test_role_outlet_ditolak(self, client, outlet_headers):
        assert client.get("/api/api-keys", headers=outlet_headers).status_code == 403

    def test_butuh_autentikasi(self, client):
        assert client.get("/api/api-keys").status_code == 401


class TestCreateApiKey:

    def test_membuat_key_baru(self, client, admin_headers, app_db):
        response = client.post("/api/api-keys", json={"outlet_code": "OUTLET_009"}, headers=admin_headers)

        assert response.status_code == 201
        assert app_db.query(ApiKey).filter(ApiKey.outlet_code == "OUTLET_009").first() is not None

    def test_mengembalikan_key_mentah_sekali(self, client, admin_headers):
        response = client.post("/api/api-keys", json={"outlet_code": "OUTLET_009"}, headers=admin_headers)

        assert len(response.json()["api_key"]) >= 32

    def test_database_hanya_menyimpan_hash(self, client, admin_headers, app_db):
        raw = client.post(
            "/api/api-keys", json={"outlet_code": "OUTLET_009"}, headers=admin_headers
        ).json()["api_key"]

        tersimpan = app_db.query(ApiKey).filter(ApiKey.outlet_code == "OUTLET_009").first()
        assert tersimpan.key_hash == security.hash_api_key(raw)
        assert tersimpan.key_hash != raw

    def test_key_baru_langsung_bisa_dipakai_sync(self, client, admin_headers, monkeypatch):
        """Bukti end-to-end bahwa key yang dikembalikan benar-benar berlaku."""
        monkeypatch.setattr(
            "app.routes.sync_routes.SalesService.sync_sales",
            staticmethod(lambda db, outlet, sales_list: {"sales": 0, "items": 0}),
        )
        raw = client.post(
            "/api/api-keys", json={"outlet_code": "OUTLET_009"}, headers=admin_headers
        ).json()["api_key"]

        response = client.post("/api/sync/sales", json={"sales": []}, headers=bearer(raw))

        assert response.status_code == 200

    def test_peringatan_bahwa_key_tidak_bisa_dilihat_lagi(self, client, admin_headers):
        response = client.post("/api/api-keys", json={"outlet_code": "OUTLET_009"}, headers=admin_headers)

        assert "message" in response.json()

    def test_outlet_yang_sudah_punya_key_ditolak_409(self, client, admin_headers, make_api_key):
        """Menimpa key berarti mesin POS di lapangan langsung kehilangan akses."""
        make_api_key(outlet_code="OUTLET_001")

        response = client.post("/api/api-keys", json={"outlet_code": "OUTLET_001"}, headers=admin_headers)

        assert response.status_code == 409

    def test_key_lama_tetap_berlaku_setelah_penolakan(self, client, admin_headers, make_api_key, app_db):
        raw = make_api_key(outlet_code="OUTLET_001")

        client.post("/api/api-keys", json={"outlet_code": "OUTLET_001"}, headers=admin_headers)

        tersimpan = app_db.query(ApiKey).filter(ApiKey.outlet_code == "OUTLET_001").first()
        assert tersimpan.key_hash == security.hash_api_key(raw)

    def test_outlet_code_kosong_ditolak_422(self, client, admin_headers):
        assert client.post("/api/api-keys", json={"outlet_code": ""}, headers=admin_headers).status_code == 422

    def test_outlet_code_terlalu_panjang_ditolak_422(self, client, admin_headers):
        """Kolom DB hanya menampung 20 karakter."""
        response = client.post("/api/api-keys", json={"outlet_code": "X" * 30}, headers=admin_headers)

        assert response.status_code == 422

    def test_manager_ditolak(self, client, manager_headers):
        response = client.post("/api/api-keys", json={"outlet_code": "OUTLET_009"}, headers=manager_headers)

        assert response.status_code == 403

    def test_butuh_autentikasi(self, client):
        assert client.post("/api/api-keys", json={"outlet_code": "OUTLET_009"}).status_code == 401


class TestRotateApiKey:

    def test_menghasilkan_key_baru(self, client, admin_headers, make_api_key, app_db):
        lama = make_api_key(outlet_code="OUTLET_001")

        response = client.post("/api/api-keys/OUTLET_001/rotate", headers=admin_headers)

        assert response.status_code == 200
        baru = response.json()["api_key"]
        assert baru != lama

    def test_key_lama_langsung_tidak_berlaku(self, client, admin_headers, make_api_key, monkeypatch):
        """Inilah gunanya rotate — mencabut key yang bocor."""
        monkeypatch.setattr(
            "app.routes.sync_routes.SalesService.sync_sales",
            staticmethod(lambda db, outlet, sales_list: {"sales": 0, "items": 0}),
        )
        lama = make_api_key(outlet_code="OUTLET_001")

        client.post("/api/api-keys/OUTLET_001/rotate", headers=admin_headers)

        assert client.post("/api/sync/sales", json={"sales": []}, headers=bearer(lama)).status_code == 401

    def test_key_baru_berlaku(self, client, admin_headers, make_api_key, monkeypatch):
        monkeypatch.setattr(
            "app.routes.sync_routes.SalesService.sync_sales",
            staticmethod(lambda db, outlet, sales_list: {"sales": 0, "items": 0}),
        )
        make_api_key(outlet_code="OUTLET_001")

        baru = client.post("/api/api-keys/OUTLET_001/rotate", headers=admin_headers).json()["api_key"]

        assert client.post("/api/sync/sales", json={"sales": []}, headers=bearer(baru)).status_code == 200

    def test_mengaktifkan_kembali_key_yang_sudah_direvoke(self, client, admin_headers, make_api_key, app_db):
        """Cara yang benar untuk memulihkan outlet: rotate, bukan activate —
        key lama sudah tidak diketahui siapa pun."""
        make_api_key(outlet_code="OUTLET_001", is_active=False)

        client.post("/api/api-keys/OUTLET_001/rotate", headers=admin_headers)

        app_db.expire_all()
        assert app_db.query(ApiKey).filter(ApiKey.outlet_code == "OUTLET_001").first().is_active is True

    def test_prefix_ikut_diperbarui(self, client, admin_headers, make_api_key, app_db):
        make_api_key(outlet_code="OUTLET_001")

        baru = client.post("/api/api-keys/OUTLET_001/rotate", headers=admin_headers).json()["api_key"]

        app_db.expire_all()
        assert app_db.query(ApiKey).filter(ApiKey.outlet_code == "OUTLET_001").first().key_prefix == baru[:8]

    def test_outlet_tidak_dikenal_menghasilkan_404(self, client, admin_headers):
        assert client.post("/api/api-keys/TIDAK_ADA/rotate", headers=admin_headers).status_code == 404

    def test_manager_ditolak(self, client, manager_headers, make_api_key):
        make_api_key(outlet_code="OUTLET_001")

        assert client.post("/api/api-keys/OUTLET_001/rotate", headers=manager_headers).status_code == 403


class TestRevokeApiKey:

    def test_menonaktifkan_key(self, client, admin_headers, make_api_key, app_db):
        make_api_key(outlet_code="OUTLET_001")

        response = client.post("/api/api-keys/OUTLET_001/revoke", headers=admin_headers)

        assert response.status_code == 200
        app_db.expire_all()
        assert app_db.query(ApiKey).filter(ApiKey.outlet_code == "OUTLET_001").first().is_active is False

    def test_key_langsung_ditolak_setelah_revoke(self, client, admin_headers, make_api_key):
        raw = make_api_key(outlet_code="OUTLET_001")

        client.post("/api/api-keys/OUTLET_001/revoke", headers=admin_headers)

        assert client.post("/api/sync/sales", json={"sales": []}, headers=bearer(raw)).status_code == 401

    def test_baris_tidak_dihapus_demi_jejak_audit(self, client, admin_headers, make_api_key, app_db):
        make_api_key(outlet_code="OUTLET_001")

        client.post("/api/api-keys/OUTLET_001/revoke", headers=admin_headers)

        assert app_db.query(ApiKey).filter(ApiKey.outlet_code == "OUTLET_001").first() is not None

    def test_revoke_dua_kali_aman(self, client, admin_headers, make_api_key):
        make_api_key(outlet_code="OUTLET_001")

        client.post("/api/api-keys/OUTLET_001/revoke", headers=admin_headers)
        response = client.post("/api/api-keys/OUTLET_001/revoke", headers=admin_headers)

        assert response.status_code == 200

    def test_outlet_tidak_dikenal_menghasilkan_404(self, client, admin_headers):
        assert client.post("/api/api-keys/TIDAK_ADA/revoke", headers=admin_headers).status_code == 404

    def test_tidak_mempengaruhi_outlet_lain(self, client, admin_headers, make_api_key, app_db):
        make_api_key(outlet_code="OUTLET_001")
        make_api_key(outlet_code="OUTLET_002")

        client.post("/api/api-keys/OUTLET_001/revoke", headers=admin_headers)

        app_db.expire_all()
        lain = app_db.query(ApiKey).filter(ApiKey.outlet_code == "OUTLET_002").first()
        assert lain.is_active is True

    def test_manager_ditolak(self, client, manager_headers, make_api_key):
        make_api_key(outlet_code="OUTLET_001")

        assert client.post("/api/api-keys/OUTLET_001/revoke", headers=manager_headers).status_code == 403
