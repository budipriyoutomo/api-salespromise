"""Logika mapping product group — group mana yang dipublish ke RabbitMQ.

Dipakai route `/api/product-groups` (kelola) dan `/api/sales/publish` (membaca
group aktif). Menggantikan literal `"COLORPLATE"` yang dulu tertanam di query.

Tidak ada fungsi hapus, dan itu disengaja: group yang tidak dipakai lagi
dimatikan lewat `is_active`. Barisnya tetap ada sebagai jejak group apa saja
yang pernah dipublish.
"""

from sqlalchemy.exc import IntegrityError

from app.core.time import utcnow
from app.models.product_group_mapping import ProductGroupMapping

# Sama dengan panjang kolom "Group" di orderdetail.
MAX_PRODUCT_GROUP_LENGTH = 255


class GroupSudahAda(Exception):
    """Group sudah terdaftar — termasuk yang sedang nonaktif."""


class GroupTidakDitemukan(Exception):
    pass


class DataTidakValid(Exception):
    pass


def normalize_product_group(value) -> str:
    """Bentuk pembanding nama group: tanpa spasi di ujung, huruf besar.

    Sengaja hanya membuang SPASI (`strip(" ")`), bukan semua whitespace —
    harus sama persis dengan `UPPER(TRIM("Group"))` di query, yang di
    PostgreSQL maupun SQLite hanya membuang spasi. Kalau keduanya berbeda,
    nama yang tersimpan di mapping tidak akan pernah cocok dengan data.
    """
    if value is None:
        return ""
    return value.strip(" ").upper()


def list_mappings(db):
    return db.query(ProductGroupMapping).order_by(ProductGroupMapping.product_group).all()


def get_by_id(db, mapping_id: int):
    return db.get(ProductGroupMapping, mapping_id)


def get_by_group(db, product_group: str):
    return (
        db.query(ProductGroupMapping)
        .filter(ProductGroupMapping.product_group == normalize_product_group(product_group))
        .first()
    )


def get_active_groups(db) -> list[str]:
    """Nama group aktif, terurut — daftar yang dipublish ke RabbitMQ."""
    rows = (
        db.query(ProductGroupMapping.product_group)
        .filter(ProductGroupMapping.is_active.is_(True))
        .order_by(ProductGroupMapping.product_group)
        .all()
    )
    return [row.product_group for row in rows]


def create_mapping(db, product_group, is_active: bool = True):
    normal = normalize_product_group(product_group)

    if not normal:
        raise DataTidakValid("product_group tidak boleh kosong")

    if len(normal) > MAX_PRODUCT_GROUP_LENGTH:
        raise DataTidakValid(f"product_group maksimal {MAX_PRODUCT_GROUP_LENGTH} karakter")

    if get_by_group(db, normal):
        raise GroupSudahAda(normal)

    row = ProductGroupMapping(product_group=normal, is_active=is_active, created_at=utcnow())
    db.add(row)

    try:
        db.commit()
    except IntegrityError:
        # Dua admin menambahkan group yang sama bersamaan: pengecekan di atas
        # lolos untuk keduanya, unique constraint yang menangkap sisanya.
        db.rollback()
        raise GroupSudahAda(normal)

    db.refresh(row)
    return row


def set_active(db, mapping_id: int, is_active: bool):
    row = get_by_id(db, mapping_id)

    if not row:
        raise GroupTidakDitemukan(mapping_id)

    row.is_active = is_active
    row.updated_at = utcnow()

    db.commit()
    db.refresh(row)

    return row
