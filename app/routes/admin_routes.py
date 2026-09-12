"""Endpoint administrasi — khusus role admin.

Dua kelompok:

- `/api/api-keys` → kredensial mesin POS
- `/api/users`    → akun login dashboard

Keduanya `require_roles(ROLE_ADMIN)`. Manager sengaja tidak diberi akses:
manager boleh membaca data semua outlet, tapi tidak mengelola kredensial.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import require_roles
from app.models.user import ROLE_ADMIN, User
from app.schemas.admin_schema import (
    ApiKeyCreatedResponse,
    ApiKeyDetailResponse,
    ApiKeyListResponse,
    ApiKeyResponse,
    CreateApiKeyRequest,
    CreateUserRequest,
    SetPasswordRequest,
    UpdateUserRequest,
    UserAdminResponse,
    UserDetailResponse,
    UserListResponse,
)
from app.services import api_key_service, user_service
from app.utils.logger import logger

require_admin = require_roles(ROLE_ADMIN)


# ---------------------------------------------------------------------------
# API key outlet
# ---------------------------------------------------------------------------

api_key_router = APIRouter(prefix="/api/api-keys", tags=["Admin - API Keys"])


@api_key_router.get("", response_model=ApiKeyListResponse)
def list_api_keys(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    rows = api_key_service.list_keys(db)

    return ApiKeyListResponse(data=[ApiKeyResponse.model_validate(row) for row in rows])


@api_key_router.post("", response_model=ApiKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
def create_api_key(
    payload: CreateApiKeyRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Buat key untuk outlet baru.

    Outlet yang sudah punya key ditolak, bukan ditimpa — menimpa berarti mesin
    POS di lapangan langsung kehilangan akses tanpa peringatan. Untuk mengganti
    key yang bocor, pakai endpoint rotate.
    """
    try:
        api_key, raw_key = api_key_service.create_key(db, payload.outlet_code)
    except api_key_service.OutletSudahPunyaKey:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Outlet '{payload.outlet_code}' sudah punya API key. Pakai rotate untuk menggantinya.",
        )

    logger.info(f"API KEY DIBUAT outlet={payload.outlet_code} oleh={admin.email}")

    return ApiKeyCreatedResponse(data=ApiKeyResponse.model_validate(api_key), api_key=raw_key)


@api_key_router.post("/{outlet_code}/rotate", response_model=ApiKeyCreatedResponse)
def rotate_api_key(
    outlet_code: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Ganti key outlet. Key lama langsung tidak berlaku."""
    try:
        api_key, raw_key = api_key_service.rotate_key(db, outlet_code)
    except api_key_service.OutletTidakDitemukan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outlet tidak ditemukan")

    logger.info(f"API KEY DIROTASI outlet={outlet_code} oleh={admin.email}")

    return ApiKeyCreatedResponse(data=ApiKeyResponse.model_validate(api_key), api_key=raw_key)


@api_key_router.post("/{outlet_code}/revoke", response_model=ApiKeyDetailResponse)
def revoke_api_key(
    outlet_code: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Nonaktifkan key. Barisnya tidak dihapus, demi jejak audit."""
    try:
        api_key = api_key_service.revoke_key(db, outlet_code)
    except api_key_service.OutletTidakDitemukan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outlet tidak ditemukan")

    logger.info(f"API KEY DIREVOKE outlet={outlet_code} oleh={admin.email}")

    return ApiKeyDetailResponse(data=ApiKeyResponse.model_validate(api_key))


# ---------------------------------------------------------------------------
# User dashboard
# ---------------------------------------------------------------------------

user_router = APIRouter(prefix="/api/users", tags=["Admin - Users"])


def _tidak_valid(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


def _terlarang(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@user_router.get("", response_model=UserListResponse)
def list_users(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    rows = user_service.list_users(db)

    return UserListResponse(data=[UserAdminResponse.model_validate(row) for row in rows])


@user_router.post("", response_model=UserDetailResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: CreateUserRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    try:
        user = user_service.create_user(
            db,
            email=payload.email,
            password=payload.password,
            role=payload.role,
            outlet_code=payload.outlet_code,
            full_name=payload.full_name,
        )
    except user_service.EmailSudahTerdaftar:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email sudah terdaftar")
    except user_service.DataTidakValid as exc:
        raise _tidak_valid(exc)

    logger.info(f"USER DIBUAT email={user.email} role={user.role} oleh={admin.email}")

    return UserDetailResponse(data=UserAdminResponse.model_validate(user))


@user_router.get("/{user_id}", response_model=UserDetailResponse)
def get_user(user_id: int, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    user = user_service.get_by_id(db, user_id)

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User tidak ditemukan")

    return UserDetailResponse(data=UserAdminResponse.model_validate(user))


@user_router.patch("/{user_id}", response_model=UserDetailResponse)
def update_user(
    user_id: int,
    payload: UpdateUserRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    perubahan = payload.model_dump(exclude_unset=True)

    try:
        user = user_service.update_user(db, user_id, actor=admin, **perubahan)
    except user_service.UserTidakDitemukan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User tidak ditemukan")
    except user_service.DataTidakValid as exc:
        raise _tidak_valid(exc)
    except user_service.MenguncilDiriSendiri as exc:
        raise _terlarang(exc)

    logger.info(f"USER DIPERBARUI id={user_id} oleh={admin.email} perubahan={list(perubahan)}")

    return UserDetailResponse(data=UserAdminResponse.model_validate(user))


@user_router.post("/{user_id}/password", response_model=UserDetailResponse)
def reset_password(
    user_id: int,
    payload: SetPasswordRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Reset password user lain. Tidak butuh password lama — ini jalur admin."""
    try:
        user = user_service.set_password(db, user_id, payload.password)
    except user_service.UserTidakDitemukan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User tidak ditemukan")
    except user_service.DataTidakValid as exc:
        raise _tidak_valid(exc)

    logger.info(f"PASSWORD DIRESET id={user_id} oleh={admin.email}")

    return UserDetailResponse(data=UserAdminResponse.model_validate(user))
