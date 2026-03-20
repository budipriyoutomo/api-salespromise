from pydantic import BaseModel, UUID4
from typing import List, Optional
from datetime import datetime, date


class SalesItemSchema(BaseModel):
    """
    Sesuai tabel orderdetail.sql
    """
    id: int                          # OrderDetailID
    product_id: int                  # ProductID
    product_set_type: int = 0        # ProductSetType
    order_status_id: int = 2         # OrderStatusID
    sale_mode: int = 1               # SaleMode
    qty: float                       # Amount
    price: float                     # Price
    retail_price: float = 0.0        # RetailPrice
    minimum_price: float = 0.0       # MinimumPrice
    subtotal: float                  # computed / derived
    comment: Optional[str] = None    # Comment
    order_staff_id: int = 0          # OrderStaffID
    order_table_id: int = 0          # OrderTableID
    void_staff_id: int = 0           # VoidStaffID


class SalesSchema(BaseModel):
    """
    Sesuai tabel ordertransaction.sql
    """
    id: int                                         # TransactionID
    invoice_number: Optional[str] = None            # ReferenceNo / ReceiptID
    sale_date: Optional[date] = None                # SaleDate
    paid_time: Optional[datetime] = None            # PaidTime
    close_time: Optional[datetime] = None           # CloseTime
    trx_date: Optional[datetime] = None             # PaidTime / CloseTime alias

    shop_id: int = 0                                # ShopID
    transaction_status_id: int = 1                  # TransactionStatusID
    sale_mode: int = 1                              # SaleMode
    no_customer: int = 1                            # NoCustomer
    deleted: int = 0                                # Deleted

    # Pricing
    receipt_product_retail_price: float = 0.0       # ReceiptProductRetailPrice
    receipt_sale_price: float = 0.0                 # ReceiptSalePrice
    receipt_pay_price: float = 0.0                  # ReceiptPayPrice
    receipt_discount: float = 0.0                   # ReceiptDiscount
    receipt_total_amount: float = 0.0               # ReceiptTotalAmount
    other_percent_discount: float = 0.0             # OtherPercentDiscount
    other_amount_discount: float = 0.0              # OtherAmountDiscount

    # Tax & Service
    vat_percent: float = 0.0                        # VATPercent
    transaction_vat: float = 0.0                    # TransactionVAT
    transaction_exclude_vat: float = 0.0            # TransactionExcludeVAT
    transaction_vatable: float = 0.0                # TransactionVATable
    service_charge_percent: float = 0.0             # ServiceChargePercent
    service_charge: float = 0.0                     # ServiceCharge
    service_charge_vat: float = 0.0                 # ServiceChargeVAT
    other_income: float = 0.0                       # OtherIncome
    other_income_vat: float = 0.0                   # OtherIncomeVAT

    # Void
    void_staff_id: int = 0                          # VoidStaffID
    void_reason: Optional[str] = None               # VoidReason
    void_time: Optional[datetime] = None            # VoidTime

    # Misc
    transaction_note: Optional[str] = None          # TransactionNote
    queue_name: Optional[str] = None                # QueueName
    reference_no: Optional[str] = None              # ReferenceNo
    is_split_transaction: int = 0                   # IsSplitTransaction
    is_from_other_transaction: int = 0              # IsFromOtherTransaction

    items: List[SalesItemSchema] = []

    @property
    def total(self) -> float:
        """Alias untuk receipt_total_amount agar kompatibel dengan service lama."""
        return self.receipt_total_amount


class SyncRequestSchema(BaseModel):
    outlet: str
    sales: List[SalesSchema]