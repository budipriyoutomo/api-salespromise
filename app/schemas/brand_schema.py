"""Schema untuk brand dan mapping outlet → brand."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.brand_service import MAX_BRAND_CODE_LENGTH, MAX_BRAND_NAME_LENGTH


class BrandResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    is_active: bool
    # Outlet yang dipetakan ke brand ini, terurut.
    outlet_codes: List[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @model_validator(mode="before")
    @classmethod
    def _outlet_codes_dari_relasi(cls, data):
        # Objek ORM membawa `outlets` (baris mapping), bukan daftar kode.
        outlets = getattr(data, "outlets", None)
        if outlets is None:
            return data
        return {
            "id": data.id,
            "code": data.code,
            "name": data.name,
            "is_active": data.is_active,
            "outlet_codes": [o.outlet_code for o in outlets],
            "created_at": data.created_at,
            "updated_at": data.updated_at,
        }


class BrandListResponse(BaseModel):
    success: bool = True
    data: List[BrandResponse]


class BrandDetailResponse(BaseModel):
    success: bool = True
    data: BrandResponse


class CreateBrandRequest(BaseModel):
    """Kode dinormalisasi oleh service: `mhr ` tersimpan sebagai `MHR`."""

    code: str = Field(min_length=1, max_length=MAX_BRAND_CODE_LENGTH)
    name: str = Field(min_length=1, max_length=MAX_BRAND_NAME_LENGTH)
    is_active: bool = True


class UpdateBrandRequest(BaseModel):
    """Kode sengaja tidak bisa diubah — dipakai sebagai filter `?brand=` di laporan."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=MAX_BRAND_NAME_LENGTH)
    is_active: Optional[bool] = None

    @model_validator(mode="after")
    def minimal_satu_field(self):
        if self.name is None and self.is_active is None:
            raise ValueError("Isi name atau is_active")
        return self


class OutletBrandResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    outlet_code: str
    # Status API key outlet.
    is_active: bool
    brand_id: Optional[int] = None
    brand_code: Optional[str] = None
    brand_name: Optional[str] = None


class OutletBrandListResponse(BaseModel):
    success: bool = True
    data: List[OutletBrandResponse]


class OutletBrandDetailResponse(BaseModel):
    success: bool = True
    data: OutletBrandResponse


class SetOutletBrandRequest(BaseModel):
    """`brand_id: null` melepas outlet dari brand-nya.

    Field wajib dikirim (boleh null) supaya body kosong tidak diam-diam
    melepas outlet.
    """

    brand_id: Optional[int] = Field(..., gt=0)
