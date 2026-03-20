from sqlalchemy import Column, String, DateTime, Numeric, SmallInteger, Integer, Date, Text, TinyInteger
from sqlalchemy.orm import relationship
from app.database import Base


class OrderTransaction(Base):

    __tablename__ = "ordertransaction"

    transaction_id = Column("TransactionID", Integer, primary_key=True, default=0)
    open_staff_id = Column("OpenStaffID", Integer, default=0)
    paid_time = Column("PaidTime", DateTime, nullable=True)
    paid_staff_id = Column("PaidStaffID", Integer, default=0)
    close_time = Column("CloseTime", DateTime, nullable=True)
    comm_staff_id = Column("CommStaffID", Integer, default=0)
    other_percent_discount = Column("OtherPercentDiscount", Numeric(5, 2), nullable=False, default=0)
    other_amount_discount = Column("OtherAmountDiscount", Numeric(10, 4), nullable=False, default=0)
    transaction_status_id = Column("TransactionStatusID", SmallInteger, nullable=False, default=1)
    sale_mode = Column("SaleMode", Integer, nullable=False, default=1)
    queue_name = Column("QueueName", String(50), nullable=True)
    deleted = Column("Deleted", Integer, nullable=False, default=0)
    no_customer = Column("NoCustomer", SmallInteger, nullable=True, default=1)
    receipt_year = Column("ReceiptYear", SmallInteger, nullable=True, default=0)
    receipt_month = Column("ReceiptMonth", Integer, nullable=True, default=0)
    receipt_id = Column("ReceiptID", Integer, nullable=False, default=0)
    sale_date = Column("SaleDate", Date, nullable=True)
    shop_id = Column("ShopID", Integer, nullable=False, default=0)
    transaction_vat = Column("TransactionVAT", Numeric(18, 6), nullable=False, default=0)
    transaction_exclude_vat = Column("TransactionExcludeVAT", Numeric(18, 4), nullable=False, default=0)
    service_charge = Column("ServiceCharge", Numeric(18, 4), nullable=False, default=0)
    service_charge_vat = Column("ServiceChargeVAT", Numeric(18, 4), nullable=False, default=0)
    other_income = Column("OtherIncome", Numeric(18, 4), nullable=False, default=0)
    other_income_vat = Column("OtherIncomeVAT", Numeric(18, 4), nullable=False, default=0)
    transaction_vatable = Column("TransactionVATable", Numeric(18, 4), nullable=False, default=0)
    receipt_product_retail_price = Column("ReceiptProductRetailPrice", Numeric(18, 4), nullable=False, default=0)
    receipt_sale_price = Column("ReceiptSalePrice", Numeric(18, 4), nullable=False, default=0)
    receipt_pay_price = Column("ReceiptPayPrice", Numeric(18, 4), nullable=False, default=0)
    receipt_discount = Column("ReceiptDiscount", Numeric(18, 4), nullable=False, default=0)
    receipt_total_amount = Column("ReceiptTotalAmount", Numeric(18, 4), nullable=False, default=0)
    vat_percent = Column("VATPercent", Numeric(5, 2), nullable=False, default=0)
    service_charge_percent = Column("ServiceChargePercent", Numeric(5, 2), nullable=False, default=0)
    void_staff_id = Column("VoidStaffID", Integer, nullable=False, default=0)
    void_reason = Column("VoidReason", Text, nullable=True)
    void_time = Column("VoidTime", DateTime, nullable=True)
    no_print_bill_detail = Column("NoPrintBillDetail", Integer, nullable=False, default=0)
    bill_detail_reference_no = Column("BillDetailReferenceNo", Integer, nullable=False, default=0)
    transaction_note = Column("TransactionNote", String(100), nullable=True)
    is_split_transaction = Column("IsSplitTransaction", Integer, nullable=False, default=0)
    is_from_other_transaction = Column("IsFromOtherTransaction", Integer, nullable=False, default=0)
    transaction_additional_type = Column("TransactionAdditionalType", Integer, nullable=False, default=0)
    reference_no = Column("ReferenceNo", String(20), nullable=True)

    order_details = relationship("OrderDetail", back_populates="transaction")
