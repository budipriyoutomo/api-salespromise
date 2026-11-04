"""Mapping menu closing report → ProductID POS (TODO Fase 7.6).

Menu (kunci menuId) tercatat otomatis oleh consumer (`closing_report_service`).
Admin memetakannya ke satu atau beberapa ProductID POS dengan pengali =
berapa unit produk POS untuk 1 porsi menu. Perbandingan dihitung per produk:

    closing(produk) = Σ menu ke produk itu: (sold + adjustment + compensation) × multiplier

Menu yang memang tidak ada di POS ditandai `not_in_pos` (migrasi 018). Tanda
dan mapping aktif tidak boleh ada bersamaan; admin memilih dari frontend:
`set_not_in_pos(deactivate_products=True)` mematikan mapping, mapping baru /
yang diaktifkan dengan `clear_not_in_pos=True` melepas tanda. Tanpa pilihan
itu = `TidakAdaDiPosBentrok` (409).

Tidak ada fungsi hapus — mapping dimatikan lewat `is_active`.
"""

from sqlalchemy import exists, func, or_
from sqlalchemy.exc import IntegrityError

from app.core.time import utcnow
from app.models.closing_report import ClosingMenu, ClosingMenuProduct
from app.services import product_menu_service

DEFAULT_LIMIT = 50
MAX_LIMIT = 200

STATUS_SEMUA = "all"
STATUS_DIPETAKAN = "mapped"
STATUS_BELUM = "unmapped"
STATUS_TIDAK_ADA_DI_POS = "not_in_pos"
STATUS_MENU = (STATUS_SEMUA, STATUS_DIPETAKAN, STATUS_BELUM, STATUS_TIDAK_ADA_DI_POS)


class MenuTidakDitemukan(Exception):
    pass


class MappingTidakDitemukan(Exception):
    pass


class ProductSudahAda(Exception):
    """ProductID sudah dipetakan ke menu ini — termasuk yang nonaktif."""


class ProductTidakAdaDiData(Exception):
    """ProductID tidak pernah muncul di data penjualan."""


class TidakAdaDiPosBentrok(Exception):
    """Tanda "tidak ada di POS" dan mapping aktif akan ada bersamaan."""


def list_menus(db, status: str = STATUS_SEMUA, q: str | None = None, limit=DEFAULT_LIMIT, offset=0):
    """Menu terurut menuCode. Mengembalikan (baris, total)."""
    query = db.query(ClosingMenu)

    q = (q or "").strip()
    if q:
        pola = f"%{q.lower()}%"
        query = query.filter(or_(func.lower(ClosingMenu.menu_code).like(pola), func.lower(ClosingMenu.menu_name).like(pola)))

    # Aturan yang sama dengan `ClosingMenu.is_mapped`: punya mapping aktif.
    punya_mapping_aktif = (
        exists()
        .where(ClosingMenuProduct.closing_menu_id == ClosingMenu.id)
        .where(ClosingMenuProduct.is_active.is_(True))
    )
    if status == STATUS_DIPETAKAN:
        query = query.filter(punya_mapping_aktif)
    elif status == STATUS_BELUM:
        # Hanya yang masih perlu tindakan admin.
        query = query.filter(~punya_mapping_aktif, ClosingMenu.not_in_pos.is_(False))
    elif status == STATUS_TIDAK_ADA_DI_POS:
        query = query.filter(ClosingMenu.not_in_pos.is_(True))

    total = query.count()
    rows = query.order_by(ClosingMenu.menu_code, ClosingMenu.id).limit(limit).offset(offset).all()
    return rows, total


def get_menu(db, menu_id: int):
    return db.get(ClosingMenu, menu_id)


def _lepas_tanda(menu: ClosingMenu):
    menu.not_in_pos = False
    menu.not_in_pos_by = None
    menu.not_in_pos_at = None


def _cek_tanda_sebelum_mapping_aktif(menu: ClosingMenu, clear_not_in_pos: bool):
    if not menu.not_in_pos:
        return
    if not clear_not_in_pos:
        raise TidakAdaDiPosBentrok(menu.id)
    _lepas_tanda(menu)


def set_not_in_pos(db, menu_id: int, not_in_pos: bool, by: str, deactivate_products: bool = False):
    """Tandai / lepas tanda. Menandai menu dengan mapping aktif butuh `deactivate_products`."""
    menu = db.get(ClosingMenu, menu_id)
    if menu is None:
        raise MenuTidakDitemukan(menu_id)

    if not not_in_pos:
        _lepas_tanda(menu)
    else:
        aktif = [p for p in menu.products if p.is_active]
        if aktif and not deactivate_products:
            raise TidakAdaDiPosBentrok(menu.id)
        sekarang = utcnow()
        for p in aktif:
            p.is_active = False
            p.updated_at = sekarang
        if not menu.not_in_pos:
            menu.not_in_pos = True
            menu.not_in_pos_by = by
            menu.not_in_pos_at = sekarang

    db.commit()
    db.refresh(menu)
    return menu


def add_product(
    db, menu_id: int, product_id: int, multiplier: int = 1, is_active: bool = True, clear_not_in_pos: bool = False
):
    menu = db.get(ClosingMenu, menu_id)
    if menu is None:
        raise MenuTidakDitemukan(menu_id)

    if any(p.product_id == product_id for p in menu.products):
        raise ProductSudahAda(product_id)

    # Sumber nama yang sama dengan mapping menu colorplate.
    info = product_menu_service._info_terbaru(db, product_id)
    if info is None:
        raise ProductTidakAdaDiData(product_id)

    if is_active:
        _cek_tanda_sebelum_mapping_aktif(menu, clear_not_in_pos)

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


def update_product(
    db,
    menu_id: int,
    mapping_id: int,
    multiplier: int | None = None,
    is_active: bool | None = None,
    clear_not_in_pos: bool = False,
):
    row = db.get(ClosingMenuProduct, mapping_id)
    if row is None or row.closing_menu_id != menu_id:
        raise MappingTidakDitemukan(mapping_id)

    if is_active and not row.is_active:
        _cek_tanda_sebelum_mapping_aktif(db.get(ClosingMenu, menu_id), clear_not_in_pos)

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
