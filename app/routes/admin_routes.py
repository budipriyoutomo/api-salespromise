"""Endpoint administrasi — khusus role admin.

Tiga kelompok:

- `/api/api-keys`       → kredensial mesin POS
- `/api/users`          → akun login dashboard
- `/api/product-groups` → group yang dipublish ke RabbitMQ
- `/api/product-menus`  → menu satuan yang dipublish ke RabbitMQ

Semuanya `require_roles(ROLE_ADMIN)`. Manager sengaja tidak diberi akses:
manager boleh membaca data semua outlet, tapi tidak mengelola kredensial
maupun kontrak event ke consumer.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
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
    CreateProductGroupMappingRequest,
    CreateProductMenuColorplateRequest,
    CreateProductMenuMappingRequest,
    CreateUserRequest,
    PlatecolorListResponse,
    ProductGroupMappingDetailResponse,
    ProductGroupMappingListResponse,
    ProductGroupMappingResponse,
    ProductMenuCandidate,
    ProductMenuCandidateListResponse,
    ProductMenuColorplateDetailResponse,
    ProductMenuColorplateResponse,
    ProductMenuMappingDetailResponse,
    ProductMenuMappingListResponse,
    ProductMenuMappingResponse,
    SetPasswordRequest,
    UpdateProductGroupMappingRequest,
    UpdateProductMenuColorplateRequest,
    UpdateProductMenuMappingRequest,
    UpdateUserRequest,
    UserAdminResponse,
    UserDetailResponse,
    UserListResponse,
)
from app.services import api_key_service, product_group_service, product_menu_service, user_service
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


# ---------------------------------------------------------------------------
# Product group mapping (Fase 6)
# ---------------------------------------------------------------------------
#
# Tidak ada endpoint DELETE, dan itu disengaja: group dimatikan lewat PATCH
# `is_active`, barisnya tetap ada sebagai jejak apa saja yang pernah dipublish.

product_group_router = APIRouter(prefix="/api/product-groups", tags=["Admin - Product Groups"])


@product_group_router.get("", response_model=ProductGroupMappingListResponse)
def list_product_groups(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """Semua mapping, termasuk yang nonaktif."""
    rows = product_group_service.list_mappings(db)

    return ProductGroupMappingListResponse(data=[ProductGroupMappingResponse.model_validate(row) for row in rows])


@product_group_router.post("", response_model=ProductGroupMappingDetailResponse, status_code=status.HTTP_201_CREATED)
def create_product_group(
    payload: CreateProductGroupMappingRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Tambah group yang ikut dipublish ke RabbitMQ.

    Group yang sudah terdaftar ditolak 409, termasuk yang sedang nonaktif —
    aktifkan kembali lewat PATCH, jangan dibuat ulang.
    """
    try:
        row = product_group_service.create_mapping(db, payload.product_group, is_active=payload.is_active)
    except product_group_service.GroupSudahAda as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Product group '{exc}' sudah terdaftar. Aktifkan lewat PATCH kalau sedang nonaktif.",
        )
    except product_group_service.DataTidakValid as exc:
        raise _tidak_valid(exc)

    logger.info(f"PRODUCT GROUP DIBUAT group={row.product_group!r} aktif={row.is_active} oleh={admin.email}")

    return ProductGroupMappingDetailResponse(data=ProductGroupMappingResponse.model_validate(row))


