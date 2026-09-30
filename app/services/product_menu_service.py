"""Logika mapping per menu — menu mana yang ikut dihitung ke warna colorplate.

Publish hanya mengirim format colorplate. Menu dari group lain ikut terhitung
lewat konversi di `product_menu_colorplates`: qty menu × multiplier ditambahkan
ke warna tujuannya. Menu aktif tanpa konversi aktif tidak dipublish.

Sama seperti mapping group, tidak ada fungsi hapus — menu dan konversinya
dimatikan lewat `is_active`.
"""

from dataclasses import dataclass, field

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from app.core.time import utcnow
from app.models.product_menu_mapping import ProductMenuColorplate, ProductMenuMapping
from app.models.sales import Sales
from app.models.sales_items import SalesItems
from app.services.product_group_service import normalize_product_group
from app.services.sales_service import SalesService, color_key, item_join

CANDIDATE_DEFAULT_LIMIT = 100
CANDIDATE_MAX_LIMIT = 500


@dataclass
class KandidatMenu:
    """Satu menu di data penjualan — sudah digabung dari beberapa outlet.

    `outlet_codes` hanya keterangan: mapping menu berlaku untuk semua outlet,
    jadi menu yang sama tidak boleh muncul sebagai dua baris hanya karena
    terjual di dua outlet.
    """

    product_id: int
    product_name: str | None
    product_group: str | None
    outlet_codes: list[str] = field(default_factory=list)
    last_sale_date: object = None


class MenuSudahAda(Exception):
    """Menu sudah terdaftar — termasuk yang sedang nonaktif."""


class MenuTidakDitemukan(Exception):
    pass


class MenuTidakAdaDiData(Exception):
    """ProductID tidak pernah muncul di data penjualan."""


class WarnaTidakDikenal(Exception):
    """Warna tidak pernah muncul sebagai menu COLORPLATE di data penjualan."""


class WarnaSudahAda(Exception):
    """Menu sudah punya konversi ke warna ini — termasuk yang nonaktif."""


class KonversiTidakDitemukan(Exception):
    pass


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


def get_active_conversions(db) -> dict[int, list[tuple[str, int]]]:
    """ProductID → [(platecolor, multiplier)] dari menu aktif & konversi aktif.

    Menu aktif yang belum punya konversi aktif tidak muncul di sini, jadi
    tidak dipublish.
    """
    rows = (
        db.query(ProductMenuMapping.product_id, ProductMenuColorplate.platecolor, ProductMenuColorplate.multiplier)
        .join(ProductMenuColorplate, ProductMenuColorplate.menu_mapping_id == ProductMenuMapping.id)
        .filter(ProductMenuMapping.is_active.is_(True), ProductMenuColorplate.is_active.is_(True))
        .order_by(ProductMenuMapping.product_id, ProductMenuColorplate.platecolor)
        .all()
    )

    hasil: dict[int, list[tuple[str, int]]] = {}
    for row in rows:
        hasil.setdefault(row.product_id, []).append((row.platecolor, row.multiplier))
    return hasil


def list_colors(db) -> list[str]:
    return SalesService.list_colorplate_colors(db)


def _get_colorplate(db, mapping_id: int, colorplate_id: int):
    row = db.get(ProductMenuColorplate, colorplate_id)
    if row is None or row.menu_mapping_id != mapping_id:
        raise KonversiTidakDitemukan(colorplate_id)
    return row


def add_colorplate(db, mapping_id: int, platecolor: str, multiplier: int, is_active: bool = True):
    """Tambah konversi menu → warna. Warna harus ada di data COLORPLATE.

    Disimpan dengan ejaan dari data ("Blue", bukan input admin "blue ") supaya
    event yang dipublish memakai nama yang sama dengan colorplate langsung.
    """
    menu = get_by_id(db, mapping_id)
    if not menu:
        raise MenuTidakDitemukan(mapping_id)

    kunci = color_key(platecolor)
    warna = next((w for w in list_colors(db) if color_key(w) == kunci), None)
    if warna is None:
        raise WarnaTidakDikenal(platecolor)

    if any(color_key(c.platecolor) == kunci for c in menu.colorplates):
        raise WarnaSudahAda(warna)

    row = ProductMenuColorplate(
        menu_mapping_id=menu.id,
        platecolor=warna,
        multiplier=multiplier,
        is_active=is_active,
        created_at=utcnow(),
    )
    db.add(row)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise WarnaSudahAda(warna)

    db.refresh(row)
    return row


