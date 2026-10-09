"""Schema untuk master data product dan mapping ProductID POS."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.product_service import (
    MAX_CATEGORY_LENGTH,
    MAX_OUTLET_CODE_LENGTH,
    MAX_PRODUCT_CODE_LENGTH,
    MAX_PRODUCT_NAME_LENGTH,
    MAX_UNIT_LENGTH,
)

# Sesuai kolom NUMERIC(18, 4).
Harga = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=4)]


class ProductBrand(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str


class ProductPosMappingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    outlet_code: str
    pos_product_id: int
    pos_product_name: Optional[str] = None
    pos_product_group: Optional[str] = None
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    category: Optional[str] = None
    unit: Optional[str] = None
    price: float
    brand: Optional[ProductBrand] = None
    is_active: bool
    # Semua mapping milik produk ini, termasuk yang nonaktif.
    pos_mappings: List[ProductPosMappingResponse] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ProductListResponse(BaseModel):
    success: bool = True
    data: List[ProductResponse]


class ProductDetailResponse(BaseModel):
    success: bool = True
    data: ProductResponse


class CreateProductRequest(BaseModel):
    """Kode dinormalisasi oleh service: `p-001 ` tersimpan sebagai `P-001`."""

    code: str = Field(min_length=1, max_length=MAX_PRODUCT_CODE_LENGTH)
    name: str = Field(min_length=1, max_length=MAX_PRODUCT_NAME_LENGTH)
    category: Optional[str] = Field(default=None, max_length=MAX_CATEGORY_LENGTH)
    unit: Optional[str] = Field(default=None, max_length=MAX_UNIT_LENGTH)
    price: Harga = Decimal(0)
    brand_id: Optional[int] = Field(default=None, gt=0)
    is_active: bool = True


# Field yang boleh null di PATCH (null = dikosongkan).
_BOLEH_NULL = {"category", "unit", "brand_id"}


class UpdateProductRequest(BaseModel):
    """Hanya field yang dikirim yang diubah. Kode sengaja tidak bisa diubah."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=MAX_PRODUCT_NAME_LENGTH)
    category: Optional[str] = Field(default=None, max_length=MAX_CATEGORY_LENGTH)
    unit: Optional[str] = Field(default=None, max_length=MAX_UNIT_LENGTH)
    price: Optional[Harga] = None
    brand_id: Optional[int] = Field(default=None, gt=0)
    is_active: Optional[bool] = None

    @model_validator(mode="after")
    def field_wajib_tidak_null(self):
        dikirim = self.model_fields_set
        if not dikirim:
            raise ValueError("Isi minimal satu field")
        for nama in dikirim - _BOLEH_NULL:
            if getattr(self, nama) is None:
                raise ValueError(f"{nama} tidak boleh null")
        return self

    def changes(self) -> dict:
        return {nama: getattr(self, nama) for nama in self.model_fields_set}


class PosCandidateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    outlet_code: str
    pos_product_id: int
    pos_product_name: Optional[str] = None
    pos_product_group: Optional[str] = None
    last_sale_date: Optional[date] = None
    # Produk master yang memetakan pasangan ini secara aktif, kalau ada.
    mapped_product_id: Optional[int] = None
    mapped_product_code: Optional[str] = None


class PosCandidateListResponse(BaseModel):
    success: bool = True
    data: List[PosCandidateResponse]


class CreatePosMappingRequest(BaseModel):
    outlet_code: str = Field(min_length=1, max_length=MAX_OUTLET_CODE_LENGTH)
    pos_product_id: int = Field(gt=0)


class UpdatePosMappingRequest(BaseModel):
    is_active: bool
