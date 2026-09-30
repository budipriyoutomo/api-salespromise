"""Logika brand dan mapping outlet → brand.

Dipakai route `/api/brands` (kelola) dan filter `?brand=` di laporan sales.

Satu outlet paling banyak satu brand. Sama seperti mapping lain, tidak ada
fungsi hapus: brand dimatikan lewat `is_active`, outlet dilepas dari brand
dengan `brand_id = None`.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.time import utcnow
from app.models.api_key import ApiKey
from app.models.brand import Brand, OutletBrandMapping

# Sama dengan panjang `api_keys.outlet_code`.
MAX_BRAND_CODE_LENGTH = 20
MAX_BRAND_NAME_LENGTH = 255


@dataclass
class OutletBrand:
    """Satu outlet beserta brand-nya (None kalau belum dipetakan)."""

    outlet_code: str
    is_active: bool
    brand_id: int | None = None
    brand_code: str | None = None
    brand_name: str | None = None


class BrandSudahAda(Exception):
    """Kode brand sudah terdaftar — termasuk yang sedang nonaktif."""


class BrandTidakDitemukan(Exception):
    pass


class BrandNonaktif(Exception):
    """Outlet tidak boleh dipetakan ke brand yang nonaktif."""


class OutletTidakDitemukan(Exception):
    """Outlet tidak punya API key — tidak dikenal sistem."""


class DataTidakValid(Exception):
    pass


def normalize_brand_code(value) -> str:
    """Bentuk pembanding kode brand: tanpa spasi di ujung, huruf besar.

    Hanya SPASI yang dibuang, sama dengan `UPPER(TRIM(code))` di CHECK
    migrasi 009.
    """
    if value is None:
        return ""
    return value.strip(" ").upper()


# ---------------------------------------------------------------------------
# Brand
# ---------------------------------------------------------------------------


def list_brands(db):
    return db.query(Brand).order_by(Brand.code).all()


def get_by_id(db, brand_id: int):
    return db.get(Brand, brand_id)


def get_by_code(db, code: str):
    return db.query(Brand).filter(Brand.code == normalize_brand_code(code)).first()


def _clean_name(name) -> str:
    name = (name or "").strip()
    if not name:
        raise DataTidakValid("name tidak boleh kosong")
    if len(name) > MAX_BRAND_NAME_LENGTH:
        raise DataTidakValid(f"name maksimal {MAX_BRAND_NAME_LENGTH} karakter")
    return name


def create_brand(db, code, name, is_active: bool = True):
    normal = normalize_brand_code(code)

    if not normal:
        raise DataTidakValid("code tidak boleh kosong")
    if len(normal) > MAX_BRAND_CODE_LENGTH:
        raise DataTidakValid(f"code maksimal {MAX_BRAND_CODE_LENGTH} karakter")

    name = _clean_name(name)

    if get_by_code(db, normal):
        raise BrandSudahAda(normal)

    row = Brand(code=normal, name=name, is_active=is_active, created_at=utcnow())
    db.add(row)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise BrandSudahAda(normal)

    db.refresh(row)
    return row


def update_brand(db, brand_id: int, name=None, is_active: bool | None = None):
    """Ubah nama / status. Kode tidak bisa diubah — dipakai sebagai filter laporan."""
    row = get_by_id(db, brand_id)
    if not row:
        raise BrandTidakDitemukan(brand_id)

    if name is not None:
        row.name = _clean_name(name)
    if is_active is not None:
        row.is_active = is_active
    row.updated_at = utcnow()

    db.commit()
    db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Mapping outlet → brand
# ---------------------------------------------------------------------------


def list_outlets(db) -> list[OutletBrand]:
    """Semua outlet (sumber: `api_keys`) beserta brand-nya, termasuk yang belum dipetakan."""
    rows = (
        db.query(ApiKey.outlet_code, ApiKey.is_active, Brand.id, Brand.code, Brand.name)
        .outerjoin(OutletBrandMapping, OutletBrandMapping.outlet_code == ApiKey.outlet_code)
        .outerjoin(Brand, Brand.id == OutletBrandMapping.brand_id)
        .order_by(ApiKey.outlet_code)
        .all()
    )
    return [
        OutletBrand(
            outlet_code=outlet_code,
            is_active=is_active,
            brand_id=brand_id,
            brand_code=brand_code,
            brand_name=brand_name,
        )
        for outlet_code, is_active, brand_id, brand_code, brand_name in rows
    ]


def get_outlet(db, outlet_code: str) -> OutletBrand | None:
    return next((o for o in list_outlets(db) if o.outlet_code == outlet_code), None)


def set_outlet_brand(db, outlet_code: str, brand_id: int | None) -> OutletBrand:
    """Petakan outlet ke brand, pindahkan ke brand lain, atau lepas (`brand_id=None`)."""
    if not db.query(ApiKey.outlet_code).filter(ApiKey.outlet_code == outlet_code).first():
        raise OutletTidakDitemukan(outlet_code)

    if brand_id is not None:
        brand = get_by_id(db, brand_id)
        if not brand:
            raise BrandTidakDitemukan(brand_id)
        if not brand.is_active:
            raise BrandNonaktif(brand.code)

    row = db.query(OutletBrandMapping).filter(OutletBrandMapping.outlet_code == outlet_code).first()

    if row is None:
        row = OutletBrandMapping(outlet_code=outlet_code, brand_id=brand_id, created_at=utcnow())
        db.add(row)
    else:
        row.brand_id = brand_id
        row.updated_at = utcnow()

    try:
        db.commit()
    except IntegrityError:
        # Dua admin memetakan outlet yang sama bersamaan — yang kalah mengulang
        # sebagai update atas baris yang baru dibuat.
        db.rollback()
        row = db.query(OutletBrandMapping).filter(OutletBrandMapping.outlet_code == outlet_code).one()
        row.brand_id = brand_id
        row.updated_at = utcnow()
        db.commit()

    return get_outlet(db, outlet_code)


def outlet_codes_subquery(brand_code: str):
    """Subquery `outlet_code` milik brand — untuk `Sales.outlet_code.in_(...)`.

    Brand yang tidak dikenal menghasilkan subquery kosong, jadi laporan kosong,
    sama seperti filter `?outlet=` dengan kode yang tidak ada. Brand nonaktif
    tetap bisa difilter: laporan historisnya masih relevan.
    """
    return (
        select(OutletBrandMapping.outlet_code)
        .join(Brand, Brand.id == OutletBrandMapping.brand_id)
        .where(Brand.code == normalize_brand_code(brand_code))
    )
