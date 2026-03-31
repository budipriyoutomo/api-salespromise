from sqlalchemy import Column, String, Boolean, DateTime
from datetime import datetime
from app.database import Base


class ApiKey(Base):
    __tablename__ = "api_keys"

    key = Column(String(64), primary_key=True)
    outlet_code = Column(String(20), nullable=False, unique=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)