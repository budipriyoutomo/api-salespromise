"""Penanda password sementara (TODO frontend 2.8).

Admin pertama — dan setiap user yang passwordnya direset admin — dibuat dengan
password sementara yang diketahui orang lain. Selama tidak ada penanda di
`UserResponse`, frontend tidak punya cara jujur untuk tahu itu, jadi tidak
bisa memaksa penggantian.

Yang dikunci di sini adalah **siklus hidup penandanya**: menyala saat password
ditentukan orang lain, padam saat pemiliknya mengganti sendiri.
"""

from app.models.user import User
from app.schemas.auth_schema import UserResponse
from app.services import user_service


def buat_user(db, email="a@maharasa.id", role="admin", **kwargs):
    return user_service.create_user(
        db, email=email, password="rahasia123", role=role, **kwargs
    )


class TestPenandaAdaDiKontrak:

    def test_user_response_membawa_must_change_password(self):
        assert "must_change_password" in UserResponse.model_fields

    def test_default_false_supaya_baris_lama_tidak_ikut_terkunci(self):
        # User yang sudah ada sebelum kolom ini lahir tidak boleh tiba-tiba
        # dipaksa ganti password saat login berikutnya.
        hasil = UserResponse(
            id=1, email="a@maharasa.id", role="admin", is_active=True
        )

        assert hasil.must_change_password is False


class TestSiklusHidupPenanda:

    def test_user_baru_wajib_ganti_password(self, db_session):
        user = buat_user(db_session)

        assert user.must_change_password is True

    def test_reset_oleh_admin_menyalakan_penanda_lagi(self, db_session):
        user = buat_user(db_session)
        # Pemiliknya sudah pernah mengganti sendiri…
        user_service.ganti_password_sendiri(db_session, user.id, "barusendiri1")
        assert user.must_change_password is False

        # …lalu admin mereset paksa: penandanya harus menyala lagi.
        user_service.set_password(db_session, user.id, "direset12345")

        assert user.must_change_password is True

    def test_ganti_sendiri_memadamkan_penanda(self, db_session):
        user = buat_user(db_session)

        user_service.ganti_password_sendiri(db_session, user.id, "barusendiri1")

        assert user.must_change_password is False

    def test_ganti_sendiri_tetap_menerapkan_panjang_minimal(self, db_session):
        user = buat_user(db_session)

        try:
            user_service.ganti_password_sendiri(db_session, user.id, "pendek")
        except user_service.DataTidakValid:
            pass
        else:
            raise AssertionError("password pendek seharusnya ditolak")

        # Gagal berarti tidak mengubah apa pun, termasuk penandanya.
        assert user.must_change_password is True


class TestKolomModel:

    def test_kolom_ada_di_model_dengan_default_aman(self, db_session):
        user = User(
            email="polos@maharasa.id",
            password_hash="x",
            role="admin",
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        # Dibuat lewat jalur lain (CLI lama, SQL manual) → tidak dipaksa.
        assert user.must_change_password is False
