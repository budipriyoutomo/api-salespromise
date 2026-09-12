"""Test manage_users.py — CLI user dashboard.

Tanpa CLI ini tidak ada cara membuat user pertama, jadi frontend tidak akan
pernah bisa login.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import manage_users
from app.core import security
from app.database import Base
from app.models.user import User


@pytest.fixture()
def user_store(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    monkeypatch.setattr(manage_users, "SessionLocal", factory)

    class Store:
        def all(self):
            session = factory()
            try:
                return session.query(User).all()
            finally:
                session.close()

        def get(self, email):
            session = factory()
            try:
                return session.query(User).filter(User.email == email).first()
            finally:
                session.close()

    try:
        yield Store()
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


class TestCreate:

    def test_membuat_user_admin(self, user_store, capsys):
        manage_users.create_user(email="admin@maharasa.id", role="admin", password="rahasia123")

        user = user_store.get("admin@maharasa.id")
        assert user is not None
        assert user.role == "admin"
        assert user.is_active is True

    def test_password_disimpan_sebagai_hash(self, user_store):
        manage_users.create_user(email="admin@maharasa.id", role="admin", password="rahasia123")

        user = user_store.get("admin@maharasa.id")
        assert user.password_hash != "rahasia123"
        assert security.verify_password("rahasia123", user.password_hash) is True

    def test_password_tidak_muncul_di_output(self, user_store, capsys):
        manage_users.create_user(email="admin@maharasa.id", role="admin", password="rahasia123")

        assert "rahasia123" not in capsys.readouterr().out

    def test_email_disimpan_lowercase(self, user_store):
        """Login memakai perbandingan lowercase — penyimpanannya harus sejalan."""
        manage_users.create_user(email="  Admin@Maharasa.ID  ", role="admin", password="rahasia123")

        assert user_store.get("admin@maharasa.id") is not None

    def test_role_outlet_menyimpan_outlet_code(self, user_store):
        manage_users.create_user(
            email="kasir@maharasa.id",
            role="outlet",
            outlet_code="OUTLET_001",
            password="rahasia123",
        )

        assert user_store.get("kasir@maharasa.id").outlet_code == "OUTLET_001"

    def test_role_outlet_tanpa_outlet_code_ditolak(self, user_store, capsys):
        """User 'outlet' tanpa outlet akan selalu kena 403 — cegah sejak pembuatan."""
        manage_users.create_user(email="kasir@maharasa.id", role="outlet", password="rahasia123")

        assert user_store.get("kasir@maharasa.id") is None
        assert "wajib disertai" in capsys.readouterr().out

    def test_outlet_code_diabaikan_untuk_role_admin(self, user_store):
        """Admin lintas outlet — menyimpan outlet_code hanya bikin rancu."""
        manage_users.create_user(
            email="admin@maharasa.id",
            role="admin",
            outlet_code="OUTLET_001",
            password="rahasia123",
        )

        assert user_store.get("admin@maharasa.id").outlet_code is None

    def test_role_tidak_dikenal_ditolak(self, user_store, capsys):
        manage_users.create_user(email="x@maharasa.id", role="superuser", password="rahasia123")

        assert user_store.get("x@maharasa.id") is None
        assert "tidak dikenal" in capsys.readouterr().out

    def test_email_duplikat_ditolak(self, user_store, capsys):
        manage_users.create_user(email="admin@maharasa.id", role="admin", password="rahasia123")
        manage_users.create_user(email="admin@maharasa.id", role="manager", password="lainnya123")

        assert len(user_store.all()) == 1
        assert user_store.get("admin@maharasa.id").role == "admin"

    def test_password_terlalu_pendek_ditolak(self, user_store, capsys):
        manage_users.create_user(email="admin@maharasa.id", role="admin", password="pendek")

        assert user_store.get("admin@maharasa.id") is None
        assert "minimal" in capsys.readouterr().out

    def test_nama_lengkap_tersimpan(self, user_store):
        manage_users.create_user(
            email="admin@maharasa.id",
            role="admin",
            password="rahasia123",
            full_name="Budi Priyo",
        )

        assert user_store.get("admin@maharasa.id").full_name == "Budi Priyo"

    def test_password_ditanya_lewat_prompt_kalau_tidak_diberikan(self, user_store, monkeypatch):
        """Supaya password tidak tercatat di shell history."""
        jawaban = iter(["rahasia123", "rahasia123"])
        monkeypatch.setattr(manage_users.getpass, "getpass", lambda prompt="": next(jawaban))

        manage_users.create_user(email="admin@maharasa.id", role="admin")

        assert user_store.get("admin@maharasa.id") is not None

    def test_konfirmasi_password_tidak_cocok_membatalkan(self, user_store, monkeypatch, capsys):
        jawaban = iter(["rahasia123", "salah-ketik"])
        monkeypatch.setattr(manage_users.getpass, "getpass", lambda prompt="": next(jawaban))

        manage_users.create_user(email="admin@maharasa.id", role="admin")

        assert user_store.get("admin@maharasa.id") is None
        assert "tidak sama" in capsys.readouterr().out


class TestChangePassword:

    def test_mengganti_password(self, user_store):
        manage_users.create_user(email="admin@maharasa.id", role="admin", password="rahasia123")

        manage_users.change_password(email="admin@maharasa.id", password="barubaru123")

        user = user_store.get("admin@maharasa.id")
        assert security.verify_password("barubaru123", user.password_hash) is True
        assert security.verify_password("rahasia123", user.password_hash) is False

    def test_user_tidak_ada_tidak_melempar_exception(self, user_store, capsys):
        manage_users.change_password(email="hantu@maharasa.id", password="barubaru123")

        assert "tidak ditemukan" in capsys.readouterr().out

    def test_password_terlalu_pendek_ditolak(self, user_store, capsys):
        manage_users.create_user(email="admin@maharasa.id", role="admin", password="rahasia123")

        manage_users.change_password(email="admin@maharasa.id", password="pendek")

        user = user_store.get("admin@maharasa.id")
        assert security.verify_password("rahasia123", user.password_hash) is True


class TestSetActive:

    def test_menonaktifkan_user(self, user_store):
        manage_users.create_user(email="budi@maharasa.id", role="manager", password="rahasia123")

        manage_users.set_active("budi@maharasa.id", False)

        assert user_store.get("budi@maharasa.id").is_active is False

    def test_mengaktifkan_kembali(self, user_store):
        manage_users.create_user(email="budi@maharasa.id", role="manager", password="rahasia123")
        manage_users.set_active("budi@maharasa.id", False)

        manage_users.set_active("budi@maharasa.id", True)

        assert user_store.get("budi@maharasa.id").is_active is True

    def test_admin_aktif_terakhir_tidak_bisa_dinonaktifkan(self, user_store, capsys):
        """Kalau lolos, sistem kehilangan admin dan hanya bisa dipulihkan lewat DB."""
        manage_users.create_user(email="admin@maharasa.id", role="admin", password="rahasia123")
        capsys.readouterr()

        manage_users.set_active("admin@maharasa.id", False)

        assert user_store.get("admin@maharasa.id").is_active is True
        assert "minimal satu admin" in capsys.readouterr().out

    def test_admin_bisa_dinonaktifkan_kalau_masih_ada_admin_lain(self, user_store):
        manage_users.create_user(email="admin@maharasa.id", role="admin", password="rahasia123")
        manage_users.create_user(email="admin2@maharasa.id", role="admin", password="rahasia123")

        manage_users.set_active("admin@maharasa.id", False)

        assert user_store.get("admin@maharasa.id").is_active is False

    def test_user_tidak_ada_tidak_melempar_exception(self, user_store, capsys):
        manage_users.set_active("hantu@maharasa.id", False)

        assert "tidak ditemukan" in capsys.readouterr().out


class TestList:

    def test_pesan_saat_belum_ada_user(self, user_store, capsys):
        manage_users.list_users()

        assert "Belum ada user" in capsys.readouterr().out

    def test_menampilkan_semua_user(self, user_store, capsys):
        manage_users.create_user(email="admin@maharasa.id", role="admin", password="rahasia123")
        manage_users.create_user(
            email="kasir@maharasa.id", role="outlet", outlet_code="OUTLET_001", password="rahasia123"
        )
        capsys.readouterr()

        manage_users.list_users()
        output = capsys.readouterr().out

        assert "admin@maharasa.id" in output
        assert "kasir@maharasa.id" in output
        assert "OUTLET_001" in output

    def test_tidak_menampilkan_password_hash(self, user_store, capsys):
        manage_users.create_user(email="admin@maharasa.id", role="admin", password="rahasia123")
        hash_tersimpan = user_store.get("admin@maharasa.id").password_hash
        capsys.readouterr()

        manage_users.list_users()

        assert hash_tersimpan not in capsys.readouterr().out


class TestCli:

    def test_list_tanpa_email(self, user_store, capsys):
        manage_users.main(["list"])

        assert "Belum ada user" in capsys.readouterr().out

    def test_action_selain_list_butuh_email(self, user_store, capsys):
        manage_users.main(["create", "--role", "admin", "--password", "rahasia123"])

        assert "--email wajib diisi" in capsys.readouterr().out

    def test_create_lewat_cli(self, user_store):
        manage_users.main(
            ["create", "--email", "admin@maharasa.id", "--role", "admin", "--password", "rahasia123"]
        )

        assert user_store.get("admin@maharasa.id") is not None

    def test_deactivate_lewat_cli(self, user_store):
        manage_users.main(
            ["create", "--email", "budi@maharasa.id", "--role", "manager", "--password", "rahasia123"]
        )

        manage_users.main(["deactivate", "--email", "budi@maharasa.id"])

        assert user_store.get("budi@maharasa.id").is_active is False
