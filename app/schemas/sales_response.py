"""Schema response.

Dipisah dari schema request supaya bentuk yang keluar dikunci eksplisit:
objek ORM tidak lagi dikirim mentah, dan OpenAPI-nya jadi lengkap sehingga
frontend bisa men-generate tipe dari `/openapi.json`.
"""

# `date` di-alias: PublishResponse punya field bernama `date`, dan nama field
# menutupi nama tipe saat Pydantic mengevaluasi anotasi.
from datetime import date as date_type
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class SaleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    transaction_id: int
    outlet_code: Optional[str] = None
    shop_id: int
    receipt_id: int
    reference_no: Optional[str] = None

    sale_date: Optional[date_type] = None
    paid_time: Optional[datetime] = None

    receipt_total_amount: float
    receipt_pay_price: float
    receipt_discount: float

    transaction_status_id: int
    void_staff_id: int

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class PaginationMeta(BaseModel):
    limit: int
    offset: int
    total: int
    has_more: bool


class SalesListResponse(BaseModel):
    success: bool = True
    data: List[SaleResponse]
    pagination: PaginationMeta


class ColorplateRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_name: Optional[str] = None
    outlet_code: Optional[str] = None
    sale_date: Optional[date_type] = None
    sold: float


class ColorplateListResponse(BaseModel):
    success: bool = True
    data: List[ColorplateRow]


class SyncResponse(BaseModel):
    success: bool = True
    inserted_sales: int
    inserted_items: int


class PublishResponse(BaseModel):
    success: bool = True
    message: str
    outlet: Optional[str] = None
    date: Optional[date_type] = None
    published: int = 0


class OutletResponse(BaseModel):
    outlet_code: str
    is_active: bool


class OutletListResponse(BaseModel):
    success: bool = True
    data: List[OutletResponse]


# ---------------------------------------------------------------------------
# Laporan dashboard
# ---------------------------------------------------------------------------


class SummaryData(BaseModel):
    total_transactions: int
    total_amount: float
    total_discount: float
    average_per_transaction: float


class SummaryResponse(BaseModel):
    success: bool = True
    data: SummaryData


class DailyRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sale_date: Optional[date_type] = None
    total_transactions: int
    total_amount: float


class DailyListResponse(BaseModel):
    success: bool = True
    data: List[DailyRow]


class OutletSalesRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    outlet_code: Optional[str] = None
    total_transactions: int
    total_amount: float


class OutletSalesListResponse(BaseModel):
    success: bool = True
    data: List[OutletSalesRow]


class TopProductRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: int
    product_name: Optional[str] = None
    product_group: Optional[str] = None
    total_qty: float
    total_amount: float


class TopProductListResponse(BaseModel):
    success: bool = True
    data: List[TopProductRow]


class SaleItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    order_detail_id: int
    transaction_id: int
    product_id: int
    product_group: Optional[str] = None
    product_dept: Optional[str] = None
    product_name: Optional[str] = None
    qty: float
    price: float
    retail_price: float
    order_status_id: int
    void_staff_id: int
    comment: Optional[str] = None


class SaleDetail(SaleResponse):
    items: List[SaleItemResponse] = []


class SaleDetailResponse(BaseModel):
    success: bool = True
    data: SaleDetail


class SyncStatusRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    outlet_code: Optional[str] = None
    last_sale_date: Optional[date_type] = None
    last_synced_at: Optional[datetime] = None
    total_transactions: int


class SyncStatusListResponse(BaseModel):
    success: bool = True
    data: List[SyncStatusRow]
