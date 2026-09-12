"""Test app/database.py — dependency session dan konfigurasi engine."""

import pytest

from app.database import Base, engine, get_db


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

    def test_ukuran_pool(self):
        assert engine.pool.size() == 10
        assert engine.pool._max_overflow == 20

    def test_semua_model_terdaftar_di_metadata(self):
        """Dipakai init_db.py dan test — pastikan tidak ada model yang lupa di-import."""
        import app.models.api_key  # noqa: F401
        import app.models.sales  # noqa: F401
        import app.models.sales_items  # noqa: F401

        assert {"ordertransaction", "orderdetail", "api_keys"} <= set(Base.metadata.tables)
