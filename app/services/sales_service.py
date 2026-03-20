from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from datetime import datetime

from app.models.sales import Sales
from app.models.sales_items import SalesItems
from app.utils.logger import logger


class SalesService:

    @staticmethod
    def sync_sales(db: Session, outlet: str, sales_list):

        inserted = 0

        try:

            for sale in sales_list:

                sales_stmt = insert(Sales).values(
                    id=sale.id,
                    outlet_code=outlet,
                    invoice_number=sale.invoice_number,
                    trx_date=sale.trx_date,
                    total=sale.total,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )

                sales_stmt = sales_stmt.on_conflict_do_update(
                    index_elements=["id"],
                    set_={
                        "invoice_number": sale.invoice_number,
                        "trx_date": sale.trx_date,
                        "total": sale.total,
                        "updated_at": datetime.utcnow()
                    }
                )

                db.execute(sales_stmt)

                for item in sale.items:

                    item_stmt = insert(SalesItems).values(
                        id=item.id,
                        sales_id=sale.id,
                        product_id=item.product_id,
                        qty=item.qty,
                        price=item.price,
                        subtotal=item.subtotal
                    )

                    item_stmt = item_stmt.on_conflict_do_update(
                        index_elements=["id"],
                        set_={
                            "qty": item.qty,
                            "price": item.price,
                            "subtotal": item.subtotal
                        }
                    )

                    db.execute(item_stmt)

                    inserted += 1

            db.commit()

            logger.info(f"SYNC SUCCESS outlet={outlet} inserted_items={inserted}")

            return inserted

        except Exception as e:

            db.rollback()

            logger.error(f"SYNC ERROR outlet={outlet} error={str(e)}")

            raise