"""Test item infrastruktur Fase 3.

Mencakup: helper waktu pengganti `datetime.utcnow()`, penutupan koneksi
RabbitMQ, batas ukuran payload sync, konfigurasi broker terpusat, dan
health check yang benar-benar memeriksa database.
"""

from datetime import datetime, timezone

import pytest

from app.config import settings
from app.core.time import utcnow


class TestUtcNow:
    """Item 3.2 — `datetime.utcnow()` deprecated sejak Python 3.12."""

    def test_mengembalikan_waktu_utc(self):
        sebelum = datetime.now(timezone.utc).replace(tzinfo=None)
        hasil = utcnow()
        sesudah = datetime.now(timezone.utc).replace(tzinfo=None)

        assert sebelum <= hasil <= sesudah

    def test_naive_bukan_timezone_aware(self):
        """Kolom DB bertipe TIMESTAMP tanpa timezone.

        Kalau helper ini mengembalikan datetime ber-timezone, PostgreSQL akan
        menafsirkan angkanya apa adanya dan nilai tersimpan bisa bergeser
        beberapa jam. Naive-UTC menjaga perilakunya persis seperti
        `datetime.utcnow()` yang digantikan.
        """
        assert utcnow().tzinfo is None

    def test_setara_dengan_utcnow_lama(self):
        selisih = abs((utcnow() - datetime.now(timezone.utc).replace(tzinfo=None)).total_seconds())

        assert selisih < 1

    def test_tidak_memakai_api_yang_deprecated(self):
        """Pastikan tidak ada `datetime.utcnow()` tersisa di kode aplikasi."""
        import pathlib

        akar = pathlib.Path(__file__).resolve().parents[2]
        tersisa = []

        for berkas in list((akar / "app").rglob("*.py")) + [akar / "manage_keys.py", akar / "manage_users.py"]:
            isi = berkas.read_text(encoding="utf-8")
            if "utcnow()" in isi and "def utcnow" not in isi and "datetime.utcnow()" in isi:
                tersisa.append(str(berkas.relative_to(akar)))

        assert tersisa == [], f"masih memakai datetime.utcnow(): {tersisa}"


class TestRabbitMqConfig:
    """Item 3.9 — konfigurasi broker tidak lagi tersebar sebagai os.getenv."""

    def test_ada_di_settings(self):
        assert settings.RABBITMQ_HOST == "test-rabbit"
        assert settings.RABBITMQ_USER == "test-user"
        assert settings.RABBITMQ_PASSWORD == "test-pass"

    def test_client_membaca_dari_settings(self, monkeypatch):
        from app.services.rabbitmq import RabbitMQClient

        monkeypatch.setattr(settings, "RABBITMQ_HOST", "broker-lain")

        assert RabbitMQClient().host == "broker-lain"


class TestRabbitMqDependency:
    """Item 3.3 — koneksi bocor karena client dibuat tiap request dan tak ditutup."""

    def test_dependency_menutup_koneksi_setelah_request(self, monkeypatch):
        from app.routes import sales_routes

        ditutup = []

        class FakeClient:
            def close(self):
                ditutup.append(True)

        monkeypatch.setattr(sales_routes, "RabbitMQClient", FakeClient)

        generator = sales_routes.get_rabbitmq_client()
        next(generator)
        with pytest.raises(StopIteration):
            next(generator)

        assert ditutup == [True]

    def test_koneksi_ditutup_walau_request_error(self, monkeypatch):
        """Kalau tidak, satu broker down bisa menghabiskan koneksi."""
        from app.routes import sales_routes

        ditutup = []

        class FakeClient:
            def close(self):
                ditutup.append(True)

        monkeypatch.setattr(sales_routes, "RabbitMQClient", FakeClient)

        generator = sales_routes.get_rabbitmq_client()
        next(generator)
        with pytest.raises(RuntimeError):
            generator.throw(RuntimeError("publish gagal"))

        assert ditutup == [True]

    def test_kegagalan_menutup_tidak_menggagalkan_request(self, monkeypatch):
        """Broker yang sudah putus tidak boleh mengubah response sukses jadi 500."""
        from app.routes import sales_routes

        class FakeClient:
            def close(self):
                raise RuntimeError("koneksi sudah putus")

        monkeypatch.setattr(sales_routes, "RabbitMQClient", FakeClient)

        generator = sales_routes.get_rabbitmq_client()
        next(generator)
        with pytest.raises(StopIteration):
            next(generator)


