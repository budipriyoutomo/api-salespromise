"""Schema untuk master data product dan mapping ProductID POS."""

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.product_service import (
    IMPORT_MAX_ITEMS,
    MAX_CATEGORY_LENGTH,
    MAX_OUTLET_CODE_LENGTH,
    MAX_PRODUCT_CODE_LENGTH,
    MAX_PRODUCT_NAME_LENGTH,
    MAX_SUBCATEGORY_LENGTH,
)


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
    # Tampil sebagai "ProductID".
    code: str
    # Kosong hanya untuk produk dari sebelum migrasi 015.
    product_code: Optional[str] = None
    name: str
    category: Optional[str] = None
    subcategory: Optional[str] = None
    # Kosong hanya untuk produk dari sebelum brand diwajibkan.
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
    """Wajib: ProductID (`code`), Product Code, nama, brand.

    `code` & `product_code` dinormalisasi oleh service: `p-001 ` → `P-001`.
    """

    code: str = Field(min_length=1, max_length=MAX_PRODUCT_CODE_LENGTH)
    product_code: str = Field(min_length=1, max_length=MAX_PRODUCT_CODE_LENGTH)
    name: str = Field(min_length=1, max_length=MAX_PRODUCT_NAME_LENGTH)
    brand_id: int = Field(gt=0)
    category: Optional[str] = Field(default=None, max_length=MAX_CATEGORY_LENGTH)
    subcategory: Optional[str] = Field(default=None, max_length=MAX_SUBCATEGORY_LENGTH)
    is_active: bool = True


# Field yang boleh null di PATCH (null = dikosongkan).
_BOLEH_NULL = {"category", "subcategory"}


class UpdateProductRequest(BaseModel):
    """Hanya field yang dikirim yang diubah. ProductID (`code`) tidak bisa diubah."""

    product_code: Optional[str] = Field(default=None, min_length=1, max_length=MAX_PRODUCT_CODE_LENGTH)
    name: Optional[str] = Field(default=None, min_length=1, max_length=MAX_PRODUCT_NAME_LENGTH)
    category: Optional[str] = Field(default=None, max_length=MAX_CATEGORY_LENGTH)
    subcategory: Optional[str] = Field(default=None, max_length=MAX_SUBCATEGORY_LENGTH)
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


# ---------------------------------------------------------------------------
# Impor dari transaksi POS
# ---------------------------------------------------------------------------


class ImportCandidateResponse(BaseModel):
    """Satu (brand, ProductID POS) yang masih punya outlet belum dipetakan."""

    model_config = ConfigDict(from_attributes=True)

    brand_id: int
    brand_code: str
    brand_name: str
    pos_product_id: int
    pos_product_name: Optional[str] = None
    pos_product_group: Optional[str] = None
    pos_product_dept: Optional[str] = None
    last_sale_date: Optional[date] = None
    outlet_codes: List[str]
    unmapped_outlet_codes: List[str]
    # ProductID & Product Code produk yang akan dibuat: BRAND-ProductID.
    proposed_code: str
    # baru | tambah_outlet | bentrok
    status: str
    existing_product_id: Optional[int] = None
    reason: Optional[str] = None


class ImportCandidateListResponse(BaseModel):
    success: bool = True
    data: List[ImportCandidateResponse]


class ImportItem(BaseModel):
    brand_id: int = Field(gt=0)
    pos_product_id: int = Field(gt=0)


class ImportProductsRequest(BaseModel):
    items: List[ImportItem] = Field(min_length=1, max_length=IMPORT_MAX_ITEMS)


class ImportResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    brand_id: int
    pos_product_id: int
    # dibuat | ditambahkan | dilewati
    status: str
    product_id: Optional[int] = None
    code: Optional[str] = None
    mapped_outlets: List[str] = Field(default_factory=list)
    reason: Optional[str] = None


class ImportSummary(BaseModel):
    created: int
    added: int
    skipped: int
    results: List[ImportResult]


class ImportProductsResponse(BaseModel):
    success: bool = True
    data: ImportSummary
