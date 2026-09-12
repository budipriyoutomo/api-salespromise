"""Autentikasi user dashboard.

Terpisah dari API key outlet: endpoint di sini untuk manusia yang membuka
frontend, sedangkan `/api/sync/*` untuk mesin POS.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import settings
from app.core import security
from app.core.rate_limit import RateLimiter
from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.admin_schema import ChangePasswordRequest
from app.schemas.auth_schema import (
    AccessTokenResponse,
    LoginRequest,
    RefreshRequest,
    SimpleResponse,
    TokenResponse,
    UserResponse,
)
from app.services import user_service
from app.utils.logger import logger

router = APIRouter(prefix="/api/auth", tags=["Auth"])

# Pesan yang sama untuk email tidak terdaftar maupun password salah —
# supaya tidak bisa dipakai memetakan email mana yang ada di sistem.
INVALID_CREDENTIALS = "Email atau password salah"

# Penahan penebakan password. Dikunci per alamat pemanggil, bukan per email:
# kalau per email, penyerang justru bisa mengunci akun orang lain dengan
# sengaja mengirim password salah berkali-kali.
login_limiter = RateLimiter(
    max_attempts=settings.LOGIN_MAX_ATTEMPTS,
    window_seconds=settings.LOGIN_WINDOW_SECONDS,
)


def _alamat_pemanggil(request: Request) -> str:
    return request.client.host if request.client else "tidak-diketahui"


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def _access_token_for(user: User) -> str:
    return security.create_access_token(
        subject=user.email,
        role=user.role,
        outlet_code=user.outlet_code,
    )


@router.post("/login", response_model=TokenResponse)
def login(request: Request, payload: LoginRequest, db: Session = Depends(get_db)):
    pemanggil = _alamat_pemanggil(request)

    if not login_limiter.allow(pemanggil):
        logger.warning(f"RATE LIMIT login diblokir dari={pemanggil}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Terlalu banyak percobaan login. Coba lagi nanti.",
            headers={"Retry-After": str(settings.LOGIN_WINDOW_SECONDS)},
        )

    email = payload.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()

    if not user or not security.verify_password(payload.password, user.password_hash):
        logger.warning(f"LOGIN GAGAL email={email}")
        raise _unauthorized(INVALID_CREDENTIALS)

    if not user.is_active:
        logger.warning(f"LOGIN DITOLAK (user nonaktif) email={email}")
        raise _unauthorized(INVALID_CREDENTIALS)

    # Login berhasil mengosongkan hitungan, supaya orang yang sekadar salah
    # ketik beberapa kali tidak menyisakan blokir untuk dirinya sendiri.
    login_limiter.reset(pemanggil)

    logger.info(f"LOGIN SUKSES email={email} role={user.role}")

    return TokenResponse(
        access_token=_access_token_for(user),
        refresh_token=security.create_refresh_token(subject=user.email),
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserResponse.model_validate(user),
    )


@router.post("/refresh", response_model=AccessTokenResponse)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)):
    try:
        claims = security.decode_token(payload.refresh_token)
    except security.TokenError:
        raise _unauthorized("Refresh token tidak valid atau sudah kedaluwarsa")

    if claims.get("type") != "refresh":
        raise _unauthorized("Refresh token tidak valid atau sudah kedaluwarsa")

    user = db.query(User).filter(User.email == claims["sub"]).first()

    if not user or not user.is_active:
        raise _unauthorized("Refresh token tidak valid atau sudah kedaluwarsa")

    # Token baru dibuat dari data user terkini, bukan dari klaim lama —
    # supaya perubahan role langsung berlaku.
    return AccessTokenResponse(
        access_token=_access_token_for(user),
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)):
    return UserResponse.model_validate(user)


@router.post("/logout", response_model=SimpleResponse)
def logout(user: User = Depends(get_current_user)):
    """JWT bersifat stateless — server tidak menyimpan sesi apa pun.

    Endpoint ini hanya penanda agar frontend punya tempat memanggil saat user
    menekan logout; token benar-benar dibuang di sisi klien. Kalau nanti butuh
    pencabutan token sungguhan, perlu denylist token di Redis/DB.
    """
    logger.info(f"LOGOUT email={user.email}")
    return SimpleResponse(success=True, message="Token dibuang di sisi klien")


@router.post("/change-password", response_model=SimpleResponse)
def change_password(
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Ganti password sendiri — tersedia untuk semua role.

    Password lama tetap diminta walaupun pemanggil sudah membawa token valid:
    tanpa itu, token yang dicuri bisa dipakai mengunci pemilik akun yang sah.
    """
    if not security.verify_password(payload.current_password, user.password_hash):
        logger.warning(f"GANTI PASSWORD GAGAL (password lama salah) email={user.email}")
        raise _unauthorized("Password lama salah")

    user_service.set_password(db, user.id, payload.new_password)

    logger.info(f"PASSWORD DIGANTI email={user.email}")

    return SimpleResponse(success=True, message="Password berhasil diganti")
