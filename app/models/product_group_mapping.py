from sqlalchemy import Boolean, Column, DateTime, Integer, String

from app.core.time import utcnow
from app.database import Base


class ProductGroupMapping(Base):
    """Product group yang dipublish ke RabbitMQ — pengganti literal `COLORPLATE`.

    `product_group` selalu dalam bentuk normal (trim + huruf besar), ditegakkan
    oleh `product_group_service` dan CHECK di migrasi 006.

    Tidak pernah dihapus: group yang tidak dipakai lagi dimatikan lewat
    `is_active`, supaya tetap terlihat group apa saja yang pernah dipublish.
    """

    __tablename__ = "product_group_mappings"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Panjangnya mengikuti kolom "Group" di orderdetail — lebih dari itu
    # tidak akan pernah cocok dengan data.
    product_group = Column(String(255), nullable=False, unique=True)
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=True)
