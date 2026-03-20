from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from datetime import datetime

from app.models.sales import Sales
from app.models.sales_items import SalesItems
from app.utils.logger import logger


class SalesService:

    @staticmethod
    def sync_sales(db: Session, outlet: str, sales_list):

        inserted_sales = 0
        inserted_items = 0

        try:
            for sale in sales_list:

                sales_stmt = insert(Sales).values(
                    TransactionID=sale.id,
                    outlet_code=outlet,
                    ShopID=sale.shop_id,
                    ReferenceNo=sale.reference_no,
                    SaleDate=sale.sale_date,
                    PaidTime=sale.paid_time,
                    CloseTime=sale.close_time,
                    TransactionStatusID=sale.transaction_status_id,
                    SaleMode=sale.sale_mode,
                    Deleted=sale.deleted,
                    NoCustomer=sale.no_customer,
                    OtherPercentDiscount=sale.other_percent_discount,
                    OtherAmountDiscount=sale.other_amount_discount,
                    ReceiptProductRetailPrice=sale.receipt_product_retail_price,
                    ReceiptSalePrice=sale.receipt_sale_price,
                    ReceiptPayPrice=sale.receipt_pay_price,
                    ReceiptDiscount=sale.receipt_discount,
                    ReceiptTotalAmount=sale.receipt_total_amount,
                    VATPercent=sale.vat_percent,
                    TransactionVAT=sale.transaction_vat,
                    TransactionExcludeVAT=sale.transaction_exclude_vat,
                    TransactionVATable=sale.transaction_vatable,
                    ServiceChargePercent=sale.service_charge_percent,
                    ServiceCharge=sale.service_charge,
                    ServiceChargeVAT=sale.service_charge_vat,
                    OtherIncome=sale.other_income,
                    OtherIncomeVAT=sale.other_income_vat,
                    VoidStaffID=sale.void_staff_id,
                    VoidReason=sale.void_reason,
                    VoidTime=sale.void_time,
                    TransactionNote=sale.transaction_note,
                    QueueName=sale.queue_name,
                    IsSplitTransaction=sale.is_split_transaction,
                    IsFromOtherTransaction=sale.is_from_other_transaction,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )

                sales_stmt = sales_stmt.on_conflict_do_update(
                    index_elements=["TransactionID"],
                    set_={
                        "ShopID": sale.shop_id,
                        "SaleDate": sale.sale_date,
                        "PaidTime": sale.paid_time,
                        "CloseTime": sale.close_time,
                        "ReceiptTotalAmount": sale.receipt_total_amount,
                        "ReceiptPayPrice": sale.receipt_pay_price,
                        "ReceiptDiscount": sale.receipt_discount,
                        "TransactionStatusID": sale.transaction_status_id,
                        "VoidStaffID": sale.void_staff_id,
                        "VoidReason": sale.void_reason,
                        "VoidTime": sale.void_time,
                        "updated_at": datetime.utcnow()
                    }
                )

                db.execute(sales_stmt)
                inserted_sales += 1

                for item in sale.items:

                    item_stmt = insert(SalesItems).values(
                        OrderDetailID=item.id,
                        TransactionID=sale.id,
                        ProductID=item.product_id,
                        ProductSetType=item.product_set_type,
                        OrderStatusID=item.order_status_id,
                        SaleMode=item.sale_mode,
                        Amount=item.qty,
                        Price=item.price,
                        RetailPrice=item.retail_price,
                        MinimumPrice=item.minimum_price,
                        subtotal=item.subtotal,
                        Comment=item.comment,
                        OrderStaffID=item.order_staff_id,
                        OrderTableID=item.order_table_id,
                        VoidStaffID=item.void_staff_id
                    )

                    item_stmt = item_stmt.on_conflict_do_update(
                        index_elements=["OrderDetailID", "TransactionID"],
                        set_={
                            "Amount": item.qty,
                            "Price": item.price,
                            "RetailPrice": item.retail_price,
                            "subtotal": item.subtotal,
                            "OrderStatusID": item.order_status_id,
                            "VoidStaffID": item.void_staff_id
                        }
                    )

                    db.execute(item_stmt)
                    inserted_items += 1

            db.commit()

            logger.info(
                f"SYNC SUCCESS outlet={outlet} "
                f"inserted_sales={inserted_sales} inserted_items={inserted_items}"
            )

            return {"sales": inserted_sales, "items": inserted_items}

        except Exception as e:

            db.rollback()

            logger.error(f"SYNC ERROR outlet={outlet} error={str(e)}")

            raise