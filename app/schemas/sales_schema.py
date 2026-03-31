from pydantic import BaseModel, UUID4
from typing import List, Optional
from datetime import datetime, date
from pydantic import BaseModel
from typing import Optional
from datetime import date
 

class SalesItemSchema(BaseModel):
    id: int
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
 


class SalesSchema(BaseModel):
    id: int

    outlet_code: Optional[str] = None  

    invoice_number: Optional[str] = None
    sale_date: Optional[date] = None
    paid_time: Optional[datetime] = None
    close_time: Optional[datetime] = None
    trx_date: Optional[datetime] = None

    shop_id: int = 0

    transaction_status_id: int = 1
    sale_mode: int = 1
    no_customer: int = 1
    deleted: int = 0
 
    # Pricing
    receipt_product_retail_price: float = 0.0
    receipt_sale_price: float = 0.0
    receipt_pay_price: float = 0.0
    receipt_discount: float = 0.0
    receipt_total_amount: float = 0.0
    other_percent_discount: float = 0.0
    other_amount_discount: float = 0.0

    # Tax & Service
    vat_percent: float = 0.0
    transaction_vat: float = 0.0
    transaction_exclude_vat: float = 0.0
    transaction_vatable: float = 0.0
    service_charge_percent: float = 0.0
    service_charge: float = 0.0
    service_charge_vat: float = 0.0
    other_income: float = 0.0
    other_income_vat: float = 0.0

    # Void
    void_staff_id: int = 0
    void_reason: Optional[str] = None
    void_time: Optional[datetime] = None

    # Misc
    transaction_note: Optional[str] = None
    queue_name: Optional[str] = None
    reference_no: Optional[str] = None
    is_split_transaction: int = 0
    is_from_other_transaction: int = 0

    # 🔥 RELATION
    items: List[SalesItemSchema] = []

    @property
    def total(self) -> float:
        return self.receipt_total_amount


class SyncRequestSchema(BaseModel):
    outlet: str
    sales: List[SalesSchema]