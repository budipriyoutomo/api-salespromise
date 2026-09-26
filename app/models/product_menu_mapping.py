from sqlalchemy import Boolean, Column, DateTime, Integer, String

from app.core.time import utcnow
from app.database import Base


class ProductMenuMapping(Base):
    """Menu (ProductID) yang dipublish ke RabbitMQ, di luar group yang aktif.

    `product_name` / `product_group` hanya salinan untuk tampilan, diambil dari
    data penjualan saat mapping dibuat. Publish mencocokkan lewat `product_id`.

    Tidak pernah dihapus — dimatikan lewat `is_active`, sama seperti
    `ProductGroupMapping`.
    """

    __tablename__ = "product_menu_mappings"

    id = Column(Integer, primary_key=True, autoincrement=True)

    product_id = Column(Integer, nullable=False, unique=True)
    product_name = Column(String(255), nullable=True)
    product_group = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=True)
