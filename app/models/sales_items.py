from sqlalchemy import Column, Numeric, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class SalesItems(Base):

    __tablename__ = "sales_items"

    id = Column(UUID(as_uuid=True), primary_key=True)
    sales_id = Column(UUID, ForeignKey("sales.id"))
    product_id = Column(Integer)
    qty = Column(Numeric(10,2))
    price = Column(Numeric(12,2))
    subtotal = Column(Numeric(12,2))