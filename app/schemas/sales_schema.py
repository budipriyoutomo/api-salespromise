from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, date
from decimal import Decimal


class OrderDetailSchema(BaseModel):

    order_detail_id: int
    transaction_id: int
    product_id: int
    product_set_type: int = 0
    order_status_id: int = 2
    sale_mode: int = 1
    amount: Decimal
    price: Decimal
    retail_price: Decimal
    minimum_price: Decimal
    comment: Optional[str] = None
    order_staff_id: int = 0
    order_table_id: int = 0
    void_staff_id: int = 0


class OrderTransactionSchema(BaseModel):

    transaction_id: int
    open_staff_id: int = 0
    paid_time: Optional[datetime] = None
    paid_staff_id: int = 0
    close_time: Optional[datetime] = None
    comm_staff_id: int = 0
    other_percent_discount: Decimal = Decimal("0.00")
    other_amount_discount: Decimal = Decimal("0.0000")
    transaction_status_id: int = 1
    sale_mode: int = 1
    queue_name: Optional[str] = None
    deleted: int = 0
    no_customer: int = 1
    receipt_year: int = 0
    receipt_month: int = 0
    receipt_id: int = 0
    sale_date: Optional[date] = None
    shop_id: int = 0
    transaction_vat: Decimal = Decimal("0.000000")
    transaction_exclude_vat: Decimal = Decimal("0.0000")
    service_charge: Decimal = Decimal("0.0000")
    service_charge_vat: Decimal = Decimal("0.0000")
    other_income: Decimal = Decimal("0.0000")
    other_income_vat: Decimal = Decimal("0.0000")
    transaction_vatable: Decimal = Decimal("0.0000")
    receipt_product_retail_price: Decimal = Decimal("0.0000")
    receipt_sale_price: Decimal = Decimal("0.0000")
    receipt_pay_price: Decimal = Decimal("0.0000")
    receipt_discount: Decimal = Decimal("0.0000")
    receipt_total_amount: Decimal = Decimal("0.0000")
    vat_percent: Decimal = Decimal("0.00")
    service_charge_percent: Decimal = Decimal("0.00")
    void_staff_id: int = 0
    void_reason: Optional[str] = None
    void_time: Optional[datetime] = None
    no_print_bill_detail: int = 0
    bill_detail_reference_no: int = 0
    transaction_note: Optional[str] = None
    is_split_transaction: int = 0
    is_from_other_transaction: int = 0
    transaction_additional_type: int = 0
    reference_no: Optional[str] = None

    order_details: List[OrderDetailSchema] = []


class SyncRequestSchema(BaseModel):

    outlet: str
    transactions: List[OrderTransactionSchema]