"""Logika pengelolaan user dashboard.

Dipakai bersama oleh route `/api/users` dan CLI `manage_users.py`.

Sebagian aturan di sini bukan validasi data biasa, melainkan pagar agar admin
tidak bisa mengunci dirinya sendiri keluar dari sistem:

- tidak boleh menonaktifkan atau menurunkan role akun sendiri
- admin aktif terakhir tidak boleh diturunkan atau dinonaktifkan

Tanpa itu, satu klik salah di dashboard bisa membuat sistem tidak punya admin
sama sekali, dan satu-satunya jalan keluar adalah mengubah database manual.
"""

from app.core import security
from app.core.time import utcnow
from app.models.user import ROLE_ADMIN, ROLE_OUTLET, ROLES, User

MIN_PASSWORD_LENGTH = 8


class EmailSudahTerdaftar(Exception):
    pass


class UserTidakDitemukan(Exception):
    pass


class DataTidakValid(ValueError):
    """Role tidak dikenal, password terlalu pendek, outlet_code kurang, dsb."""


class MenguncilDiriSendiri(Exception):
    """Operasi ini akan membuat pemanggil atau sistem kehilangan akses admin."""


# ---------------------------------------------------------------------------
# Validasi
# ---------------------------------------------------------------------------


def normalize_email(email: str) -> str:
    return email.strip().lower()


def validasi_password(password: str):
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        raise DataTidakValid(f"Password minimal {MIN_PASSWORD_LENGTH} karakter")


def validasi_role(role: str, outlet_code=None):
    if role not in ROLES:
        raise DataTidakValid(f"Role '{role}' tidak dikenal. Pilihan: {', '.join(ROLES)}")

    if role == ROLE_OUTLET and not outlet_code:
        raise DataTidakValid("Role 'outlet' wajib disertai outlet_code")


def _outlet_untuk(role: str, outlet_code):
    """Hanya role 'outlet' yang menyimpan outlet_code.

    Admin dan manager berlaku lintas outlet — menyimpan outlet_code di sana
    hanya membuat data rancu dan bisa disalahartikan sebagai pembatas.
    """
    return outlet_code if role == ROLE_OUTLET else None


# ---------------------------------------------------------------------------
# Baca
# ---------------------------------------------------------------------------


def list_users(db):
    return db.query(User).order_by(User.email).all()


def get_by_id(db, user_id: int):
    return db.query(User).filter(User.id == user_id).first()


def get_by_email(db, email: str):
    return db.query(User).filter(User.email == normalize_email(email)).first()


def hitung_admin_aktif(db, kecuali_id=None):
    query = db.query(User).filter(User.role == ROLE_ADMIN, User.is_active.is_(True))

    if kecuali_id is not None:
        query = query.filter(User.id != kecuali_id)

    return query.count()


# ---------------------------------------------------------------------------
# Tulis
# ---------------------------------------------------------------------------


def create_user(db, email: str, password: str, role: str, outlet_code=None, full_name=None):
    email = normalize_email(email)

    validasi_role(role, outlet_code)
    validasi_password(password)

    if get_by_email(db, email):
        raise EmailSudahTerdaftar(email)

    user = User(
        email=email,
        password_hash=security.hash_password(password),
        full_name=full_name,
        role=role,
        outlet_code=_outlet_untuk(role, outlet_code),
        is_active=True,
        created_at=utcnow(),
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return user


def update_user(db, user_id: int, actor: User = None, **perubahan):
    """Perbarui user.

    `actor` adalah user yang melakukan perubahan. Diperlukan untuk menegakkan
    pagar anti-terkunci; kalau `None` (mis. dipanggil dari CLI), pagar itu
    dilewati karena operator sudah punya akses langsung ke database.

    `email` sengaja tidak bisa diubah: email adalah subject JWT, jadi
    mengubahnya membuat token yang sedang berjalan menunjuk user yang tak ada.
    """
    user = get_by_id(db, user_id)

    if not user:
        raise UserTidakDitemukan(user_id)

    role_baru = perubahan.get("role", user.role)
    outlet_baru = perubahan.get("outlet_code", user.outlet_code)
    aktif_baru = perubahan.get("is_active", user.is_active)

    if "role" in perubahan or "outlet_code" in perubahan:
        validasi_role(role_baru, outlet_baru)

    menurunkan_admin = user.role == ROLE_ADMIN and role_baru != ROLE_ADMIN
    menonaktifkan = user.is_active and not aktif_baru

    if actor is not None and actor.id == user.id and (menurunkan_admin or menonaktifkan):
        raise MenguncilDiriSendiri("Tidak bisa menurunkan atau menonaktifkan akun sendiri")

    if (menurunkan_admin or (menonaktifkan and user.role == ROLE_ADMIN)) and hitung_admin_aktif(
        db, kecuali_id=user.id
    ) == 0:
        raise MenguncilDiriSendiri("Sistem harus punya minimal satu admin aktif")

    if "full_name" in perubahan:
        user.full_name = perubahan["full_name"]
    if "role" in perubahan:
        user.role = role_baru
    if "role" in perubahan or "outlet_code" in perubahan:
        user.outlet_code = _outlet_untuk(role_baru, outlet_baru)
    if "is_active" in perubahan:
        user.is_active = aktif_baru

    user.updated_at = utcnow()

    db.commit()
    db.refresh(user)

    return user


def set_password(db, user_id: int, password: str):
    validasi_password(password)

    user = get_by_id(db, user_id)

    if not user:
        raise UserTidakDitemukan(user_id)

    user.password_hash = security.hash_password(password)
    user.updated_at = utcnow()

    db.commit()
    db.refresh(user)

    return user


def set_active(db, email: str, is_active: bool):
    """Dipakai CLI. Pagar admin-terakhir tetap berlaku."""
    user = get_by_email(db, email)

    if not user:
        raise UserTidakDitemukan(email)

    if user.is_active and not is_active and user.role == ROLE_ADMIN:
        if hitung_admin_aktif(db, kecuali_id=user.id) == 0:
            raise MenguncilDiriSendiri("Sistem harus punya minimal satu admin aktif")

    user.is_active = is_active
    user.updated_at = utcnow()

    db.commit()
    db.refresh(user)

    return user
