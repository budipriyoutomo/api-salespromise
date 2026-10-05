"""Mapping menu closing report → ProductID POS (TODO Fase 7.6).

Menu (kunci menuId) tercatat otomatis oleh consumer (`closing_report_service`).
Admin memetakannya ke satu atau beberapa ProductID POS dengan pengali =
berapa unit produk POS untuk 1 porsi menu. Perbandingan dihitung per produk:

    closing(produk) = Σ menu ke produk itu: (sold + adjustment + compensation) × multiplier

Tidak ada fungsi hapus — mapping dimatikan lewat `is_active`.
"""

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from app.core.time import utcnow
from app.models.closing_report import ClosingMenu, ClosingMenuProduct
from app.services import product_menu_service

STATUS_SEMUA = "all"
STATUS_DIPETAKAN = "mapped"
STATUS_BELUM = "unmapped"
STATUS_MENU = (STATUS_SEMUA, STATUS_DIPETAKAN, STATUS_BELUM)


class MenuTidakDitemukan(Exception):
    pass


class MappingTidakDitemukan(Exception):
    pass


class ProductSudahAda(Exception):
    """ProductID sudah dipetakan ke menu ini — termasuk yang nonaktif."""


class ProductTidakAdaDiData(Exception):
    """ProductID tidak pernah muncul di data penjualan."""


def list_menus(db, status: str = STATUS_SEMUA, q: str | None = None):
    query = db.query(ClosingMenu)

    q = (q or "").strip()
    if q:
        pola = f"%{q.lower()}%"
        query = query.filter(or_(func.lower(ClosingMenu.menu_code).like(pola), func.lower(ClosingMenu.menu_name).like(pola)))

    menus = query.order_by(ClosingMenu.menu_code).all()

    # Status dihitung di Python: daftar menu kecil, dan aturannya ("punya
    # mapping aktif") sama persis dengan `ClosingMenu.is_mapped`.
    if status == STATUS_DIPETAKAN:
        return [m for m in menus if m.is_mapped]
    if status == STATUS_BELUM:
        return [m for m in menus if not m.is_mapped]
    return menus


def add_product(db, menu_id: int, product_id: int, multiplier: int = 1, is_active: bool = True):
    menu = db.get(ClosingMenu, menu_id)
    if menu is None:
        raise MenuTidakDitemukan(menu_id)

    if any(p.product_id == product_id for p in menu.products):
        raise ProductSudahAda(product_id)

    # Sumber nama yang sama dengan mapping menu colorplate.
    info = product_menu_service._info_terbaru(db, product_id)
    if info is None:
        raise ProductTidakAdaDiData(product_id)

    row = ClosingMenuProduct(
        closing_menu_id=menu.id,
        product_id=product_id,
        product_name=info.product_name or None,
        multiplier=multiplier,
        is_active=is_active,
        created_at=utcnow(),
    )
    db.add(row)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ProductSudahAda(product_id)

    db.refresh(row)
    return row


def update_product(db, menu_id: int, mapping_id: int, multiplier: int | None = None, is_active: bool | None = None):
    row = db.get(ClosingMenuProduct, mapping_id)
    if row is None or row.closing_menu_id != menu_id:
        raise MappingTidakDitemukan(mapping_id)

    if multiplier is not None:
        row.multiplier = multiplier
    if is_active is not None:
        row.is_active = is_active
    row.updated_at = utcnow()

    db.commit()
    db.refresh(row)
    return row


def active_mappings(db) -> dict:
    """menu_id → [(product_id, multiplier, product_name)] dari baris mapping aktif.

    Dikunci menu_id: menuCode bisa berubah, unik hanya per brand, dan bisa null.
    """
    rows = (
        db.query(
            ClosingMenu.menu_id,
            ClosingMenuProduct.product_id,
            ClosingMenuProduct.multiplier,
            ClosingMenuProduct.product_name,
        )
        .join(ClosingMenuProduct, ClosingMenuProduct.closing_menu_id == ClosingMenu.id)
        .filter(ClosingMenuProduct.is_active.is_(True))
        .order_by(ClosingMenuProduct.product_id)
        .all()
    )

    hasil: dict = {}
    for row in rows:
        hasil.setdefault(row.menu_id, []).append((row.product_id, row.multiplier, row.product_name))
    return hasil
