from sqlalchemy import Column, Date, ForeignKeyConstraint, Integer, Numeric, SmallInteger, String

from app.database import Base


class SalesItems(Base):
    __tablename__ = "orderdetail"
    __table_args__ = (
        # Item menunjuk transaksi lewat (TransactionID, outlet_code), bukan
        # TransactionID saja — lihat Sales.outlet_code.
        ForeignKeyConstraint(
            ["TransactionID", "outlet_code"],
            ["ordertransaction.TransactionID", "ordertransaction.outlet_code"],
        ),
    )

    order_detail_id = Column("OrderDetailID", Integer, primary_key=True)
    transaction_id = Column("TransactionID", Integer, primary_key=True, nullable=False)
    outlet_code = Column("outlet_code", String(20), primary_key=True, nullable=False)

    sale_date = Column("SaleDate", Date, nullable=False)

    product_id = Column("ProductID", Integer, nullable=False, default=0)

    product_group = Column("Group", String(255), nullable=True)
    product_dept = Column("Dept", String(255), nullable=True)
    product_name = Column("Name", String(255), nullable=True)

    product_set_type = Column("ProductSetType", Integer, nullable=False, default=0)
    order_status_id = Column("OrderStatusID", SmallInteger, nullable=False, default=2)
    sale_mode = Column("SaleMode", SmallInteger, nullable=False, default=1)

    qty = Column("Amount", Numeric(18, 4), nullable=False, default=0)
    price = Column("Price", Numeric(18, 4), nullable=False, default=0)
    retail_price = Column("RetailPrice", Numeric(18, 4), nullable=False, default=0)
    minimum_price = Column("MinimumPrice", Numeric(18, 4), nullable=False, default=0)


    comment = Column("Comment", String(255), nullable=True)
    order_staff_id = Column("OrderStaffID", Integer, nullable=False, default=0)
    order_table_id = Column("OrderTableID", Integer, nullable=False, default=0)
    void_staff_id = Column("VoidStaffID", Integer, nullable=False, default=0)