class TestBatasPayloadSync:
    """Item 3.6 — satu request tidak boleh membawa payload tak terbatas."""

    def test_batas_terdefinisi(self):
        from app.schemas.sales_schema import MAX_SALES_PER_REQUEST

        assert MAX_SALES_PER_REQUEST > 0

    def test_payload_melebihi_batas_ditolak_422(self, client, api_key_headers):
        from app.schemas.sales_schema import MAX_SALES_PER_REQUEST

        body = {"sales": [{"transaction_id": i} for i in range(MAX_SALES_PER_REQUEST + 1)]}

        response = client.post("/api/sync/sales", json=body, headers=api_key_headers)

        assert response.status_code == 422

    def test_payload_tepat_di_batas_diterima(self, client, api_key_headers, monkeypatch):
        from app.schemas.sales_schema import MAX_SALES_PER_REQUEST

        monkeypatch.setattr(
            "app.routes.sync_routes.SalesService.sync_sales",
            staticmethod(lambda db, outlet, sales_list: {"sales": len(sales_list), "items": 0}),
        )
        body = {"sales": [{"transaction_id": i} for i in range(MAX_SALES_PER_REQUEST)]}

        response = client.post("/api/sync/sales", json=body, headers=api_key_headers)

        assert response.status_code == 200

    def test_pesan_error_menyebut_batasnya(self, client, api_key_headers):
        from app.schemas.sales_schema import MAX_SALES_PER_REQUEST

        body = {"sales": [{"transaction_id": i} for i in range(MAX_SALES_PER_REQUEST + 1)]}

        response = client.post("/api/sync/sales", json=body, headers=api_key_headers)

        assert str(MAX_SALES_PER_REQUEST) in response.text


class TestHealthReady:
    """Item 3.12 — health check yang benar-benar memeriksa dependency."""

    def test_ready_mengembalikan_200_saat_database_sehat(self, client):
        response = client.get("/health/ready")

        assert response.status_code == 200
        assert response.json()["database"] == "ok"

    def test_ready_mengembalikan_503_saat_database_mati(self, client, monkeypatch):
        """Load balancer harus bisa mengeluarkan instance yang DB-nya putus."""
        from app.database import get_db
        from app.main import app

        class DbMati:
            def execute(self, *args, **kwargs):
                raise RuntimeError("connection refused")

        app.dependency_overrides[get_db] = lambda: DbMati()

        response = client.get("/health/ready")

        assert response.status_code == 503
        assert response.json()["database"] == "error"

    def test_ready_terbuka_tanpa_autentikasi(self, client):
        assert client.get("/health/ready").status_code == 200

    def test_health_biasa_tidak_menyentuh_database(self, client, monkeypatch):
        """`/health` dipakai liveness probe — harus tetap jawab walau DB mati."""
        from app.database import get_db
        from app.main import app

        class DbMati:
            def execute(self, *args, **kwargs):
                raise RuntimeError("connection refused")

        app.dependency_overrides[get_db] = lambda: DbMati()

        assert client.get("/health").status_code == 200
        assert client.get("/").status_code == 200


class TestInitDbGuard:
    """`init_db.py` memanggil drop_all() — satu kali salah jalan, data hilang."""

    def test_butuh_konfirmasi_eksplisit(self, monkeypatch):
        import init_db

        monkeypatch.delenv("INIT_DB_CONFIRM", raising=False)

        assert init_db.boleh_drop() is False

    def test_konfirmasi_lewat_env(self, monkeypatch):
        import init_db

        monkeypatch.setenv("INIT_DB_CONFIRM", "DROP-ALL")

        assert init_db.boleh_drop() is True

    def test_nilai_konfirmasi_salah_ditolak(self, monkeypatch):
        import init_db

        monkeypatch.setenv("INIT_DB_CONFIRM", "yes")

        assert init_db.boleh_drop() is False
