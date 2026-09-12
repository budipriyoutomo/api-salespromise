"""Dependency autentikasi.

Menggantikan `APIKeyMiddleware` yang lama. Dua alasan pindah ke dependency:

1. `HTTPException` yang dilempar dari `BaseHTTPMiddleware` tidak ditangkap
   exception handler FastAPI — hasilnya 500, bukan 401.
2. Sekarang ada dua jenis identitas yang berbeda kewenangannya, dan tiap route
   perlu memilih sendiri mana yang berlaku.

Pembagiannya:

- `require_api_key`   → mesin POS. `/api/sync/*` dan `/api/sales/publish`.
- `get_current_user`  → user dashboard (JWT). Endpoint baca untuk frontend.
"""

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core import security
from app.database import get_db
from app.models.api_key import ApiKey
from app.models.user import ROLE_OUTLET, User

# auto_error=False supaya pesan 401 kita sendiri yang dipakai,
# bukan pesan bawaan Starlette yang berbeda bentuk antar kasus.
_bearer = HTTPBearer(auto_error=False)

INVALID_API_KEY = "Invalid or inactive API key"
INVALID_TOKEN = "Invalid or expired token"
MISSING_CREDENTIALS = "Missing or malformed Authorization header"


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _token_from(credentials: HTTPAuthorizationCredentials) -> str:
    if credentials is None or not credentials.credentials:
        raise _unauthorized(MISSING_CREDENTIALS)
    return credentials.credentials


# ---------------------------------------------------------------------------
# API key outlet
# ---------------------------------------------------------------------------


def require_api_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> ApiKey:
    """Validasi API key outlet dan simpan outlet_code ke `request.state`.

    Lookup memakai hash — key mentah tidak pernah tersimpan di database.
    """
    token = _token_from(credentials)

    api_key = (
        db.query(ApiKey)
        .filter(
            ApiKey.key_hash == security.hash_api_key(token),
            ApiKey.is_active.is_(True),
        )
        .first()
    )

    if not api_key:
        raise _unauthorized(INVALID_API_KEY)

    request.state.outlet_code = api_key.outlet_code
    return api_key


# ---------------------------------------------------------------------------
# User dashboard (JWT)
# ---------------------------------------------------------------------------


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    token = _token_from(credentials)

    try:
        payload = security.decode_token(token)
    except security.TokenError:
        raise _unauthorized(INVALID_TOKEN)

    # Refresh token berumur panjang — jangan sampai bisa membuka endpoint data.
    if payload.get("type") != "access":
        raise _unauthorized(INVALID_TOKEN)

    user = db.query(User).filter(User.email == payload["sub"]).first()

    # User yang dihapus atau dinonaktifkan harus langsung tertolak,
    # tidak menunggu tokennya kedaluwarsa sendiri.
    if not user or not user.is_active:
        raise _unauthorized(INVALID_TOKEN)

    request.state.user = user
    return user


def require_roles(*allowed_roles):
    """Dependency factory untuk membatasi endpoint ke role tertentu."""

    def _checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role}' tidak diizinkan mengakses endpoint ini",
            )
        return user

    return _checker


# ---------------------------------------------------------------------------
# Outlet scoping
# ---------------------------------------------------------------------------


def resolve_outlet_scope(user: User, requested_outlet=None):
    """Tentukan outlet mana yang boleh dibaca user ini.

    Mengembalikan `None` yang berarti "semua outlet" — hanya untuk role yang
    memang berhak. Outlet TIDAK PERNAH diambil mentah dari query param.
    """
    if user.can_read_all_outlets():
        return requested_outlet

    if user.role == ROLE_OUTLET and not user.outlet_code:
        # Konfigurasi user tidak konsisten — gagal tertutup.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User tidak terhubung ke outlet mana pun",
        )

    if requested_outlet and requested_outlet != user.outlet_code:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tidak berhak mengakses data outlet lain",
        )

    return user.outlet_code
