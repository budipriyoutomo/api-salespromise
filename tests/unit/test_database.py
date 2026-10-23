"""Test app/database.py — dependency session dan konfigurasi engine."""

import pytest

from app.config import Settings
from app.database import Base, engine, engine_options, get_db


class TestGetDb:

    def test_menghasilkan_satu_session(self, monkeypatch):
        dibuat = []

        class FakeSession:
            def __init__(self):
                self.closed = False
                dibuat.append(self)

            def close(self):
                self.closed = True

        monkeypatch.setattr("app.database.SessionLocal", FakeSession)

        gen = get_db()
        session = next(gen)

        assert session is dibuat[0]

    def test_session_ditutup_setelah_request_selesai(self, monkeypatch):
        class FakeSession:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        monkeypatch.setattr("app.database.SessionLocal", FakeSession)

        gen = get_db()
        session = next(gen)
        with pytest.raises(StopIteration):
            next(gen)

        assert session.closed is True

    def test_session_ditutup_walau_request_error(self, monkeypatch):
        """Kalau tidak, koneksi pool habis setiap kali ada request yang gagal."""

        class FakeSession:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        monkeypatch.setattr("app.database.SessionLocal", FakeSession)

        gen = get_db()
        session = next(gen)
        with pytest.raises(RuntimeError):
            gen.throw(RuntimeError("route gagal"))

        assert session.closed is True


class TestEngine:

    def test_memakai_pool_pre_ping(self):
        """Tanpa ini, koneksi yang sudah diputus server bikin request pertama gagal."""
        assert engine.pool._pre_ping is True

    def test_ukuran_pool_dari_settings(self):
        assert engine.pool.size() == 5
        assert engine.pool._max_overflow == 5
        assert engine.pool._timeout == 10


class TestEngineOptions:

    def _settings(self, **nilai):
        s = Settings()
        for nama, v in nilai.items():
            setattr(s, nama, v)
        return s

    def test_meneruskan_ukuran_pool_dan_timeout(self):
        opsi = engine_options(
            self._settings(DB_POOL_SIZE=3, DB_MAX_OVERFLOW=2, DB_POOL_TIMEOUT=7, DB_POOL_RECYCLE=900)
        )

        assert opsi["pool_pre_ping"] is True
        assert (opsi["pool_size"], opsi["max_overflow"]) == (3, 2)
        assert (opsi["pool_timeout"], opsi["pool_recycle"]) == (7, 900)

    def test_statement_timeout_dikirim_saat_connect(self):
        """Satu query berat tidak boleh menahan koneksi pool sampai semua request antre."""
        opsi = engine_options(self._settings(DB_STATEMENT_TIMEOUT_MS=30000))

        assert opsi["connect_args"] == {"options": "-c statement_timeout=30000"}

    def test_statement_timeout_nol_berarti_tanpa_batas(self):
        opsi = engine_options(self._settings(DB_STATEMENT_TIMEOUT_MS=0))

        assert "connect_args" not in opsi

    def test_semua_model_terdaftar_di_metadata(self):
        """Dipakai init_db.py dan test — pastikan tidak ada model yang lupa di-import."""
        import app.models.api_key  # noqa: F401
        import app.models.sales  # noqa: F401
        import app.models.sales_items  # noqa: F401

        assert {"ordertransaction", "orderdetail", "api_keys"} <= set(Base.metadata.tables)
