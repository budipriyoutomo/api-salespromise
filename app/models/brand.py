from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.core.time import utcnow
from app.database import Base


class Brand(Base):
    """Brand yang menaungi beberapa outlet — dipakai untuk filter laporan.

    `code` selalu dalam bentuk normal (trim + huruf besar), ditegakkan oleh
    `brand_service` dan CHECK di migrasi 009. Tidak pernah dihapus — dimatikan
    lewat `is_active`.
    """

    __tablename__ = "brands"

    id = Column(Integer, primary_key=True, autoincrement=True)

    code = Column(String(20), nullable=False, unique=True)
    name = Column(String(255), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=True)

    outlets = relationship(
        "OutletBrandMapping",
        order_by="OutletBrandMapping.outlet_code",
        lazy="selectin",
        back_populates="brand",
    )


class OutletBrandMapping(Base):
    """Satu outlet → paling banyak satu brand.

    `outlet_code` mengikuti `api_keys.outlet_code` tanpa foreign key. Outlet
    dilepas dari brand dengan `brand_id = NULL`, barisnya tidak dihapus.
    """

    __tablename__ = "outlet_brand_mappings"

    id = Column(Integer, primary_key=True, autoincrement=True)

    outlet_code = Column(String(20), nullable=False, unique=True)
    brand_id = Column(Integer, ForeignKey("brands.id"), nullable=True, index=True)

    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=True)

    brand = relationship("Brand", back_populates="outlets", lazy="joined")
