from sqlalchemy import Column, Integer, SmallInteger, Numeric, String, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base


class OrderDetail(Base):

    __tablename__ = "orderdetail"

    order_detail_id = Column("OrderDetailID", Integer, primary_key=True, default=0)
    transaction_id = Column("TransactionID", Integer, ForeignKey("ordertransaction.TransactionID"), nullable=False, default=0)
    product_id = Column("ProductID", Integer, nullable=False, default=0)
    product_set_type = Column("ProductSetType", Integer, nullable=False, default=0)
    order_status_id = Column("OrderStatusID", SmallInteger, nullable=False, default=2)
    sale_mode = Column("SaleMode", Integer, nullable=False, default=1)
    amount = Column("Amount", Numeric(18, 4), nullable=False, default=0)
    price = Column("Price", Numeric(18, 4), nullable=False, default=0)
    retail_price = Column("RetailPrice", Numeric(18, 4), nullable=False, default=0)
    minimum_price = Column("MinimumPrice", Numeric(18, 4), nullable=False, default=0)
    comment = Column("Comment", String(255), nullable=True)
    order_staff_id = Column("OrderStaffID", Integer, nullable=False, default=0)
    order_table_id = Column("OrderTableID", Integer, nullable=False, default=0)
    void_staff_id = Column("VoidStaffID", Integer, nullable=False, default=0)

    transaction = relationship("OrderTransaction", back_populates="order_details")
