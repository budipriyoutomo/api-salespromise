from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from app.database import Base

# Role yang dikenal sistem:
#   admin   — akses penuh semua outlet, termasuk pengelolaan user & API key
#   manager — baca data semua outlet
#   outlet  — baca data outletnya sendiri saja (wajib punya outlet_code)
ROLE_ADMIN = "admin"
ROLE_MANAGER = "manager"
ROLE_OUTLET = "outlet"

ROLES = (ROLE_ADMIN, ROLE_MANAGER, ROLE_OUTLET)

# Role yang boleh melihat data lintas outlet
CROSS_OUTLET_ROLES = (ROLE_ADMIN, ROLE_MANAGER)


class User(Base):
    """User dashboard — terpisah dari API key outlet yang dipakai mesin POS."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)

    email = Column(String(255), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=True)

    role = Column(String(20), nullable=False, default=ROLE_OUTLET)
    # Wajib diisi untuk role 'outlet'; dibiarkan NULL untuk admin/manager.
    outlet_code = Column(String(20), nullable=True, index=True)

    is_active = Column(Boolean, nullable=False, default=True)

    # Menyala selama password akun ini ditentukan orang lain — saat dibuat,
    # dan setiap kali admin mereset paksa. Padam begitu pemiliknya mengganti
    # sendiri. Frontend memakainya untuk memaksa penggantian di login pertama.
    #
    # Default False, bukan True: baris yang sudah ada sebelum kolom ini lahir
    # tidak boleh tiba-tiba terkunci saat login berikutnya.
    must_change_password = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def can_read_all_outlets(self) -> bool:
        return self.role in CROSS_OUTLET_ROLES
