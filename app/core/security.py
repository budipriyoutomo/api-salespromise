"""Hashing dan token.

Dipisah dari route/service supaya bisa diuji tanpa HTTP maupun database.

Dua jenis rahasia ditangani berbeda:

- **API key outlet** — di-hash SHA-256 tanpa salt. Sengaja deterministik, karena
  lookup-nya `WHERE key = hash(token)`; key-nya sendiri sudah acak 256-bit
  sehingga tidak rentan brute force seperti password buatan manusia.
- **Password user** — bcrypt dengan salt per-password.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import settings

# 72 byte adalah batas keras bcrypt; lebih dari itu diam-diam dipotong
_BCRYPT_MAX_BYTES = 72


class TokenError(Exception):
    """Token tidak valid, kedaluwarsa, atau tidak memuat klaim yang diperlukan."""


# ---------------------------------------------------------------------------
# API key outlet
# ---------------------------------------------------------------------------


def generate_api_key() -> str:
    """Key acak untuk satu outlet. Hanya ditampilkan sekali saat dibuat."""
    return secrets.token_urlsafe(32)


def hash_api_key(raw_key: str) -> str:
    """SHA-256 hex.

    Harus identik dengan `encode(sha256(key::bytea), 'hex')` di PostgreSQL,
    karena migrasi 003 memakai fungsi itu untuk mem-backfill data lama.
    """
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def api_key_prefix(raw_key: str, length: int = 8) -> str:
    """Potongan awal key, untuk ditampilkan di CLI tanpa membocorkan keseluruhannya."""
    return raw_key[:length]


# ---------------------------------------------------------------------------
# Password user
# ---------------------------------------------------------------------------


def hash_password(raw_password: str) -> str:
    password_bytes = raw_password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(raw_password: str, password_hash: str) -> bool:
    if not password_hash:
        return False

    try:
        return bcrypt.checkpw(
            raw_password.encode("utf-8")[:_BCRYPT_MAX_BYTES],
            password_hash.encode("utf-8"),
        )
    except (ValueError, TypeError):
        # hash rusak / bukan format bcrypt — perlakukan seperti password salah
        return False


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------


def _encode(payload: dict, expires_delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        **payload,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_access_token(subject: str, role: str, outlet_code=None, expires_delta=None) -> str:
    return _encode(
        {
            "sub": subject,
            "role": role,
            "outlet_code": outlet_code,
            "type": "access",
        },
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(subject: str, expires_delta=None) -> str:
    return _encode(
        {
            "sub": subject,
            "type": "refresh",
        },
        expires_delta or timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )


def decode_token(token: str) -> dict:
    """Kembalikan payload token, atau lempar `TokenError`.

    `algorithms` sengaja dikunci ke satu algoritma — tanpa itu token ber-`alg: none`
    atau yang ditandatangani algoritma lain bisa lolos.
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc

    if not payload.get("sub"):
        raise TokenError("Token tidak memuat subject")

    return payload