@product_group_router.patch("/{mapping_id}", response_model=ProductGroupMappingDetailResponse)
def update_product_group(
    mapping_id: int,
    payload: UpdateProductGroupMappingRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Aktifkan / nonaktifkan group. Berlaku pada publish berikutnya."""
    try:
        row = product_group_service.set_active(db, mapping_id, payload.is_active)
    except product_group_service.GroupTidakDitemukan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product group tidak ditemukan")

    logger.info(f"PRODUCT GROUP DIUBAH group={row.product_group!r} aktif={row.is_active} oleh={admin.email}")

    return ProductGroupMappingDetailResponse(data=ProductGroupMappingResponse.model_validate(row))


# ---------------------------------------------------------------------------
# Product menu mapping — publish per menu
# ---------------------------------------------------------------------------
#
# Publish hanya mengirim format colorplate. Menu di sini ikut terhitung lewat
# konversi ke warna (`/{id}/colorplates`): qty × multiplier. Sama seperti
# group: tidak ada DELETE, menu & konversi dimatikan lewat PATCH `is_active`.

product_menu_router = APIRouter(prefix="/api/product-menus", tags=["Admin - Product Menus"])


@product_menu_router.get("", response_model=ProductMenuMappingListResponse)
def list_product_menus(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """Semua mapping menu, termasuk yang nonaktif."""
    rows = product_menu_service.list_mappings(db)

    return ProductMenuMappingListResponse(data=[ProductMenuMappingResponse.model_validate(row) for row in rows])


@product_menu_router.get("/candidates", response_model=ProductMenuCandidateListResponse)
def list_product_menu_candidates(
    outlet: Optional[str] = Query(None, description="Batasi ke menu yang pernah terjual di outlet ini"),
    product_group: Optional[str] = Query(None, description="Batasi ke satu group (tidak peka huruf besar/kecil)"),
    q: Optional[str] = Query(None, max_length=255, description="Cari nama menu atau ProductID"),
    limit: int = Query(
        product_menu_service.CANDIDATE_DEFAULT_LIMIT,
        ge=1,
        le=product_menu_service.CANDIDATE_MAX_LIMIT,
    ),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Menu yang pernah muncul di data penjualan — sumber pilihan mapping menu.

    Filter `outlet` hanya mempersempit daftar pilihan; mapping yang dibuat
    tetap berlaku untuk semua outlet.
    """
    rows = product_menu_service.list_candidates(
        db, outlet=outlet, product_group=product_group, q=q, limit=limit
    )

    return ProductMenuCandidateListResponse(data=[ProductMenuCandidate.model_validate(row) for row in rows])


@product_menu_router.get("/platecolors", response_model=PlatecolorListResponse)
def list_platecolors(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """Warna COLORPLATE yang ada di data penjualan — pilihan tujuan konversi menu."""
    return PlatecolorListResponse(data=product_menu_service.list_colors(db))


@product_menu_router.post("", response_model=ProductMenuMappingDetailResponse, status_code=status.HTTP_201_CREATED)
def create_product_menu(
    payload: CreateProductMenuMappingRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Tambah menu yang ikut dipublish, terlepas dari status group-nya."""
    try:
        row = product_menu_service.create_mapping(db, payload.product_id, is_active=payload.is_active)
    except product_menu_service.MenuSudahAda:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Menu ProductID {payload.product_id} sudah terdaftar. Aktifkan lewat PATCH kalau sedang nonaktif.",
        )
    except product_menu_service.MenuTidakAdaDiData:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"ProductID {payload.product_id} tidak ditemukan di data penjualan.",
        )

    logger.info(
        f"PRODUCT MENU DIBUAT product_id={row.product_id} nama={row.product_name!r} "
        f"group={row.product_group!r} aktif={row.is_active} oleh={admin.email}"
    )

    return ProductMenuMappingDetailResponse(data=ProductMenuMappingResponse.model_validate(row))


@product_menu_router.patch("/{mapping_id}", response_model=ProductMenuMappingDetailResponse)
def update_product_menu(
    mapping_id: int,
    payload: UpdateProductMenuMappingRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Aktifkan / nonaktifkan menu. Berlaku pada publish berikutnya."""
    try:
        row = product_menu_service.set_active(db, mapping_id, payload.is_active)
    except product_menu_service.MenuTidakDitemukan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Menu tidak ditemukan")

    logger.info(f"PRODUCT MENU DIUBAH product_id={row.product_id} aktif={row.is_active} oleh={admin.email}")

    return ProductMenuMappingDetailResponse(data=ProductMenuMappingResponse.model_validate(row))


@product_menu_router.post(
    "/{mapping_id}/colorplates",
    response_model=ProductMenuColorplateDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_product_menu_colorplate(
    mapping_id: int,
    payload: CreateProductMenuColorplateRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Hitung menu ini sebagai `multiplier` × warna colorplate saat publish."""
    try:
        row = product_menu_service.add_colorplate(
            db, mapping_id, payload.platecolor, payload.multiplier, is_active=payload.is_active
        )
    except product_menu_service.MenuTidakDitemukan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Menu tidak ditemukan")
    except product_menu_service.WarnaTidakDikenal:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Warna {payload.platecolor!r} tidak ada di data COLORPLATE.",
        )
    except product_menu_service.WarnaSudahAda as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Menu ini sudah punya konversi ke {e.args[0]!r}. Ubah lewat PATCH.",
        )

    logger.info(
        f"PRODUCT MENU COLORPLATE DIBUAT menu_id={mapping_id} warna={row.platecolor!r} "
        f"x{row.multiplier} aktif={row.is_active} oleh={admin.email}"
    )

    return ProductMenuColorplateDetailResponse(data=ProductMenuColorplateResponse.model_validate(row))


@product_menu_router.patch(
    "/{mapping_id}/colorplates/{colorplate_id}",
    response_model=ProductMenuColorplateDetailResponse,
)
def update_product_menu_colorplate(
    mapping_id: int,
    colorplate_id: int,
    payload: UpdateProductMenuColorplateRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Ubah multiplier / aktifkan / nonaktifkan konversi. Berlaku pada publish berikutnya."""
    try:
        row = product_menu_service.update_colorplate(
            db, mapping_id, colorplate_id, multiplier=payload.multiplier, is_active=payload.is_active
        )
    except product_menu_service.KonversiTidakDitemukan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Konversi warna tidak ditemukan")

    logger.info(
        f"PRODUCT MENU COLORPLATE DIUBAH menu_id={mapping_id} warna={row.platecolor!r} "
        f"x{row.multiplier} aktif={row.is_active} oleh={admin.email}"
    )

    return ProductMenuColorplateDetailResponse(data=ProductMenuColorplateResponse.model_validate(row))
