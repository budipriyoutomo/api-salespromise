from sqlalchemy import Column, Integer, String, Text, ForeignKey
from sqlalchemy.dialects.mysql import TINYINT, SMALLINT, DECIMAL
from app.database import Base


class SalesItems(Base):
    """
    SQLAlchemy model sesuai orderdetail.sql
    """

    __tablename__ = "orderdetail"

    id = Column("OrderDetailID", Integer, primary_key=True)
    sales_id = Column("TransactionID", Integer, ForeignKey("ordertransaction.TransactionID"),
                      nullable=False, primary_key=True)

    product_id = Column("ProductID", Integer, nullable=False, default=0)
    product_set_type = Column("ProductSetType", Integer, nullable=False, default=0)
    order_status_id = Column("OrderStatusID", SMALLINT, nullable=False, default=2)
    sale_mode = Column("SaleMode", TINYINT, nullable=False, default=1)

    qty = Column("Amount", DECIMAL(18, 4), nullable=False, default=0)
    price = Column("Price", DECIMAL(18, 4), nullable=False, default=0)
    retail_price = Column("RetailPrice", DECIMAL(18, 4), nullable=False, default=0)
    minimum_price = Column("MinimumPrice", DECIMAL(18, 4), nullable=False, default=0)
    subtotal = Column("subtotal", DECIMAL(18, 4), nullable=True)  # computed, tidak ada di SQL asli

    comment = Column("Comment", String(255), nullable=True)
    order_staff_id = Column("OrderStaffID", Integer, nullable=False, default=0)
    order_table_id = Column("OrderTableID", Integer, nullable=False, default=0)
    void_staff_id = Column("VoidStaffID", Integer, nullable=False, default=0)