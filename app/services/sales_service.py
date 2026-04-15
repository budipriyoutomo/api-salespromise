import traceback

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy import func
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

                # 🔥 SALES UPSERT
                sales_stmt = insert(Sales).values(
                    TransactionID=sale.transaction_id,
                    outlet_code=outlet,
                    ShopID=sale.shop_id,
                    ReferenceNo=sale.reference_no,
                    QueueName=sale.queue_name,

                    SaleDate=sale.sale_date,
                    PaidTime=sale.paid_time,
                    CloseTime=sale.close_time,

                    TransactionStatusID=sale.transaction_status_id,
                    SaleMode=sale.sale_mode,
                    Deleted=sale.deleted,
                    NoCustomer=sale.no_customer, 

                    OtherPercentDiscount=sale.other_percent_discount,
                    OtherAmountDiscount=sale.other_amount_discount,

                    ReceiptID=sale.receipt_id,
                    ReceiptMonth=sale.receipt_month,
                    ReceiptYear=sale.receipt_year,

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

                    IsSplitTransaction=sale.is_split_transaction,
                    IsFromOtherTransaction=sale.is_from_other_transaction,

                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )

                # 🔥 UPSERT FIX (multi outlet safe)
                sales_stmt = sales_stmt.on_conflict_do_update(
                    index_elements=["TransactionID", "outlet_code"],
                    set_={
                        "ShopID": sale.shop_id,
                        "SaleDate": sale.sale_date,
                        "PaidTime": sale.paid_time,
                        "CloseTime": sale.close_time,
                        "ReceiptID": sale.receipt_id,
                        "ReceiptMonth": sale.receipt_month,
                        "ReceiptYear": sale.receipt_year,
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

                # 🔥 ITEMS
                for item in sale.items:
 

                    item_stmt = insert(SalesItems).values(
                        OrderDetailID=item.order_detail_id,
                        TransactionID=sale.transaction_id,

                        # 🔥 NEW
                        SaleDate=item.sale_date,

                        ProductID=item.product_id,
                        Group=item.product_group,
                        Dept=item.product_dept,
                        Name=item.product_name,

                        ProductSetType=item.product_set_type,
                        OrderStatusID=item.order_status_id,
                        SaleMode=item.sale_mode,

                        Amount=item.qty,
                        Price=item.price,
                        RetailPrice=item.retail_price,
                        MinimumPrice=item.minimum_price,
 

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

            
            logger.error(
                f"SYNC ERROR outlet={outlet} error={str(e)}\n{traceback.format_exc()}"
            )

            raise

    @staticmethod
    def get_sales(db, outlet=None, start_date=None, end_date=None):
        query = db.query(Sales)

        if outlet:
            query = query.filter(Sales.outlet == outlet)

        if start_date:
            query = query.filter(Sales.sales_date >= start_date)

        if end_date:
            query = query.filter(Sales.sales_date <= end_date)

        return query.all()
    
    @staticmethod
    def get_sales_colorplate(db, outlet=None, start_date=None, end_date=None):
        query = (
                db.query(
                    SalesItems.product_name,
                    Sales.outlet_code,
                    Sales.sale_date,
                    func.sum(SalesItems.qty).label("sold")
                )
                .join(Sales, Sales.transaction_id == SalesItems.transaction_id)
                .filter(SalesItems.product_group == "COLORPLATE")
            )
        if outlet:
                query = query.filter(Sales.outlet_code == outlet)

        if start_date:
                query = query.filter(Sales.sale_date >= start_date)

        if end_date:
                query = query.filter(Sales.sale_date <= end_date)

        query = query.group_by(
            SalesItems.product_name,
            Sales.outlet_code,
            Sales.sale_date
        )

        return query.all()