"""Test pembatasan percobaan login (item 3.8).

`/api/auth/login` adalah satu-satunya endpoint publik yang menerima kredensial.
Tanpa pembatasan, password bisa ditebak terus-menerus tanpa hambatan.
"""

import pytest
from freezegun import freeze_time

from app.config import settings
from app.core.rate_limit import RateLimiter


class TestRateLimiter:

    def test_mengizinkan_di_bawah_batas(self):
        limiter = RateLimiter(max_attempts=3, window_seconds=60)

        assert limiter.allow("a") is True
        assert limiter.allow("a") is True
        assert limiter.allow("a") is True

    def test_menolak_setelah_melewati_batas(self):
        limiter = RateLimiter(max_attempts=3, window_seconds=60)
        for _ in range(3):
            limiter.allow("a")

        assert limiter.allow("a") is False

    def test_kunci_berbeda_dihitung_terpisah(self):
        """Satu IP yang diblokir tidak boleh ikut memblokir IP lain."""
        limiter = RateLimiter(max_attempts=2, window_seconds=60)
        limiter.allow("a")
        limiter.allow("a")

        assert limiter.allow("a") is False
        assert limiter.allow("b") is True

    def test_jatah_pulih_setelah_window_lewat(self):
        limiter = RateLimiter(max_attempts=2, window_seconds=60)

        with freeze_time("2026-01-01 08:00:00"):
            limiter.allow("a")
            limiter.allow("a")
            assert limiter.allow("a") is False

        with freeze_time("2026-01-01 08:01:01"):
            assert limiter.allow("a") is True

    def test_window_bergeser_bukan_reset_blok(self):
        """Sliding window: percobaan lama luruh satu per satu, bukan sekaligus."""
        limiter = RateLimiter(max_attempts=2, window_seconds=60)

        with freeze_time("2026-01-01 08:00:00"):
            limiter.allow("a")
        with freeze_time("2026-01-01 08:00:40"):
            limiter.allow("a")
            assert limiter.allow("a") is False
        with freeze_time("2026-01-01 08:01:01"):
            # percobaan pertama sudah lewat 60 detik, yang kedua belum
            assert limiter.allow("a") is True
            assert limiter.allow("a") is False

    def test_reset_mengosongkan_catatan(self):
        limiter = RateLimiter(max_attempts=1, window_seconds=60)
        limiter.allow("a")
        assert limiter.allow("a") is False

        limiter.reset("a")

        assert limiter.allow("a") is True

    def test_batas_nol_mematikan_pembatasan(self):
        """Supaya bisa dinonaktifkan lewat env tanpa mengubah kode."""
        limiter = RateLimiter(max_attempts=0, window_seconds=60)

        for _ in range(100):
            assert limiter.allow("a") is True

    def test_catatan_kunci_lama_dibersihkan(self):
        """Kalau tidak, dict-nya tumbuh terus selama proses hidup."""
        limiter = RateLimiter(max_attempts=2, window_seconds=60)

        with freeze_time("2026-01-01 08:00:00"):
            limiter.allow("a")
        with freeze_time("2026-01-01 09:00:00"):
            limiter.allow("b")

        assert "a" not in limiter._hits


class TestLoginRateLimit:

    KREDENSIAL_SALAH = {"email": "admin@maharasa.id", "password": "salah"}

    @pytest.fixture(autouse=True)
    def bersihkan(self):
        from app.routes import auth_routes

        auth_routes.login_limiter.clear()
        yield
        auth_routes.login_limiter.clear()

    def test_percobaan_berlebihan_ditolak_429(self, client, make_user):
        make_user(email="admin@maharasa.id", password="rahasia123")

        for _ in range(settings.LOGIN_MAX_ATTEMPTS):
            client.post("/api/auth/login", json=self.KREDENSIAL_SALAH)

        response = client.post("/api/auth/login", json=self.KREDENSIAL_SALAH)

        assert response.status_code == 429

    def test_password_benar_pun_ditolak_saat_terblokir(self, client, make_user):
        """Blokir berlaku per pemanggil, bukan per hasil percobaan."""
        make_user(email="admin@maharasa.id", password="rahasia123")

        for _ in range(settings.LOGIN_MAX_ATTEMPTS):
            client.post("/api/auth/login", json=self.KREDENSIAL_SALAH)

        response = client.post(
            "/api/auth/login", json={"email": "admin@maharasa.id", "password": "rahasia123"}
        )

        assert response.status_code == 429

    def test_login_berhasil_mengosongkan_hitungan(self, client, make_user):
        """Salah ketik beberapa kali lalu berhasil tidak boleh menyisakan blokir."""
        make_user(email="admin@maharasa.id", password="rahasia123")

        for _ in range(settings.LOGIN_MAX_ATTEMPTS - 1):
            client.post("/api/auth/login", json=self.KREDENSIAL_SALAH)

        client.post("/api/auth/login", json={"email": "admin@maharasa.id", "password": "rahasia123"})

        for _ in range(settings.LOGIN_MAX_ATTEMPTS - 1):
            r = client.post("/api/auth/login", json=self.KREDENSIAL_SALAH)
            assert r.status_code == 401

    def test_login_normal_tidak_terpengaruh(self, client, make_user):
        make_user(email="admin@maharasa.id", password="rahasia123")

        response = client.post(
            "/api/auth/login", json={"email": "admin@maharasa.id", "password": "rahasia123"}
        )

        assert response.status_code == 200

    def test_response_429_menyertakan_retry_after(self, client, make_user):
        make_user(email="admin@maharasa.id", password="rahasia123")

        for _ in range(settings.LOGIN_MAX_ATTEMPTS):
            client.post("/api/auth/login", json=self.KREDENSIAL_SALAH)

        response = client.post("/api/auth/login", json=self.KREDENSIAL_SALAH)

        assert "retry-after" in {k.lower() for k in response.headers}

    def test_endpoint_lain_tidak_ikut_terblokir(self, client, make_user, token_for):
        user = make_user(email="admin@maharasa.id", password="rahasia123", role="admin")
        token = token_for(user)

        for _ in range(settings.LOGIN_MAX_ATTEMPTS + 2):
            client.post("/api/auth/login", json=self.KREDENSIAL_SALAH)

        response = client.get("/api/sales/", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200

    def test_percobaan_dicatat_di_log(self, client, make_user, caplog):
        make_user(email="admin@maharasa.id", password="rahasia123")

        with caplog.at_level("WARNING", logger="sync-api"):
            for _ in range(settings.LOGIN_MAX_ATTEMPTS + 1):
                client.post("/api/auth/login", json=self.KREDENSIAL_SALAH)

        assert "RATE LIMIT" in caplog.text
