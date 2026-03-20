from sqlalchemy import Column, String, DateTime, Date, Integer, Text, Numeric, SmallInteger
from sqlalchemy.dialects.postgresql import SMALLINT
from app.database import Base


class Sales(Base):
    """
    SQLAlchemy model sesuai ordertransaction.sql
    """

    __tablename__ = "ordertransaction"

    id = Column("TransactionID", Integer, primary_key=True)
    shop_id = Column("ShopID", Integer, nullable=False, default=0)

    # Receipt info
    receipt_year = Column("ReceiptYear", SmallInteger, default=0)
    receipt_month = Column("ReceiptMonth", SmallInteger, default=0)
    receipt_id = Column("ReceiptID", Integer, nullable=False, default=0)
    reference_no = Column("ReferenceNo", String(20), nullable=True)
    queue_name = Column("QueueName", String(50), nullable=True)

    # Dates
    sale_date = Column("SaleDate", Date, nullable=True)
    paid_time = Column("PaidTime", DateTime, nullable=True)
    close_time = Column("CloseTime", DateTime, nullable=True)

    # Staff
    open_staff_id = Column("OpenStaffID", Integer, default=0)
    paid_staff_id = Column("PaidStaffID", Integer, default=0)
    comm_staff_id = Column("CommStaffID", Integer, default=0)
    void_staff_id = Column("VoidStaffID", Integer, default=0)
    void_reason = Column("VoidReason", Text, nullable=True)
    void_time = Column("VoidTime", DateTime, nullable=True)

    # Status & mode
    transaction_status_id = Column("TransactionStatusID", SmallInteger, nullable=False, default=1)
    sale_mode = Column("SaleMode", SmallInteger, nullable=False, default=1)
    deleted = Column("Deleted", SmallInteger, nullable=False, default=0)
    no_customer = Column("NoCustomer", SmallInteger, default=1)

    # Discount
    other_percent_discount = Column("OtherPercentDiscount", Numeric(5, 2), nullable=False, default=0)
    other_amount_discount = Column("OtherAmountDiscount", Numeric(10, 4), nullable=False, default=0)

    # Pricing
    receipt_product_retail_price = Column("ReceiptProductRetailPrice", Numeric(18, 4), nullable=False, default=0)
    receipt_sale_price = Column("ReceiptSalePrice", Numeric(18, 4), nullable=False, default=0)
    receipt_pay_price = Column("ReceiptPayPrice", Numeric(18, 4), nullable=False, default=0)
    receipt_discount = Column("ReceiptDiscount", Numeric(18, 4), nullable=False, default=0)
    receipt_total_amount = Column("ReceiptTotalAmount", Numeric(18, 4), nullable=False, default=0)

    # Tax
    vat_percent = Column("VATPercent", Numeric(5, 2), nullable=False, default=0)
    transaction_vat = Column("TransactionVAT", Numeric(18, 6), nullable=False, default=0)
    transaction_exclude_vat = Column("TransactionExcludeVAT", Numeric(18, 4), nullable=False, default=0)
    transaction_vatable = Column("TransactionVATable", Numeric(18, 4), nullable=False, default=0)

    # Service charge
    service_charge_percent = Column("ServiceChargePercent", Numeric(5, 2), nullable=False, default=0)
    service_charge = Column("ServiceCharge", Numeric(18, 4), nullable=False, default=0)
    service_charge_vat = Column("ServiceChargeVAT", Numeric(18, 4), nullable=False, default=0)

    # Other income
    other_income = Column("OtherIncome", Numeric(18, 4), nullable=False, default=0)
    other_income_vat = Column("OtherIncomeVAT", Numeric(18, 4), nullable=False, default=0)

    # Misc
    transaction_note = Column("TransactionNote", String(100), nullable=True)
    is_split_transaction = Column("IsSplitTransaction", SmallInteger, nullable=False, default=0)
    is_from_other_transaction = Column("IsFromOtherTransaction", SmallInteger, nullable=False, default=0)
    transaction_additional_type = Column("TransactionAdditionalType", SmallInteger, nullable=False, default=0)
    no_print_bill_detail = Column("NoPrintBillDetail", SmallInteger, nullable=False, default=0)
    bill_detail_reference_no = Column("BillDetailReferenceNo", Integer, nullable=False, default=0)

    # Outlet (tambahan dari arsitektur sync)
    outlet_code = Column("outlet_code", String(20), nullable=True)
    created_at = Column("created_at", DateTime, nullable=True)
    updated_at = Column("updated_at", DateTime, nullable=True)