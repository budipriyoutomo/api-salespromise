"""Logika mapping per menu — menu mana yang dipublish ke RabbitMQ.

Pelengkap `product_group_service`: group aktif mengirim semua menu di dalamnya,
mapping di sini menambah menu satu per satu dari group mana pun. Publish
memakai gabungan keduanya.

Sama seperti mapping group, tidak ada fungsi hapus — menu dimatikan lewat
`is_active`.
"""

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from app.core.time import utcnow
from app.models.product_menu_mapping import ProductMenuMapping
from app.models.sales_items import SalesItems
from app.services.product_group_service import normalize_product_group
from app.services.sales_service import SalesService

CANDIDATE_DEFAULT_LIMIT = 100
CANDIDATE_MAX_LIMIT = 500


class MenuSudahAda(Exception):
    """Menu sudah terdaftar — termasuk yang sedang nonaktif."""


class MenuTidakDitemukan(Exception):
    pass


class MenuTidakAdaDiData(Exception):
    """ProductID tidak pernah muncul di data penjualan."""


def list_mappings(db):
    return (
        db.query(ProductMenuMapping)
        .order_by(ProductMenuMapping.product_group, ProductMenuMapping.product_name, ProductMenuMapping.product_id)
        .all()
    )


def get_by_id(db, mapping_id: int):
    return db.get(ProductMenuMapping, mapping_id)


def get_by_product_id(db, product_id: int):
    return db.query(ProductMenuMapping).filter(ProductMenuMapping.product_id == product_id).first()


def get_active_product_ids(db) -> list[int]:
    """ProductID aktif, terurut — ikut dipublish di samping group aktif."""
    rows = (
        db.query(ProductMenuMapping.product_id)
        .filter(ProductMenuMapping.is_active.is_(True))
        .order_by(ProductMenuMapping.product_id)
        .all()
    )
    return [row.product_id for row in rows]


def list_candidates(db, product_group=None, q=None, limit=CANDIDATE_DEFAULT_LIMIT):
    """Menu yang pernah muncul di data penjualan, untuk dipilih admin.

    Satu ProductID bisa muncul lebih dari sekali kalau nama / group-nya pernah
    diubah di POS — sengaja tidak disembunyikan, admin perlu melihatnya.
    """
    limit = max(1, min(limit or CANDIDATE_DEFAULT_LIMIT, CANDIDATE_MAX_LIMIT))

    group_expr = SalesService._normalized_product_group()
    name_expr = func.trim(SalesItems.product_name)

    query = db.query(
        SalesItems.product_id.label("product_id"),
        name_expr.label("product_name"),
        group_expr.label("product_group"),
        func.max(SalesItems.sale_date).label("last_sale_date"),
    ).filter(SalesItems.product_id > 0)

    normal_group = normalize_product_group(product_group)
    if normal_group:
        query = query.filter(group_expr == normal_group)

    kata = (q or "").strip()
    if kata:
        syarat = [func.upper(SalesItems.product_name).contains(kata.upper(), autoescape=True)]
        if kata.isdigit():
            syarat.append(SalesItems.product_id == int(kata))
        query = query.filter(or_(*syarat))

    rows = query.group_by(SalesItems.product_id, name_expr, group_expr).all()

    # Diurutkan di Python — alasan yang sama dengan list_product_groups.
    rows = sorted(rows, key=lambda r: (r.product_group or "", r.product_name or "", r.product_id))
    return rows[:limit]


def _info_terbaru(db, product_id: int):
    """Nama & group menu dari penjualan terakhirnya."""
    return (
        db.query(
            func.trim(SalesItems.product_name).label("product_name"),
            SalesService._normalized_product_group().label("product_group"),
        )
        .filter(SalesItems.product_id == product_id)
        .order_by(SalesItems.sale_date.desc(), SalesItems.transaction_id.desc())
        .first()
    )


def create_mapping(db, product_id: int, is_active: bool = True):
    if get_by_product_id(db, product_id):
        raise MenuSudahAda(product_id)

    info = _info_terbaru(db, product_id)
    if info is None:
        raise MenuTidakAdaDiData(product_id)

    row = ProductMenuMapping(
        product_id=product_id,
        product_name=info.product_name or None,
        product_group=info.product_group or None,
        is_active=is_active,
        created_at=utcnow(),
    )
    db.add(row)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise MenuSudahAda(product_id)

    db.refresh(row)
    return row


def set_active(db, mapping_id: int, is_active: bool):
    row = get_by_id(db, mapping_id)

    if not row:
        raise MenuTidakDitemukan(mapping_id)

    row.is_active = is_active
    row.updated_at = utcnow()

    db.commit()
    db.refresh(row)

    return row
