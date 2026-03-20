from sqlalchemy import Column, String, DateTime, Numeric
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class Sales(Base):

    __tablename__ = "sales"

    id = Column(UUID(as_uuid=True), primary_key=True)
    outlet_code = Column(String(20))
    invoice_number = Column(String(50))
    trx_date = Column(DateTime)
    total = Column(Numeric(12,2))
    created_at = Column(DateTime)
    updated_at = Column(DateTime)