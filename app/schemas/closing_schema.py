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


class ClosingComparisonProduct(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: int
    product_name: Optional[str] = None
    # Group POS dari penjualan di rentang ini; kosong kalau tidak terjual.
    product_group: Optional[str] = None
    multiplier: int
    # Dipetakan ke salah satu menu colorplate.
    is_mapped: bool


class ClosingComparisonRow(BaseModel):
    """Satu menu colorplate per outlet & tanggal produksi, berdampingan dengan POS.

    pos_qty = Σ qty orderdetail (outlet & tanggal sama) dari ProductID yang
    dipetakan ke menu ini; kosong kalau menu belum dipetakan.

    Baris tanpa menu (`menu_id` & angka colorplate kosong) = produk POS yang
    terjual tetapi qty-nya tidak tampil di baris menu mana pun (belum
    dipetakan, bukan colorplate, atau menunya tidak ada di colorplate).
    """

    model_config = ConfigDict(from_attributes=True)

    outlet_code: str
    production_date: date
    menu_id: Optional[UUID] = None
    menu_code: Optional[str] = None
    menu_name: Optional[str] = None

    sold: Optional[int] = None
    waste: Optional[int] = None
    adjustment: Optional[int] = None
    compensation: Optional[int] = None

    # Mapping aktif; kosong = belum dipetakan.
    products: List[ClosingComparisonProduct] = Field(default_factory=list)
    pos_qty: Optional[float] = None


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


# ---------------------------------------------------------------------------
# Kirim rekap closing ke API eksternal (admin, TODO Fase 8)
# ---------------------------------------------------------------------------

StatusKirim = Literal["mengirim", "terkirim", "duplikat", "gagal"]


class SendClosingExportRequest(BaseModel):
    outlet_code: str = Field(min_length=1, max_length=20)
    production_date: date


class ClosingExportSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    outlet_code: str
    production_date: date
    sequence: int
    message_id: UUID
    status: StatusKirim
    attempts: int
    http_status: Optional[int] = None
    error: Optional[str] = None
    item_count: int
    sent_by: str
    created_at: datetime
    started_at: datetime
    finished_at: Optional[datetime] = None


class ClosingExportDetail(ClosingExportSummary):
    # Body persis seperti yang dikirim ke API tujuan.
    payload: Dict[str, Any]
    response_body: Optional[str] = None


class ClosingExportListResponse(BaseModel):
    success: bool = True
    data: List[ClosingExportSummary]
    pagination: PaginationMeta


class ClosingExportDetailResponse(BaseModel):
    success: bool = True
    data: ClosingExportDetail


class ClosingExportUnmappedMenu(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    menu_id: UUID
    menu_code: Optional[str] = None
    menu_name: Optional[str] = None


class ClosingExportDuplicateProduct(BaseModel):
    """ProductID yang dipetakan ke lebih dari satu menu di outlet + tanggal ini."""

    model_config = ConfigDict(from_attributes=True)

    product_id: int
    product_name: Optional[str] = None
    menus: List[str]


class ClosingExportStatus(BaseModel):
    """Status kirim satu outlet × tanggal produksi.

    `status` dibanding kiriman terakhir yang sampai: belum_dikirim / terkirim /
    perlu_kirim_ulang (rekap berubah sejak terkirim). `can_send` false kalau
    diblokir atau kiriman terakhir masih `mengirim`.
    """

    model_config = ConfigDict(from_attributes=True)

    outlet_code: str
    production_date: date
    status: Literal["belum_dikirim", "terkirim", "perlu_kirim_ulang"]
    can_send: bool
    item_count: int
    total_sold: float
    menu_belum_dipetakan: List[ClosingExportUnmappedMenu]
    produk_dobel: List[ClosingExportDuplicateProduct]
    last_attempt: Optional[ClosingExportSummary] = None
    last_sent: Optional[ClosingExportSummary] = None


class ClosingExportStatusResponse(BaseModel):
    success: bool = True
    data: List[ClosingExportStatus]
