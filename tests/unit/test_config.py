"""Test app/config.py — penyusunan DATABASE_URL dan validasi env."""

import pytest

from app.config import Settings, settings


class TestDatabaseUrl:

    def test_menyusun_url_dari_komponen_env(self):
        s = Settings()
        s.DB_USER = "budi"
        s.DB_PASS = "rahasia"
        s.DB_HOST = "db.internal"
        s.DB_PORT = "5433"
        s.DB_NAME = "maharasa"

        assert s.DATABASE_URL == "postgresql+psycopg2://budi:rahasia@db.internal:5433/maharasa"

    def test_memakai_driver_psycopg2(self):
        assert settings.DATABASE_URL.startswith("postgresql+psycopg2://")

    @pytest.mark.parametrize(
        "raw_password, encoded",
        [
            ("p@ssw0rd", "p%40ssw0rd"),
            ("pass:word", "pass%3Aword"),
            ("pass/word", "pass%2Fword"),
            ("pass word", "pass+word"),
            ("p@ss:w/ord", "p%40ss%3Aw%2Ford"),
        ],
    )
    def test_password_karakter_spesial_di_url_encode(self, raw_password, encoded):
        """Kalau ini bocor, koneksi gagal diam-diam dengan error auth yang menyesatkan."""
        s = Settings()
        s.DB_USER = "budi"
        s.DB_PASS = raw_password
        s.DB_HOST = "localhost"
        s.DB_PORT = "5432"
        s.DB_NAME = "db"

        assert f":{encoded}@" in s.DATABASE_URL
        assert raw_password not in s.DATABASE_URL.split("@")[0].replace(encoded, "")

    def test_password_biasa_tidak_berubah(self):
        s = Settings()
        s.DB_USER = "u"
        s.DB_PASS = "simplepass123"
        s.DB_HOST = "h"
        s.DB_PORT = "1"
        s.DB_NAME = "n"

        assert ":simplepass123@" in s.DATABASE_URL


class TestValidate:

    def test_lolos_saat_semua_env_terisi(self):
        s = Settings()
        s.DB_USER = "u"
        s.DB_PASS = "p"
        s.DB_NAME = "n"
        s.JWT_SECRET = "secret"

        assert s.validate() is None

    @pytest.mark.parametrize("missing_field", ["DB_USER", "DB_PASS", "DB_NAME", "JWT_SECRET"])
    def test_error_saat_satu_env_kosong(self, missing_field):
        s = Settings()
        s.DB_USER = "u"
        s.DB_PASS = "p"
        s.DB_NAME = "n"
        s.JWT_SECRET = "secret"
        setattr(s, missing_field, "")

        with pytest.raises(ValueError) as exc:
            s.validate()

        assert missing_field in str(exc.value)

    def test_menyebut_semua_env_yang_hilang_sekaligus(self):
        """Jangan cuma laporkan yang pertama — developer harus tahu semuanya."""
        s = Settings()
        s.DB_USER = ""
        s.DB_PASS = ""
        s.DB_NAME = ""
        s.JWT_SECRET = ""

        with pytest.raises(ValueError) as exc:
            s.validate()

        message = str(exc.value)
        assert "DB_USER" in message
        assert "DB_PASS" in message
        assert "DB_NAME" in message
        assert "JWT_SECRET" in message

    def test_jwt_secret_wajib(self):
        """Tanpa secret, token tidak bisa ditandatangani — aplikasi tidak boleh start."""
        s = Settings()
        s.DB_USER = "u"
        s.DB_PASS = "p"
        s.DB_NAME = "n"
        s.JWT_SECRET = ""

        with pytest.raises(ValueError, match="JWT_SECRET"):
            s.validate()

    def test_db_host_dan_port_tidak_wajib(self):
        """Keduanya punya default, jadi tidak boleh bikin validate() gagal."""
        s = Settings()
        s.DB_USER = "u"
        s.DB_PASS = "p"
        s.DB_NAME = "n"
        s.JWT_SECRET = "secret"
        s.DB_HOST = ""
        s.DB_PORT = ""

        assert s.validate() is None


class TestDefaultEnv:
    """Env dibaca saat `Settings()` dibuat, jadi tidak perlu reload modul.

    Versi sebelumnya memakai `importlib.reload(app.config)` — itu menghasilkan
    objek `settings` baru sementara modul lain (mis. `app.services.rabbitmq`)
    masih memegang objek lama, dan menyebabkan kegagalan yang hanya muncul saat
    seluruh suite dijalankan bersamaan.
    """

    def test_default_dipakai_saat_env_tidak_diset(self, monkeypatch):
        monkeypatch.delenv("DB_HOST", raising=False)
        monkeypatch.delenv("DB_PORT", raising=False)
        monkeypatch.delenv("LOG_LEVEL", raising=False)

        s = Settings()

        assert s.DB_HOST == "localhost"
        assert s.DB_PORT == "5432"
        assert s.LOG_LEVEL == "INFO"

    def test_default_token_dan_payload(self, monkeypatch):
        monkeypatch.delenv("ACCESS_TOKEN_EXPIRE_MINUTES", raising=False)
        monkeypatch.delenv("REFRESH_TOKEN_EXPIRE_DAYS", raising=False)
        monkeypatch.delenv("MAX_SALES_PER_REQUEST", raising=False)

        s = Settings()

        assert s.ACCESS_TOKEN_EXPIRE_MINUTES == 30
        assert s.REFRESH_TOKEN_EXPIRE_DAYS == 7
        assert s.MAX_SALES_PER_REQUEST == 1000

    def test_password_rabbitmq_tidak_punya_default(self, monkeypatch):
        """Lebih baik gagal terhubung daripada menaruh kredensial di kode."""
        monkeypatch.delenv("RABBITMQ_PASSWORD", raising=False)

        assert Settings().RABBITMQ_PASSWORD == ""

    def test_env_dibaca_ulang_tiap_instansiasi(self, monkeypatch):
        monkeypatch.setenv("DB_HOST", "host-a")
        assert Settings().DB_HOST == "host-a"

        monkeypatch.setenv("DB_HOST", "host-b")
        assert Settings().DB_HOST == "host-b"

    def test_validate_dipanggil_saat_import(self):
        """`settings` global harus sudah tervalidasi begitu modul di-import."""
        assert settings.DB_USER
        assert settings.DB_PASS
        assert settings.DB_NAME
        assert settings.JWT_SECRET


class TestCorsOrigins:

    def test_dipecah_dari_daftar_berkoma(self):
        assert settings.CORS_ORIGINS == ["http://localhost:3000", "https://dashboard.maharasa.id"]

    def test_spasi_di_sekitar_koma_dibuang(self, monkeypatch):
        monkeypatch.setenv("CORS_ORIGINS", " http://a.id , http://b.id ")

        assert Settings().CORS_ORIGINS == ["http://a.id", "http://b.id"]

    def test_env_kosong_menghasilkan_list_kosong(self, monkeypatch):
        """CORS dimatikan total kalau belum ada frontend — bukan diizinkan semua."""
        monkeypatch.setenv("CORS_ORIGINS", "")

        assert Settings().CORS_ORIGINS == []

    def test_entri_kosong_diabaikan(self, monkeypatch):
        monkeypatch.setenv("CORS_ORIGINS", "http://a.id,,http://b.id,")

        assert Settings().CORS_ORIGINS == ["http://a.id", "http://b.id"]
