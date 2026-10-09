from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.core.time import utcnow
from app.database import Base


class Product(Base):
    """Master data produk, dikelola admin (migrasi 014).

    `code` selalu dalam bentuk normal (trim + huruf besar), ditegakkan oleh
    `product_service` dan CHECK di migrasi. Tidak pernah dihapus — dimatikan
    lewat `is_active`.
    """

    __tablename__ = "products"
    __table_args__ = (CheckConstraint("price >= 0", name="ck_products_price"),)

    id = Column(Integer, primary_key=True, autoincrement=True)

    code = Column(String(50), nullable=False, unique=True)
    name = Column(String(255), nullable=False)
    category = Column(String(100), nullable=True)
    unit = Column(String(20), nullable=True)
    price = Column(Numeric(18, 4), nullable=False, default=0)
    brand_id = Column(Integer, ForeignKey("brands.id"), nullable=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=True)

    brand = relationship("Brand", lazy="joined")
    pos_mappings = relationship(
        "ProductPosMapping",
        order_by="(ProductPosMapping.outlet_code, ProductPosMapping.pos_product_id)",
        lazy="selectin",
        back_populates="product",
    )


class ProductPosMapping(Base):
    """ProductID POS satu outlet → produk master.

    POS tiap outlet menomori ProductID sendiri, jadi kuncinya
    (`outlet_code`, `pos_product_id`). Satu baris per pasangan itu: dipindah ke
    produk lain atau dimatikan lewat `is_active`, tidak pernah dihapus.

    `pos_product_name` / `pos_product_group` hanya salinan untuk tampilan,
    diambil dari penjualan terakhir saat dipetakan.
    """

    __tablename__ = "product_pos_mappings"
    __table_args__ = (
        UniqueConstraint("outlet_code", "pos_product_id", name="uq_product_pos_mappings_outlet_product"),
        CheckConstraint("pos_product_id > 0", name="ck_product_pos_mappings_pos_product_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)

    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    outlet_code = Column(String(20), nullable=False)
    pos_product_id = Column(Integer, nullable=False)
    pos_product_name = Column(String(255), nullable=True)
    pos_product_group = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=True)

    product = relationship("Product", back_populates="pos_mappings")