def update_colorplate(db, mapping_id: int, colorplate_id: int, multiplier: int | None = None, is_active: bool | None = None):
    """Ubah multiplier / status. Warna tidak bisa diganti — buat baris baru."""
    row = _get_colorplate(db, mapping_id, colorplate_id)

    if multiplier is not None:
        row.multiplier = multiplier
    if is_active is not None:
        row.is_active = is_active
    row.updated_at = utcnow()

    db.commit()
    db.refresh(row)
    return row


def list_candidates(db, outlet=None, product_group=None, q=None, limit=CANDIDATE_DEFAULT_LIMIT):
    """Menu yang pernah muncul di data penjualan, untuk dipilih admin.

    `outlet` hanya menyaring kandidat yang ditampilkan — mapping yang dibuat
    tetap berlaku untuk semua outlet. ProductID bisa berbeda antar outlet,
    jadi filter ini yang membuat menu outlet tertentu bisa ditemukan.

    Satu ProductID bisa muncul lebih dari sekali kalau nama / group-nya pernah
    diubah di POS — sengaja tidak disembunyikan, admin perlu melihatnya.
    """
    limit = max(1, min(limit or CANDIDATE_DEFAULT_LIMIT, CANDIDATE_MAX_LIMIT))

    group_expr = SalesService._normalized_product_group()
    name_expr = func.trim(SalesItems.product_name)

    query = (
        db.query(
            SalesItems.product_id.label("product_id"),
            name_expr.label("product_name"),
            group_expr.label("product_group"),
            Sales.outlet_code.label("outlet_code"),
            func.max(SalesItems.sale_date).label("last_sale_date"),
        )
        .join(Sales, item_join)
        .filter(SalesItems.product_id > 0)
    )

    if outlet:
        query = query.filter(Sales.outlet_code == outlet)

    normal_group = normalize_product_group(product_group)
    if normal_group:
        query = query.filter(group_expr == normal_group)

    kata = (q or "").strip()
    if kata:
        syarat = [func.upper(SalesItems.product_name).contains(kata.upper(), autoescape=True)]
        if kata.isdigit():
            syarat.append(SalesItems.product_id == int(kata))
        query = query.filter(or_(*syarat))

    rows = query.group_by(SalesItems.product_id, name_expr, group_expr, Sales.outlet_code).all()

    # Outlet digabung di Python: `string_agg` / `group_concat` berbeda antara
    # PostgreSQL dan SQLite, dan daftar kandidatnya kecil.
    gabungan: dict = {}
    for row in rows:
        kunci = (row.product_id, row.product_name, row.product_group)
        kandidat = gabungan.get(kunci)
        if kandidat is None:
            kandidat = KandidatMenu(
                product_id=row.product_id,
                product_name=row.product_name,
                product_group=row.product_group,
                last_sale_date=row.last_sale_date,
            )
            gabungan[kunci] = kandidat

        if row.outlet_code and row.outlet_code not in kandidat.outlet_codes:
            kandidat.outlet_codes.append(row.outlet_code)

        if row.last_sale_date and (
            kandidat.last_sale_date is None or row.last_sale_date > kandidat.last_sale_date
        ):
            kandidat.last_sale_date = row.last_sale_date

    for kandidat in gabungan.values():
        kandidat.outlet_codes.sort()

    # Diurutkan di Python — alasan yang sama dengan list_product_groups.
    hasil = sorted(
        gabungan.values(),
        key=lambda k: (k.product_group or "", k.product_name or "", k.product_id),
    )
    return hasil[:limit]


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
