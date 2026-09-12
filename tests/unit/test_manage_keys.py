"""Test manage_keys.py — CLI pengelolaan API key per outlet.

SessionLocal milik modul di-patch ke SQLite in-memory dengan StaticPool,
supaya semua pemanggilan berbagi koneksi yang sama meski tiap fungsi
menutup sessionnya sendiri.
"""

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import manage_keys
from app.core import security
from app.database import Base
from app.models.api_key import ApiKey


def _key_dari_output(output):
    """Ambil key mentah dari baris 'Key: xxx' pada output CLI."""
    for line in output.splitlines():
        if line.strip().startswith("Key:"):
            return line.split("Key:", 1)[1].strip()
    raise AssertionError("Key tidak ditemukan di output: " + output)


@pytest.fixture()
def key_store(monkeypatch):
    """Sediakan penyimpanan key sementara + helper untuk memeriksa isinya."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    monkeypatch.setattr(manage_keys, "SessionLocal", factory)

    class Store:
        def all(self):
            session = factory()
            try:
                return session.query(ApiKey).all()
            finally:
                session.close()

        def get(self, outlet_code):
            session = factory()
            try:
                return session.query(ApiKey).filter(ApiKey.outlet_code == outlet_code).first()
            finally:
                session.close()

        def seed(self, outlet_code, key="key-lama", is_active=True):
            session = factory()
            try:
                session.add(
                    ApiKey(
                        key_hash=security.hash_api_key(key),
                        key_prefix=security.api_key_prefix(key),
                        outlet_code=outlet_code,
                        is_active=is_active,
                        created_at=datetime(2026, 1, 1),
                    )
                )
                session.commit()
            finally:
                session.close()

    try:
        yield Store()
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


class TestGenerate:

    def test_membuat_key_baru(self, key_store, capsys):
        manage_keys.generate_key("OUTLET_001")

        saved = key_store.get("OUTLET_001")
        assert saved is not None
        assert saved.outlet_code == "OUTLET_001"

    def test_key_baru_langsung_aktif(self, key_store):
        manage_keys.generate_key("OUTLET_001")

        assert key_store.get("OUTLET_001").is_active is True

    def test_created_at_terisi(self, key_store):
        manage_keys.generate_key("OUTLET_001")

        assert key_store.get("OUTLET_001").created_at is not None

    def test_key_mentah_ditampilkan_sekali_di_output(self, key_store, capsys):
        manage_keys.generate_key("OUTLET_001")
        output = capsys.readouterr().out

        assert "OUTLET_001" in output
        assert "tidak bisa dilihat lagi" in output

    def test_database_hanya_menyimpan_hash(self, key_store, capsys):
        """Kalau DB bocor, key mentah tidak ikut terbawa."""
        manage_keys.generate_key("OUTLET_001")
        raw = _key_dari_output(capsys.readouterr().out)

        tersimpan = key_store.get("OUTLET_001")
        assert tersimpan.key_hash != raw
        assert tersimpan.key_hash == security.hash_api_key(raw)

    def test_prefix_disimpan_untuk_identifikasi(self, key_store, capsys):
        manage_keys.generate_key("OUTLET_001")
        raw = _key_dari_output(capsys.readouterr().out)

        assert key_store.get("OUTLET_001").key_prefix == raw[:8]

    def test_key_cukup_panjang(self, key_store, capsys):
        """token_urlsafe(32) → 43 karakter; kolom DB menampung hash 64 karakter."""
        manage_keys.generate_key("OUTLET_001")
        raw = _key_dari_output(capsys.readouterr().out)

        assert len(raw) >= 32
        assert len(key_store.get("OUTLET_001").key_hash) == 64

    def test_key_unik_antar_outlet(self, key_store):
        manage_keys.generate_key("OUTLET_001")
        manage_keys.generate_key("OUTLET_002")
        manage_keys.generate_key("OUTLET_003")

        keys = {k.key_hash for k in key_store.all()}
        assert len(keys) == 3

    def test_outlet_yang_sudah_punya_key_tidak_ditimpa(self, key_store, capsys):
        """Kalau ditimpa, mesin POS di lapangan langsung kehilangan akses."""
        key_store.seed("OUTLET_001", key="key-lama")

        manage_keys.generate_key("OUTLET_001")

        assert key_store.get("OUTLET_001").key_hash == security.hash_api_key("key-lama")
        assert len(key_store.all()) == 1

    def test_memberi_peringatan_saat_key_sudah_ada(self, key_store, capsys):
        key_store.seed("OUTLET_001", key="key-lama")

        manage_keys.generate_key("OUTLET_001")
        output = capsys.readouterr().out

        assert "sudah punya key" in output
        # key mentah tidak boleh muncul lagi, hanya prefix-nya
        assert "key-lama" not in output.replace("key-lama"[:8] + "...", "")

    def test_outlet_nonaktif_tetap_tidak_bisa_generate_ulang(self, key_store, capsys):
        """Penanda perilaku: revoke lalu generate TIDAK menghasilkan key baru.

        README menyebut 'untuk mengaktifkan kembali, generate key baru' —
        alurnya belum sesuai. Ubah test ini kalau perilakunya diperbaiki.
        """
        key_store.seed("OUTLET_001", key="key-lama", is_active=False)

        manage_keys.generate_key("OUTLET_001")
        output = capsys.readouterr().out

        assert key_store.get("OUTLET_001").key_hash == security.hash_api_key("key-lama")
        assert "nonaktif" in output


class TestRevoke:

    def test_menonaktifkan_key(self, key_store):
        key_store.seed("OUTLET_001")

        manage_keys.revoke_key("OUTLET_001")

        assert key_store.get("OUTLET_001").is_active is False

    def test_key_tidak_dihapus(self, key_store):
        """Key disimpan supaya jejak audit tidak hilang."""
        key_store.seed("OUTLET_001", key="key-lama")

        manage_keys.revoke_key("OUTLET_001")

        assert key_store.get("OUTLET_001").key_hash == security.hash_api_key("key-lama")

    def test_outlet_tidak_dikenal_tidak_melempar_exception(self, key_store, capsys):
        manage_keys.revoke_key("OUTLET_TIDAK_ADA")
        output = capsys.readouterr().out

        assert "tidak ditemukan" in output

    def test_tidak_mempengaruhi_outlet_lain(self, key_store):
        key_store.seed("OUTLET_001", key="k1")
        key_store.seed("OUTLET_002", key="k2")

        manage_keys.revoke_key("OUTLET_001")

        assert key_store.get("OUTLET_002").is_active is True

    def test_revoke_dua_kali_aman(self, key_store):
        key_store.seed("OUTLET_001")

        manage_keys.revoke_key("OUTLET_001")
        manage_keys.revoke_key("OUTLET_001")

        assert key_store.get("OUTLET_001").is_active is False


class TestList:

    def test_pesan_saat_belum_ada_key(self, key_store, capsys):
        manage_keys.list_keys()

        assert "Belum ada API key" in capsys.readouterr().out

    def test_menampilkan_semua_outlet(self, key_store, capsys):
        key_store.seed("OUTLET_001", key="k1")
        key_store.seed("OUTLET_002", key="k2")

        manage_keys.list_keys()
        output = capsys.readouterr().out

        assert "OUTLET_001" in output
        assert "OUTLET_002" in output

    def test_status_aktif_dan_nonaktif(self, key_store, capsys):
        key_store.seed("OUTLET_001", key="k1", is_active=True)
        key_store.seed("OUTLET_002", key="k2", is_active=False)

        manage_keys.list_keys()
        output = capsys.readouterr().out

        baris = {line.split()[0]: line for line in output.splitlines() if line.startswith("OUTLET_")}
        assert "aktif" in baris["OUTLET_001"]
        assert "nonaktif" in baris["OUTLET_002"]

    def test_terurut_berdasarkan_outlet_code(self, key_store, capsys):
        key_store.seed("OUTLET_003", key="k3")
        key_store.seed("OUTLET_001", key="k1")
        key_store.seed("OUTLET_002", key="k2")

        manage_keys.list_keys()
        output = capsys.readouterr().out

        urutan = [line.split()[0] for line in output.splitlines() if line.startswith("OUTLET_")]
        assert urutan == ["OUTLET_001", "OUTLET_002", "OUTLET_003"]

    def test_key_tidak_pernah_tampil_penuh(self, key_store, capsys):
        """Item 1.6 — README menjanjikan key tidak bisa dilihat lagi setelah dibuat."""
        key_store.seed("OUTLET_001", key="kunci-rahasia-penuh")

        manage_keys.list_keys()
        output = capsys.readouterr().out

        assert "kunci-rahasia-penuh" not in output
        assert "kunci-ra..." in output

    def test_hash_tidak_ikut_tampil(self, key_store, capsys):
        """Hash pun tidak perlu dipamerkan di terminal."""
        key_store.seed("OUTLET_001", key="kunci-rahasia-penuh")

        manage_keys.list_keys()
        output = capsys.readouterr().out

        assert security.hash_api_key("kunci-rahasia-penuh") not in output
