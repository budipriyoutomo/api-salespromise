from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, String

from app.database import Base


class ApiKey(Base):
    """API key per outlet, dipakai mesin POS untuk endpoint sync.

    Kolom database tetap bernama `key` supaya migrasi tidak perlu mengubah
    primary key, tapi isinya sekarang **hash SHA-256**, bukan key mentah —
    karena itu atributnya dinamai `key_hash`. Lihat migrasi 003.

    Key mentah hanya ada sekali, saat dibuat lewat `manage_keys.py generate`.
    """

    __tablename__ = "api_keys"

    key_hash = Column("key", String(64), primary_key=True)

    # Potongan awal key, hanya untuk membantu mengenali baris di CLI.
    key_prefix = Column("key_prefix", String(12), nullable=True)

    outlet_code = Column(String(20), nullable=False, unique=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
