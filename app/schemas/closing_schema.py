"""Schema endpoint closing report (TODO Fase 7.6)."""

from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.sales_response import PaginationMeta

MAX_MULTIPLIER = 1000


# ---------------------------------------------------------------------------
# Mapping menu (admin)
# ---------------------------------------------------------------------------


class ClosingMenuProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    product_name: Optional[str] = None
    multiplier: int
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ClosingMenuResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    menu_code: Optional[str] = None
    menu_id: UUID
    menu_name: str
    brand_code: Optional[str] = None
    # Punya minimal satu mapping ProductID aktif.
    is_mapped: bool
    products: List[ClosingMenuProductResponse] = Field(default_factory=list)
    first_seen_at: datetime
    last_seen_at: datetime


class ClosingMenuListResponse(BaseModel):
    success: bool = True
    data: List[ClosingMenuResponse]


class ClosingMenuProductDetailResponse(BaseModel):
    success: bool = True
    data: ClosingMenuProductResponse


class CreateClosingMenuProductRequest(BaseModel):
    """Nama produk diambil server dari data penjualan terakhir ProductID ini."""

    product_id: int = Field(gt=0)
    multiplier: int = Field(default=1, gt=0, le=MAX_MULTIPLIER)
    is_active: bool = True


class UpdateClosingMenuProductRequest(BaseModel):
    """ProductID tidak bisa diganti — nonaktifkan lalu buat baris baru."""

    multiplier: Optional[int] = Field(default=None, gt=0, le=MAX_MULTIPLIER)
    is_active: Optional[bool] = None

    @model_validator(mode="after")
    def minimal_satu_field(self):
        if self.multiplier is None and self.is_active is None:
            raise ValueError("Isi multiplier atau is_active")
        return self


# ---------------------------------------------------------------------------
# Laporan (user dashboard)
# ---------------------------------------------------------------------------


class ClosingReportSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    closing_report_id: UUID
    report_date: date
    outlet_code: str
    outlet_name: str
    brand_code: str
    brand_name: str
    # Dari revisi aktif.
    sent_at: Optional[datetime] = None
    received_at: Optional[datetime] = None
    revision_count: int
    item_count: int


class ClosingReportListResponse(BaseModel):
    success: bool = True
    data: List[ClosingReportSummary]
    pagination: PaginationMeta


class ClosingReportItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    menu_id: UUID
    menu_code: Optional[str] = None
    menu_name: str
    production_date: Optional[date] = None
    sold: int
    waste: int
    adjustment: int
    compensation: int


class ClosingRevisionResponse(BaseModel):
    """Payload mentah sengaja tidak ikut — isinya sudah terwakili header & item."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    message_id: str
    sent_at: datetime
    received_at: datetime
    is_current: bool
    item_count: int


class ClosingReportDetail(ClosingReportSummary):
    items: List[ClosingReportItemResponse]
    revisions: List[ClosingRevisionResponse]


class ClosingReportDetailResponse(BaseModel):
    success: bool = True
    data: ClosingReportDetail


class ClosingComparisonMenu(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    menu_id: UUID
    menu_code: Optional[str] = None
    menu_name: str
    # Pengali mapping; kosong untuk menu yang belum dipetakan.
    multiplier: Optional[int] = None
    sold: int
    waste: int
    adjustment: int
    compensation: int


class ClosingComparisonRow(BaseModel):
    """Satu produk POS (atau satu menu yang belum dipetakan) per outlet & tanggal.

    closing_qty = Σ (sold + adjustment + compensation) × pengali menu-menunya;
    selisih = pos_qty − closing_qty (rumus pengirim).
    """

    model_config = ConfigDict(from_attributes=True)

    outlet_code: str
    production_date: date
    # Kosong = baris menu yang belum dipetakan.
    product_id: Optional[int] = None
    product_name: Optional[str] = None
    menus: List[ClosingComparisonMenu] = Field(default_factory=list)

    # Kosong kalau tidak ada menu produk ini di closing outlet/tanggal ini.
    closing_qty: Optional[int] = None
    # Kosong kalau menu belum dipetakan.
    pos_qty: Optional[float] = None
    selisih: Optional[float] = None
    # cocok | selisih | belum_dipetakan | tidak_ada_di_closing
    status: str


class ClosingComparisonResponse(BaseModel):
    success: bool = True
    data: List[ClosingComparisonRow]


# ---------------------------------------------------------------------------
# Log pesan RabbitMQ (admin)
# ---------------------------------------------------------------------------

StatusLogPesan = Literal["baru", "revisi", "revisi_lama", "duplikat", "ditolak"]


class ClosingMessageSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    received_at: datetime
    status: StatusLogPesan
    reason: Optional[str] = None
    warnings: Optional[List[str]] = None
    message_id: Optional[str] = None
    outlet_code: Optional[str] = None
    closing_report_id: Optional[UUID] = None
    report_date: Optional[date] = None
    item_count: Optional[int] = None
    revision_id: Optional[int] = None
    body_bytes: int


class ClosingMessageCounts(BaseModel):
    baru: int = 0
    revisi: int = 0
    revisi_lama: int = 0
    duplikat: int = 0
    ditolak: int = 0


class ClosingMessageListResponse(BaseModel):
    success: bool = True
    data: List[ClosingMessageSummary]
    pagination: PaginationMeta
    counts: ClosingMessageCounts


class ClosingMessageDetail(ClosingMessageSummary):
    errors: Optional[List[Dict[str, Any]]] = None
    # JSON pesan apa adanya — bisa objek atau tipe JSON lain kalau pesannya ditolak.
    payload: Optional[Any] = None
    body_text: Optional[str] = None


class ClosingMessageDetailResponse(BaseModel):
    success: bool = True
    data: ClosingMessageDetail
