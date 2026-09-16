"""Schema untuk endpoint administrasi: API key outlet, user dashboard, product group."""

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import ROLE_ADMIN, ROLE_MANAGER, ROLE_OUTLET
from app.services.product_group_service import MAX_PRODUCT_GROUP_LENGTH
from app.services.user_service import MIN_PASSWORD_LENGTH

# Literal, bukan str biasa: role yang salah ditolak 422 oleh validasi Pydantic
# dan ikut terdokumentasi di OpenAPI sebagai enum.
RoleName = Literal[ROLE_ADMIN, ROLE_MANAGER, ROLE_OUTLET]

Password = Field(min_length=MIN_PASSWORD_LENGTH, max_length=200)


# ---------------------------------------------------------------------------
# API key outlet
# ---------------------------------------------------------------------------


class ApiKeyResponse(BaseModel):
    """Bentuk API key yang aman dikirim — tanpa key mentah maupun hash-nya."""

    model_config = ConfigDict(from_attributes=True)

    outlet_code: str
    key_prefix: Optional[str] = None
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ApiKeyListResponse(BaseModel):
    success: bool = True
    data: List[ApiKeyResponse]


class ApiKeyDetailResponse(BaseModel):
    success: bool = True
    data: ApiKeyResponse


class CreateApiKeyRequest(BaseModel):
    outlet_code: str = Field(min_length=1, max_length=20)


class ApiKeyCreatedResponse(BaseModel):
    """Satu-satunya response yang memuat key mentah."""

    success: bool = True
    data: ApiKeyResponse
    api_key: str
    message: str = "Simpan key ini sekarang — tidak bisa dilihat lagi."


# ---------------------------------------------------------------------------
# User dashboard
# ---------------------------------------------------------------------------


class UserAdminResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    full_name: Optional[str] = None
    role: str
    outlet_code: Optional[str] = None
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class UserListResponse(BaseModel):
    success: bool = True
    data: List[UserAdminResponse]


class UserDetailResponse(BaseModel):
    success: bool = True
    data: UserAdminResponse


class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str = Password
    role: RoleName
    outlet_code: Optional[str] = Field(default=None, max_length=20)
    full_name: Optional[str] = Field(default=None, max_length=255)


class UpdateUserRequest(BaseModel):
    """Semua field opsional — hanya yang dikirim yang diubah.

    `email` sengaja tidak ada: email adalah subject JWT, mengubahnya membuat
    token yang sedang berjalan menunjuk user yang tidak ada lagi.
    """

    full_name: Optional[str] = Field(default=None, max_length=255)
    role: Optional[RoleName] = None
    outlet_code: Optional[str] = Field(default=None, max_length=20)
    is_active: Optional[bool] = None


class SetPasswordRequest(BaseModel):
    password: str = Password


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Password


# ---------------------------------------------------------------------------
# Product group mapping (Fase 6)
# ---------------------------------------------------------------------------


class ProductGroupMappingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_group: str
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ProductGroupMappingListResponse(BaseModel):
    success: bool = True
    data: List[ProductGroupMappingResponse]


class ProductGroupMappingDetailResponse(BaseModel):
    success: bool = True
    data: ProductGroupMappingResponse


class CreateProductGroupMappingRequest(BaseModel):
    """Nama dinormalisasi oleh service: `colorplate ` tersimpan sebagai `COLORPLATE`."""

    product_group: str = Field(min_length=1, max_length=MAX_PRODUCT_GROUP_LENGTH)
    is_active: bool = True


class UpdateProductGroupMappingRequest(BaseModel):
    """Hanya status aktif.

    Nama sengaja tidak bisa diubah: mengganti nama sama dengan diam-diam
    berhenti mempublish group lama. Kalau salah ketik, buat mapping baru lalu
    nonaktifkan yang lama — jejaknya tetap terlihat.
    """

    is_active: bool
