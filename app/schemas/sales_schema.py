from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime, date

class SalesItemSchema(BaseModel):
    order_detail_id: int
    transaction_id: int

    sale_date: date

    product_id: int
    product_group: Optional[str] = None
    product_dept: Optional[str] = None
    product_name: Optional[str] = None

    product_set_type: int = 0
    order_status_id: int = 2
    sale_mode: int = 1

    qty: float
    price: float
    retail_price: float = 0.0
    minimum_price: float = 0.0

    comment: Optional[str] = None
    order_staff_id: int = 0
    order_table_id: int = 0
    void_staff_id: int = 0

    class Config:
        from_attributes = True  # 🔥 penting untuk ORM



class SalesSchema(BaseModel):
    transaction_id: int  # 🔥 sesuai DB

    shop_id: int = 0

    # Receipt
    receipt_year: int = 0
    receipt_month: int = 0
    receipt_id: int = 0

    reference_no: Optional[str] = None
    queue_name: Optional[str] = None

    # Dates
    sale_date: Optional[date] = None
    paid_time: Optional[datetime] = None
    close_time: Optional[datetime] = None

    # Staff
    open_staff_id: int = 0
    paid_staff_id: int = 0
    comm_staff_id: int = 0
    void_staff_id: int = 0
    void_reason: Optional[str] = None
    void_time: Optional[datetime] = None

    # Status
    transaction_status_id: int = 1
    sale_mode: int = 1
    deleted: int = 0
    no_customer: int = 1

    # Discount
    other_percent_discount: float = 0.0
    other_amount_discount: float = 0.0

    # Pricing
    receipt_product_retail_price: float = 0.0
    receipt_sale_price: float = 0.0
    receipt_pay_price: float = 0.0
    receipt_discount: float = 0.0
    receipt_total_amount: float = 0.0

    # Tax
    vat_percent: float = 0.0
    transaction_vat: float = 0.0
    transaction_exclude_vat: float = 0.0
    transaction_vatable: float = 0.0

    # Service
    service_charge_percent: float = 0.0
    service_charge: float = 0.0
    service_charge_vat: float = 0.0

    # Other
    other_income: float = 0.0
    other_income_vat: float = 0.0

    # Misc
    transaction_note: Optional[str] = None
    is_split_transaction: int = 0
    is_from_other_transaction: int = 0
 

    # 🔥 RELATION
    items: List[SalesItemSchema] = Field(default_factory=list)

    class Config:
        from_attributes = True

class SyncRequestSchema(BaseModel):
    outlet: str
    sales: List[SalesSchema]
