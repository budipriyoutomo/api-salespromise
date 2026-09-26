from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.core.time import utcnow
from app.database import Base


class ProductMenuMapping(Base):
    """Menu (ProductID) yang dipublish ke RabbitMQ sebagai warna colorplate.

    `product_name` / `product_group` hanya salinan untuk tampilan, diambil dari
    data penjualan saat mapping dibuat. Publish mencocokkan lewat `product_id`,
    lalu mengonversi qty-nya lewat `colorplates`.

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

    colorplates = relationship(
        "ProductMenuColorplate",
        order_by="ProductMenuColorplate.platecolor",
        lazy="selectin",
    )


class ProductMenuColorplate(Base):
    """Satu menu dihitung sebagai `multiplier` × warna colorplate.

    Contoh: "Buy 1 Get 2 RED" → platecolor RED, multiplier 2. Tidak dihapus —
    dimatikan lewat `is_active`.
    """

    __tablename__ = "product_menu_colorplates"
    __table_args__ = (UniqueConstraint("menu_mapping_id", "platecolor", name="uq_product_menu_colorplates_menu_color"),)

    id = Column(Integer, primary_key=True, autoincrement=True)

    menu_mapping_id = Column(Integer, ForeignKey("product_menu_mappings.id"), nullable=False, index=True)
    platecolor = Column(String(255), nullable=False)
    multiplier = Column(Integer, nullable=False, default=1)
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=True)
