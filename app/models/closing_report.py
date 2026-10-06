"""Closing report dari RabbitMQ (`closingreport.submitted`) — TODO Fase 7.

Skema produksi ada di migrations/011_closing_reports.sql, 012_closing_menu_id.sql,
dan 013_closing_message_logs.sql; constraint di sini harus sama supaya test
SQLite mewakili Postgres.

Tidak ada yang dihapus: revisi baru mendapat baris revisi + item sendiri,
revisi lama dimatikan lewat `is_current`.
"""

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.core.time import utcnow
from app.database import Base


class ClosingReport(Base):
    """Header laporan, selalu berisi data dari revisi aktif.

    `outlet_code` tanpa foreign key ke `api_keys`: outlet yang belum terdaftar
    tetap disimpan.
    """

    __tablename__ = "closing_reports"
    __table_args__ = (
        UniqueConstraint("closing_report_id", name="uq_closing_reports_closing_report_id"),
        Index("ix_closing_reports_outlet_date", "outlet_code", "report_date"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)

    closing_report_id = Column(Uuid, nullable=False)
    report_date = Column(Date, nullable=False)
    outlet_code = Column(String(20), nullable=False)
    outlet_name = Column(String(255), nullable=False)
    brand_code = Column(String(20), nullable=False)
    brand_name = Column(String(255), nullable=False)

    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=True)

    revisions = relationship(
        "ClosingReportRevision",
        order_by="ClosingReportRevision.id",
        lazy="selectin",
        back_populates="report",
    )


class ClosingReportRevision(Base):
    """Satu kiriman pesan. Retry pengirim membawa sentAt baru dengan isi identik,
    jadi duplikat ditentukan `message_id` saja (migrasi 012)."""

    __tablename__ = "closing_report_revisions"
    __table_args__ = (
        UniqueConstraint("report_id", "message_id", name="uq_closing_report_revisions_message_id"),
        # Paling banyak satu revisi aktif per laporan.
        Index(
            "uq_closing_report_revisions_current",
            "report_id",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current"),
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)

    report_id = Column(Integer, ForeignKey("closing_reports.id"), nullable=False)
    message_id = Column(String(255), nullable=False)
    version = Column(SmallInteger, nullable=False)
    sent_at = Column(DateTime, nullable=False)
    received_at = Column(DateTime, nullable=False, default=utcnow)
    is_current = Column(Boolean, nullable=False, default=False)
    raw_payload = Column(JSON().with_variant(JSONB(), "postgresql"), nullable=False)

    report = relationship("ClosingReport", back_populates="revisions")
    items = relationship(
        "ClosingReportItem",
        order_by="ClosingReportItem.id",
        lazy="selectin",
    )

    @property
    def item_count(self) -> int:
        return len(self.items)


class ClosingReportItem(Base):
    __tablename__ = "closing_report_items"
    __table_args__ = (
        UniqueConstraint("revision_id", "menu_id", "production_date", name="uq_closing_report_items_menu_date"),
        # compensation tidak ikut: pengirim belum memvalidasinya (migrasi 012).
        CheckConstraint("sold >= 0 AND waste >= 0", name="ck_closing_report_items_qty"),
        Index("ix_closing_report_items_menu_id_date", "menu_id", "production_date"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)

    revision_id = Column(Integer, ForeignKey("closing_report_revisions.id"), nullable=False)
    menu_id = Column(Uuid, nullable=False)
    # Bisa null untuk menu lama tanpa kode.
    menu_code = Column(String(50), nullable=True)
    menu_name = Column(String(255), nullable=False)
    # Null = menu tanpa baris produksi hari itu; perbandingan memakai report_date.
    production_date = Column(Date, nullable=True)

    sold = Column(Integer, nullable=False)
    waste = Column(Integer, nullable=False)
    # Koreksi, boleh negatif.
    adjustment = Column(Integer, nullable=False)
    compensation = Column(Integer, nullable=False)


class ClosingMenu(Base):
    """Menu yang pernah muncul di pesan; tercatat otomatis saat pertama terlihat.

    Kuncinya `menu_id` — menuCode bisa berubah, unik hanya per brand, dan bisa
    null (jawaban pengirim). Belum dipetakan = belum punya `products` aktif.
    """

    __tablename__ = "closing_menus"
    __table_args__ = (UniqueConstraint("menu_id", name="uq_closing_menus_menu_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)

    menu_id = Column(Uuid, nullable=False)
    # Kode / nama / brand terakhir yang terlihat, untuk tampilan dan pencarian.
    menu_code = Column(String(50), nullable=True)
    menu_name = Column(String(255), nullable=False)
    brand_code = Column(String(20), nullable=True)

    first_seen_at = Column(DateTime, nullable=False, default=utcnow)
    last_seen_at = Column(DateTime, nullable=False, default=utcnow)

    products = relationship(
        "ClosingMenuProduct",
        order_by="ClosingMenuProduct.product_id",
        lazy="selectin",
    )

    @property
    def is_mapped(self) -> bool:
        return any(p.is_active for p in self.products)


class ClosingMenuProduct(Base):
    """Satu menu closing dihitung dari `product_id` POS × `multiplier`.

    Tidak dihapus — dimatikan lewat `is_active`.
    """

    __tablename__ = "closing_menu_products"
    __table_args__ = (
        UniqueConstraint("closing_menu_id", "product_id", name="uq_closing_menu_products_menu_product"),
        CheckConstraint("product_id > 0", name="ck_closing_menu_products_product_id"),
        CheckConstraint("multiplier > 0", name="ck_closing_menu_products_multiplier"),
        Index("ix_closing_menu_products_product", "product_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)

    closing_menu_id = Column(Integer, ForeignKey("closing_menus.id"), nullable=False)
    product_id = Column(Integer, nullable=False)
    # Salinan untuk tampilan; pencocokan hanya lewat product_id.
    product_name = Column(String(255), nullable=True)
    multiplier = Column(Integer, nullable=False, default=1)
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=True)


STATUS_LOG_PESAN = ("baru", "revisi", "revisi_lama", "duplikat", "ditolak")


class ClosingMessageLog(Base):
    """Satu baris per pesan yang diputuskan consumer (migrasi 013).

    Untuk diperiksa admin dari dashboard; tidak dipakai untuk perhitungan.
    """

    __tablename__ = "closing_message_logs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('baru', 'revisi', 'revisi_lama', 'duplikat', 'ditolak')",
            name="ck_closing_message_logs_status",
        ),
        Index("ix_closing_message_logs_received_at", "received_at"),
        Index("ix_closing_message_logs_status_received_at", "status", "received_at"),
        Index("ix_closing_message_logs_message_id", "message_id"),
    )

    # BIGSERIAL di Postgres; SQLite hanya auto-increment untuk INTEGER.
    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)

    received_at = Column(DateTime, nullable=False, default=utcnow)
    status = Column(String(20), nullable=False)
    reason = Column(String(255), nullable=True)
    errors = Column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)
    warnings = Column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)

    # Dari payload, juga untuk pesan yang ditolak.
    message_id = Column(String(255), nullable=True)
    outlet_code = Column(String(255), nullable=True)
    # Hanya untuk pesan yang lolos validasi.
    closing_report_id = Column(Uuid, nullable=True)
    report_date = Column(Date, nullable=True)
    item_count = Column(Integer, nullable=True)
    revision_id = Column(Integer, ForeignKey("closing_report_revisions.id"), nullable=True)

    body_bytes = Column(Integer, nullable=False)
    # JSON apa adanya; body_text hanya kalau body bukan JSON.
    payload = Column(JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql"), nullable=True)
    body_text = Column(Text, nullable=True)
