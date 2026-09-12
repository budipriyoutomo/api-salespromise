"""Test app/core/security.py — hashing dan token."""

from datetime import timedelta

import jwt
import pytest
from freezegun import freeze_time

from app.config import settings
from app.core import security


class TestHashApiKey:

    def test_menghasilkan_sha256_hex_64_karakter(self):
        hashed = security.hash_api_key("kunci-rahasia")

        assert len(hashed) == 64
        assert all(c in "0123456789abcdef" for c in hashed)

    def test_deterministik(self):
        """Lookup mengandalkan ini — key yang sama harus selalu jadi hash yang sama."""
        assert security.hash_api_key("kunci") == security.hash_api_key("kunci")

    def test_key_berbeda_menghasilkan_hash_berbeda(self):
        assert security.hash_api_key("kunci-a") != security.hash_api_key("kunci-b")

    def test_hash_tidak_memuat_key_aslinya(self):
        assert "kunci-rahasia" not in security.hash_api_key("kunci-rahasia")

    def test_cocok_dengan_sha256_postgres(self):
        """Migrasi memakai encode(sha256(key::bytea),'hex') — hasilnya harus identik."""
        import hashlib

        assert security.hash_api_key("abc") == hashlib.sha256(b"abc").hexdigest()


class TestGenerateApiKey:

    def test_panjang_memadai(self):
        key = security.generate_api_key()

        assert len(key) >= 32

    def test_selalu_unik(self):
        keys = {security.generate_api_key() for _ in range(100)}

        assert len(keys) == 100

    def test_aman_untuk_url_dan_header(self):
        key = security.generate_api_key()

        assert key.isascii()
        assert " " not in key


class TestPassword:

    def test_hash_tidak_sama_dengan_password_asli(self):
        hashed = security.hash_password("rahasia123")

        assert hashed != "rahasia123"
        assert "rahasia123" not in hashed

    def test_verify_menerima_password_benar(self):
        hashed = security.hash_password("rahasia123")

        assert security.verify_password("rahasia123", hashed) is True

    def test_verify_menolak_password_salah(self):
        hashed = security.hash_password("rahasia123")

        assert security.verify_password("rahasia124", hashed) is False

    def test_hash_berbeda_tiap_kali_karena_salt(self):
        """Dua user dengan password sama tidak boleh punya hash identik."""
        assert security.hash_password("sama") != security.hash_password("sama")

    def test_verify_tidak_meledak_untuk_hash_rusak(self):
        assert security.verify_password("apa saja", "bukan-hash-bcrypt") is False

    def test_verify_tidak_meledak_untuk_hash_kosong(self):
        assert security.verify_password("apa saja", "") is False

    def test_password_panjang_tetap_bisa_di_hash(self):
        """bcrypt memotong di 72 byte — pastikan tidak melempar error."""
        panjang = "a" * 200

        hashed = security.hash_password(panjang)

        assert security.verify_password(panjang, hashed) is True


class TestAccessToken:

    def test_memuat_identitas_user(self):
        token = security.create_access_token(subject="budi@maharasa.id", role="admin", outlet_code=None)
        payload = security.decode_token(token)

        assert payload["sub"] == "budi@maharasa.id"
        assert payload["role"] == "admin"
        assert payload["outlet_code"] is None

    def test_memuat_outlet_code_untuk_role_outlet(self):
        token = security.create_access_token(subject="kasir@maharasa.id", role="outlet", outlet_code="OUTLET_001")
        payload = security.decode_token(token)

        assert payload["outlet_code"] == "OUTLET_001"

    def test_bertipe_access(self):
        token = security.create_access_token(subject="a@b.id", role="admin", outlet_code=None)

        assert security.decode_token(token)["type"] == "access"

    def test_punya_waktu_kedaluwarsa(self):
        token = security.create_access_token(subject="a@b.id", role="admin", outlet_code=None)
        payload = security.decode_token(token)

        assert payload["exp"] > payload["iat"]

    def test_token_kedaluwarsa_ditolak(self):
        with freeze_time("2026-01-01 08:00:00"):
            token = security.create_access_token(subject="a@b.id", role="admin", outlet_code=None)

        with freeze_time("2026-01-02 08:00:00"):
            with pytest.raises(security.TokenError):
                security.decode_token(token)

    def test_token_masih_berlaku_sebelum_kedaluwarsa(self):
        with freeze_time("2026-01-01 08:00:00"):
            token = security.create_access_token(subject="a@b.id", role="admin", outlet_code=None)

        with freeze_time("2026-01-01 08:10:00"):
            assert security.decode_token(token)["sub"] == "a@b.id"

    def test_masa_berlaku_bisa_diatur(self):
        with freeze_time("2026-01-01 08:00:00"):
            token = security.create_access_token(
                subject="a@b.id",
                role="admin",
                outlet_code=None,
                expires_delta=timedelta(minutes=1),
            )

        with freeze_time("2026-01-01 08:02:00"):
            with pytest.raises(security.TokenError):
                security.decode_token(token)


class TestRefreshToken:

    def test_bertipe_refresh(self):
        token = security.create_refresh_token(subject="a@b.id")

        assert security.decode_token(token)["type"] == "refresh"

    def test_berumur_lebih_panjang_dari_access_token(self):
        with freeze_time("2026-01-01 08:00:00"):
            access = security.decode_token(
                security.create_access_token(subject="a@b.id", role="admin", outlet_code=None)
            )
            refresh = security.decode_token(security.create_refresh_token(subject="a@b.id"))

        assert refresh["exp"] > access["exp"]


class TestDecodeToken:

    def test_menolak_token_ngawur(self):
        with pytest.raises(security.TokenError):
            security.decode_token("bukan.token.jwt")

    def test_menolak_token_kosong(self):
        with pytest.raises(security.TokenError):
            security.decode_token("")

    def test_menolak_tanda_tangan_dari_secret_lain(self):
        """Pertahanan utama — token buatan sendiri tidak boleh diterima."""
        palsu = jwt.encode(
            {"sub": "penyusup@jahat.id", "role": "admin", "type": "access", "exp": 9999999999},
            "secret-palsu",
            algorithm="HS256",
        )

        with pytest.raises(security.TokenError):
            security.decode_token(palsu)

    def test_menolak_algoritma_none(self):
        """Serangan klasik alg=none harus mental."""
        palsu = jwt.encode({"sub": "penyusup@jahat.id", "type": "access"}, key="", algorithm="none")

        with pytest.raises(security.TokenError):
            security.decode_token(palsu)

    def test_menolak_token_tanpa_subject(self):
        tanpa_sub = jwt.encode(
            {"role": "admin", "type": "access", "exp": 9999999999},
            settings.JWT_SECRET,
            algorithm=settings.JWT_ALGORITHM,
        )

        with pytest.raises(security.TokenError):
            security.decode_token(tanpa_sub)
