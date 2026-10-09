"""Logika master data product dan mapping ProductID POS → produk master.

Dipakai route `/api/products`. ProductID dinomori POS tiap outlet, jadi yang
dipetakan adalah pasangan (outlet, ProductID).

Sama seperti master lain, tidak ada fungsi hapus: produk dan mapping dimatikan
lewat `is_active`.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from app.core.time import utcnow
from app.models.brand import Brand
from app.models.product import Product, ProductPosMapping
from app.models.sales import Sales
from app.models.sales_items import SalesItems
from app.services.sales_service import SalesService, item_join

MAX_PRODUCT_CODE_LENGTH = 50
MAX_PRODUCT_NAME_LENGTH = 255
MAX_CATEGORY_LENGTH = 100
MAX_UNIT_LENGTH = 20
# Sama dengan panjang `api_keys.outlet_code`.
MAX_OUTLET_CODE_LENGTH = 20

CANDIDATE_DEFAULT_LIMIT = 100
CANDIDATE_MAX_LIMIT = 500


@dataclass
class KandidatPos:
    """Satu ProductID di data penjualan satu outlet, dengan nama terbarunya."""

    outlet_code: str
    pos_product_id: int
    pos_product_name: str | None
    pos_product_group: str | None
    last_sale_date: date | None
    mapped_product_id: int | None = None
    mapped_product_code: str | None = None


class ProdukSudahAda(Exception):
    """Kode produk sudah terdaftar — termasuk yang sedang nonaktif."""


class ProdukTidakDitemukan(Exception):
    pass


class ProdukNonaktif(Exception):
    """ProductID POS tidak boleh dipetakan ke produk yang nonaktif."""


class BrandTidakValid(Exception):
    """Brand tidak ada atau nonaktif."""


class PosTidakAdaDiData(Exception):
    """ProductID tidak pernah muncul di penjualan outlet itu."""


class PosSudahDipetakan(Exception):
    """ProductID outlet itu sudah aktif di produk (kode produk di args[0])."""


class MappingTidakDitemukan(Exception):
    pass


class DataTidakValid(Exception):
    pass


def normalize_product_code(value) -> str:
    """Bentuk pembanding kode produk — sama dengan `UPPER(TRIM(code))` di migrasi 014."""
    if value is None:
        return ""
    return value.strip(" ").upper()


# ---------------------------------------------------------------------------
# Produk
# ---------------------------------------------------------------------------


def list_products(db):
    return db.query(Product).order_by(Product.code).all()


def get_by_id(db, product_id: int):
    return db.get(Product, product_id)


def get_by_code(db, code: str):
    return db.query(Product).filter(Product.code == normalize_product_code(code)).first()


def _clean_name(name) -> str:
    name = (name or "").strip()
    if not name:
        raise DataTidakValid("name tidak boleh kosong")
    if len(name) > MAX_PRODUCT_NAME_LENGTH:
        raise DataTidakValid(f"name maksimal {MAX_PRODUCT_NAME_LENGTH} karakter")
    return name


def _clean_optional(value, field: str, max_length: int) -> str | None:
    """Teks opsional: dipangkas, kosong disimpan sebagai NULL."""
    value = (value or "").strip()
    if not value:
        return None
    if len(value) > max_length:
        raise DataTidakValid(f"{field} maksimal {max_length} karakter")
    return value


def _clean_price(price) -> Decimal:
    if price is None:
        raise DataTidakValid("price tidak boleh kosong")
    price = Decimal(str(price))
    if price < 0:
        raise DataTidakValid("price tidak boleh negatif")
    return price


def _check_brand(db, brand_id: int | None) -> None:
    if brand_id is None:
        return
    brand = db.get(Brand, brand_id)
    if not brand:
        raise BrandTidakValid(f"Brand id {brand_id} tidak ditemukan")
    if not brand.is_active:
        raise BrandTidakValid(f"Brand '{brand.code}' nonaktif")


def create_product(
    db,
    code,
    name,
    category=None,
    unit=None,
    price=0,
    brand_id: int | None = None,
    is_active: bool = True,
):
    normal = normalize_product_code(code)

    if not normal:
        raise DataTidakValid("code tidak boleh kosong")
    if len(normal) > MAX_PRODUCT_CODE_LENGTH:
        raise DataTidakValid(f"code maksimal {MAX_PRODUCT_CODE_LENGTH} karakter")

    row = Product(
        code=normal,
        name=_clean_name(name),
        category=_clean_optional(category, "category", MAX_CATEGORY_LENGTH),
        unit=_clean_optional(unit, "unit", MAX_UNIT_LENGTH),
        price=_clean_price(price),
        brand_id=brand_id,
        is_active=is_active,
        created_at=utcnow(),
    )

    _check_brand(db, brand_id)
    if get_by_code(db, normal):
        raise ProdukSudahAda(normal)

    db.add(row)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ProdukSudahAda(normal)

    db.refresh(row)
    return row


def update_product(db, product_id: int, changes: dict):
    """Ubah field yang dikirim saja. Kode tidak bisa diubah.

    `changes` berisi field yang benar-benar dikirim; `None` untuk category /
    unit / brand_id berarti dikosongkan.
    """
    row = get_by_id(db, product_id)
    if not row:
        raise ProdukTidakDitemukan(product_id)

    if "name" in changes:
        row.name = _clean_name(changes["name"])
    if "category" in changes:
        row.category = _clean_optional(changes["category"], "category", MAX_CATEGORY_LENGTH)
    if "unit" in changes:
        row.unit = _clean_optional(changes["unit"], "unit", MAX_UNIT_LENGTH)
    if "price" in changes:
        row.price = _clean_price(changes["price"])
    if "brand_id" in changes:
        _check_brand(db, changes["brand_id"])
        row.brand_id = changes["brand_id"]
    if changes.get("is_active") is not None:
        row.is_active = changes["is_active"]
    row.updated_at = utcnow()

    db.commit()
    db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Mapping ProductID POS → produk
# ---------------------------------------------------------------------------


def list_pos_candidates(db, outlet=None, q=None, limit=CANDIDATE_DEFAULT_LIMIT) -> list[KandidatPos]:
    """ProductID per outlet dari data penjualan, untuk dipilih admin.

    Nama / group yang ditampilkan diambil dari penjualan terakhir. Pencarian
    `q` mencocokkan nama mana pun yang pernah dipakai, atau ProductID persis.
    """
    limit = max(1, min(limit or CANDIDATE_DEFAULT_LIMIT, CANDIDATE_MAX_LIMIT))

    group_expr = SalesService._normalized_product_group()
    name_expr = func.trim(SalesItems.product_name)

    query = (
        db.query(
            Sales.outlet_code.label("outlet_code"),
            SalesItems.product_id.label("product_id"),
            name_expr.label("product_name"),
            group_expr.label("product_group"),
            func.max(SalesItems.sale_date).label("last_sale_date"),
            func.max(SalesItems.transaction_id).label("last_transaction_id"),
        )
        .join(Sales, item_join)
        .filter(SalesItems.product_id > 0)
    )

    if outlet:
        query = query.filter(Sales.outlet_code == outlet)

    kata = (q or "").strip()
    if kata:
        syarat = [func.upper(SalesItems.product_name).contains(kata.upper(), autoescape=True)]
        if kata.isdigit():
            syarat.append(SalesItems.product_id == int(kata))
        query = query.filter(or_(*syarat))

    rows = query.group_by(Sales.outlet_code, SalesItems.product_id, name_expr, group_expr).all()

    # Satu kandidat per (outlet, ProductID) — varian nama yang paling akhir terjual menang.
    terbaru: dict = {}
    for row in rows:
        kunci = (row.outlet_code, row.product_id)
        urutan = (row.last_sale_date or date.min, row.last_transaction_id or 0)
        if kunci not in terbaru or urutan > terbaru[kunci][0]:
            terbaru[kunci] = (urutan, row)

    mapped = {
        (m.outlet_code, m.pos_product_id): (m.product_id, code)
        for m, code in db.query(ProductPosMapping, Product.code)
        .join(Product, Product.id == ProductPosMapping.product_id)
        .filter(ProductPosMapping.is_active.is_(True))
        .all()
    }

    hasil = []
    for kunci in sorted(terbaru):
        row = terbaru[kunci][1]
        mapped_id, mapped_code = mapped.get(kunci, (None, None))
        hasil.append(
            KandidatPos(
                outlet_code=row.outlet_code,
                pos_product_id=row.product_id,
                pos_product_name=row.product_name or None,
                pos_product_group=row.product_group or None,
                last_sale_date=row.last_sale_date,
                mapped_product_id=mapped_id,
                mapped_product_code=mapped_code,
            )
        )
    return hasil[:limit]


def _info_pos_terbaru(db, outlet_code: str, pos_product_id: int):
    """Nama & group ProductID outlet itu dari penjualan terakhirnya."""
    return (
        db.query(
            func.trim(SalesItems.product_name).label("product_name"),
            SalesService._normalized_product_group().label("product_group"),
        )
        .join(Sales, item_join)
        .filter(Sales.outlet_code == outlet_code, SalesItems.product_id == pos_product_id)
        .order_by(SalesItems.sale_date.desc(), SalesItems.transaction_id.desc())
        .first()
    )


def add_pos_mapping(db, product_id: int, outlet_code: str, pos_product_id: int):
    """Petakan (outlet, ProductID) ke produk.

    Kalau pasangan itu sudah punya baris nonaktif — di produk mana pun — baris
    itu dipakai ulang (dipindah & diaktifkan). Yang masih aktif ditolak: admin
    harus menonaktifkannya dulu supaya pemindahan selalu disengaja.
    """
    product = get_by_id(db, product_id)
    if not product:
        raise ProdukTidakDitemukan(product_id)
    if not product.is_active:
        raise ProdukNonaktif(product.code)

    outlet_code = (outlet_code or "").strip()
    if not outlet_code:
        raise DataTidakValid("outlet_code tidak boleh kosong")

    info = _info_pos_terbaru(db, outlet_code, pos_product_id)
    if info is None:
        raise PosTidakAdaDiData(outlet_code, pos_product_id)

    row = (
        db.query(ProductPosMapping)
        .filter(ProductPosMapping.outlet_code == outlet_code, ProductPosMapping.pos_product_id == pos_product_id)
        .first()
    )

    if row is not None and row.is_active:
        raise PosSudahDipetakan(row.product.code)

    if row is None:
        row = ProductPosMapping(outlet_code=outlet_code, pos_product_id=pos_product_id, created_at=utcnow())
        db.add(row)
    else:
        row.updated_at = utcnow()

    row.product_id = product.id
    row.pos_product_name = info.product_name or None
    row.pos_product_group = info.product_group or None
    row.is_active = True

    try:
        db.commit()
    except IntegrityError:
        # Admin lain memetakan pasangan yang sama bersamaan.
        db.rollback()
        pemilik = (
            db.query(Product.code)
            .join(ProductPosMapping, ProductPosMapping.product_id == Product.id)
            .filter(ProductPosMapping.outlet_code == outlet_code, ProductPosMapping.pos_product_id == pos_product_id)
            .scalar()
        )
        raise PosSudahDipetakan(pemilik)

    db.refresh(product)
    return product


def set_pos_mapping_active(db, product_id: int, mapping_id: int, is_active: bool):
    product = get_by_id(db, product_id)
    if not product:
        raise ProdukTidakDitemukan(product_id)

    row = db.get(ProductPosMapping, mapping_id)
    if not row or row.product_id != product.id:
        raise MappingTidakDitemukan(mapping_id)

    row.is_active = is_active
    row.updated_at = utcnow()

    db.commit()
    db.refresh(product)
    return product
