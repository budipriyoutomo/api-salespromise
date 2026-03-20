from sqlalchemy.dialects.mysql import insert
from sqlalchemy.orm import Session
from datetime import datetime

from app.models.order_transaction import OrderTransaction
from app.models.order_detail import OrderDetail
from app.utils.logger import logger


class SalesService:

    @staticmethod
    def sync_sales(db: Session, outlet: str, transactions: list):

        inserted = 0

        try:

            for trx in transactions:

                trx_stmt = insert(OrderTransaction).values(
                    TransactionID=trx.transaction_id,
                    OpenStaffID=trx.open_staff_id,
                    PaidTime=trx.paid_time,
                    PaidStaffID=trx.paid_staff_id,
                    CloseTime=trx.close_time,
                    CommStaffID=trx.comm_staff_id,
                    OtherPercentDiscount=trx.other_percent_discount,
                    OtherAmountDiscount=trx.other_amount_discount,
                    TransactionStatusID=trx.transaction_status_id,
                    SaleMode=trx.sale_mode,
                    QueueName=trx.queue_name,
                    Deleted=trx.deleted,
                    NoCustomer=trx.no_customer,
                    ReceiptYear=trx.receipt_year,
                    ReceiptMonth=trx.receipt_month,
                    ReceiptID=trx.receipt_id,
                    SaleDate=trx.sale_date,
                    ShopID=trx.shop_id,
                    TransactionVAT=trx.transaction_vat,
                    TransactionExcludeVAT=trx.transaction_exclude_vat,
                    ServiceCharge=trx.service_charge,
                    ServiceChargeVAT=trx.service_charge_vat,
                    OtherIncome=trx.other_income,
                    OtherIncomeVAT=trx.other_income_vat,
                    TransactionVATable=trx.transaction_vatable,
                    ReceiptProductRetailPrice=trx.receipt_product_retail_price,
                    ReceiptSalePrice=trx.receipt_sale_price,
                    ReceiptPayPrice=trx.receipt_pay_price,
                    ReceiptDiscount=trx.receipt_discount,
                    ReceiptTotalAmount=trx.receipt_total_amount,
                    VATPercent=trx.vat_percent,
                    ServiceChargePercent=trx.service_charge_percent,
                    VoidStaffID=trx.void_staff_id,
                    VoidReason=trx.void_reason,
                    VoidTime=trx.void_time,
                    NoPrintBillDetail=trx.no_print_bill_detail,
                    BillDetailReferenceNo=trx.bill_detail_reference_no,
                    TransactionNote=trx.transaction_note,
                    IsSplitTransaction=trx.is_split_transaction,
                    IsFromOtherTransaction=trx.is_from_other_transaction,
                    TransactionAdditionalType=trx.transaction_additional_type,
                    ReferenceNo=trx.reference_no
                )

                trx_stmt = trx_stmt.on_duplicate_key_update(
                    PaidTime=trx.paid_time,
                    CloseTime=trx.close_time,
                    TransactionStatusID=trx.transaction_status_id,
                    OtherPercentDiscount=trx.other_percent_discount,
                    OtherAmountDiscount=trx.other_amount_discount,
                    ReceiptTotalAmount=trx.receipt_total_amount,
                    ReceiptPayPrice=trx.receipt_pay_price,
                    ReceiptDiscount=trx.receipt_discount,
                    VoidStaffID=trx.void_staff_id,
                    VoidReason=trx.void_reason,
                    VoidTime=trx.void_time,
                    Deleted=trx.deleted
                )

                db.execute(trx_stmt)

                for detail in trx.order_details:

                    detail_stmt = insert(OrderDetail).values(
                        OrderDetailID=detail.order_detail_id,
                        TransactionID=detail.transaction_id,
                        ProductID=detail.product_id,
                        ProductSetType=detail.product_set_type,
                        OrderStatusID=detail.order_status_id,
                        SaleMode=detail.sale_mode,
                        Amount=detail.amount,
                        Price=detail.price,
                        RetailPrice=detail.retail_price,
                        MinimumPrice=detail.minimum_price,
                        Comment=detail.comment,
                        OrderStaffID=detail.order_staff_id,
                        OrderTableID=detail.order_table_id,
                        VoidStaffID=detail.void_staff_id
                    )

                    detail_stmt = detail_stmt.on_duplicate_key_update(
                        OrderStatusID=detail.order_status_id,
                        Amount=detail.amount,
                        Price=detail.price,
                        RetailPrice=detail.retail_price,
                        Comment=detail.comment,
                        VoidStaffID=detail.void_staff_id
                    )

                    db.execute(detail_stmt)

                    inserted += 1

            db.commit()

            logger.info(f"SYNC SUCCESS outlet={outlet} inserted_items={inserted}")

            return inserted

        except Exception as e:

            db.rollback()

            logger.error(f"SYNC ERROR outlet={outlet} error={str(e)}")

            raise