from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class UserResponse(BaseModel):
    """Bentuk user yang boleh dikirim ke frontend — tanpa password_hash."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    full_name: Optional[str] = None
    role: str
    outlet_code: Optional[str] = None
    is_active: bool

    # True berarti password akun ini masih ditentukan orang lain dan harus
    # diganti pemiliknya. Default False supaya user lama tidak ikut terkunci.
    must_change_password: bool = False


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class SimpleResponse(BaseModel):
    success: bool
    message: str
