"""Logika master data product dan mapping ProductID POS → produk master.

Dipakai route `/api/products`. ProductID dinomori POS tiap outlet, jadi yang
dipetakan adalah pasangan (outlet, ProductID). Produk master juga bisa diimpor
dari penjualan: satu produk per (brand, ProductID POS), berkode `BRAND-ProductID`.

Sama seperti master lain, tidak ada fungsi hapus: produk dan mapping dimatikan
lewat `is_active`.
"""

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from app.core.time import utcnow
from app.models.brand import Brand, OutletBrandMapping
from app.models.product import Product, ProductPosMapping
from app.models.sales import Sales
from app.models.sales_items import SalesItems
from app.services.sales_service import SalesService, item_join

MAX_PRODUCT_CODE_LENGTH = 50
MAX_PRODUCT_NAME_LENGTH = 255
MAX_CATEGORY_LENGTH = 100
MAX_SUBCATEGORY_LENGTH = 100
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
    """ProductID (`code`) sudah terdaftar — termasuk yang sedang nonaktif."""


class ProductCodeSudahAda(Exception):
    """Product Code sudah dipakai produk lain — termasuk yang sedang nonaktif."""


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


def _clean_kode(value, field: str) -> str:
    normal = normalize_product_code(value)
    if not normal:
        raise DataTidakValid(f"{field} tidak boleh kosong")
    if len(normal) > MAX_PRODUCT_CODE_LENGTH:
        raise DataTidakValid(f"{field} maksimal {MAX_PRODUCT_CODE_LENGTH} karakter")
    return normal


def _check_product_code_bebas(db, product_code: str, kecuali_id: int | None = None) -> None:
    query = db.query(Product.id).filter(Product.product_code == product_code)
    if kecuali_id is not None:
        query = query.filter(Product.id != kecuali_id)
    if query.first():
        raise ProductCodeSudahAda(product_code)


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


def _check_brand(db, brand_id: int | None) -> None:
    """Brand wajib diisi dan harus aktif."""
    if brand_id is None:
        raise DataTidakValid("brand_id tidak boleh kosong")
    brand = db.get(Brand, brand_id)
    if not brand:
        raise BrandTidakValid(f"Brand id {brand_id} tidak ditemukan")
    if not brand.is_active:
        raise BrandTidakValid(f"Brand '{brand.code}' nonaktif")


def create_product(
    db,
    code,
    product_code,
    name,
    brand_id: int | None,
    category=None,
    subcategory=None,
    is_active: bool = True,
):
    """Wajib: ProductID (`code`), Product Code, nama, dan brand. Sisanya opsional."""
    normal = _clean_kode(code, "code")
    product_code = _clean_kode(product_code, "product_code")

    row = Product(
        code=normal,
        product_code=product_code,
        name=_clean_name(name),
        category=_clean_optional(category, "category", MAX_CATEGORY_LENGTH),
        subcategory=_clean_optional(subcategory, "subcategory", MAX_SUBCATEGORY_LENGTH),
        brand_id=brand_id,
        is_active=is_active,
        created_at=utcnow(),
    )

    _check_brand(db, brand_id)
    if get_by_code(db, normal):
        raise ProdukSudahAda(normal)
    _check_product_code_bebas(db, product_code)

    db.add(row)

    try:
        db.commit()
    except IntegrityError:
        # Admin lain menyimpan ProductID / Product Code yang sama bersamaan.
        db.rollback()
        if get_by_code(db, normal):
            raise ProdukSudahAda(normal)
        raise ProductCodeSudahAda(product_code)

    db.refresh(row)
    return row


def update_product(db, product_id: int, changes: dict):
    """Ubah field yang dikirim saja. ProductID (`code`) tidak bisa diubah.

    `changes` berisi field yang benar-benar dikirim; `None` untuk category /
    subcategory berarti dikosongkan.
    """
    row = get_by_id(db, product_id)
    if not row:
        raise ProdukTidakDitemukan(product_id)

    if "product_code" in changes:
        product_code = _clean_kode(changes["product_code"], "product_code")
        _check_product_code_bebas(db, product_code, kecuali_id=row.id)
        row.product_code = product_code
    if "name" in changes:
        row.name = _clean_name(changes["name"])
    if "category" in changes:
        row.category = _clean_optional(changes["category"], "category", MAX_CATEGORY_LENGTH)
    if "subcategory" in changes:
        row.subcategory = _clean_optional(changes["subcategory"], "subcategory", MAX_SUBCATEGORY_LENGTH)
    if "brand_id" in changes:
        _check_brand(db, changes["brand_id"])
        row.brand_id = changes["brand_id"]
    if changes.get("is_active") is not None:
        row.is_active = changes["is_active"]
    row.updated_at = utcnow()

    try:
        db.commit()
    except IntegrityError:
        # Admin lain memakai Product Code yang sama bersamaan.
        db.rollback()
        raise ProductCodeSudahAda(changes.get("product_code"))
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


# ---------------------------------------------------------------------------
# Impor master data dari transaksi POS
# ---------------------------------------------------------------------------

IMPORT_CANDIDATE_DEFAULT_LIMIT = 200
IMPORT_CANDIDATE_MAX_LIMIT = 1000
IMPORT_MAX_ITEMS = 500

STATUS_IMPOR_BARU = "baru"
STATUS_IMPOR_TAMBAH_OUTLET = "tambah_outlet"
STATUS_IMPOR_BENTROK = "bentrok"


@dataclass
class KandidatImpor:
    """Satu (brand, ProductID POS) dari penjualan yang masih punya outlet belum dipetakan.

    Outlet-outlet satu brand yang menjual ProductID yang sama digabung jadi
    satu produk master berkode `BRAND-ProductID` (dipakai juga untuk Product
    Code). Nama / Group / Dept dari penjualan terakhir di brand itu.
    """

    brand_id: int
    brand_code: str
    brand_name: str
    pos_product_id: int
    pos_product_name: str | None
    pos_product_group: str | None
    pos_product_dept: str | None
    last_sale_date: date | None
    outlet_codes: list[str]
    unmapped_outlet_codes: list[str]
    proposed_code: str
    # baru | tambah_outlet | bentrok
    status: str
    existing_product_id: int | None = None
    reason: str | None = None
    # (outlet, ProductID) → (nama, group) terbaru, untuk salinan di mapping.
    info_outlet: dict = field(default_factory=dict, repr=False)


@dataclass
class HasilImpor:
    brand_id: int
    pos_product_id: int
    # dibuat | ditambahkan | dilewati
    status: str
    product_id: int | None = None
    code: str | None = None
    mapped_outlets: list[str] = field(default_factory=list)
    reason: str | None = None


def kode_impor(brand_code: str, pos_product_id: int) -> str:
    return normalize_product_code(f"{brand_code}-{pos_product_id}")


def _potong(value, max_length: int) -> str | None:
    value = (value or "").strip()
    return value[:max_length] or None


def _kandidat_impor(db, brand_id=None, q=None, pos_product_id=None) -> list[KandidatImpor]:
    """Semua kandidat, terurut kode brand lalu ProductID. Lihat `KandidatImpor`."""
    outlet_brand = {
        m.outlet_code: brand
        for m, brand in db.query(OutletBrandMapping, Brand)
        .join(Brand, Brand.id == OutletBrandMapping.brand_id)
        .filter(Brand.is_active.is_(True))
        .all()
        if brand_id is None or brand.id == brand_id
    }
    if not outlet_brand:
        return []

    group_expr = SalesService._normalized_product_group()
    name_expr = func.trim(SalesItems.product_name)
    dept_expr = func.trim(SalesItems.product_dept)

    query = (
        db.query(
            Sales.outlet_code.label("outlet_code"),
            SalesItems.product_id.label("product_id"),
            name_expr.label("product_name"),
            group_expr.label("product_group"),
            dept_expr.label("product_dept"),
            func.max(SalesItems.sale_date).label("last_sale_date"),
            func.max(SalesItems.transaction_id).label("last_transaction_id"),
        )
        .join(Sales, item_join)
        .filter(SalesItems.product_id > 0, Sales.outlet_code.in_(sorted(outlet_brand)))
    )
    if pos_product_id is not None:
        query = query.filter(SalesItems.product_id == pos_product_id)

    kata = (q or "").strip()
    if kata:
        syarat = [func.upper(SalesItems.product_name).contains(kata.upper(), autoescape=True)]
        if kata.isdigit():
            syarat.append(SalesItems.product_id == int(kata))
        query = query.filter(or_(*syarat))

    rows = query.group_by(Sales.outlet_code, SalesItems.product_id, name_expr, group_expr, dept_expr).all()

    # Per (outlet, ProductID): varian nama terakhir. Per (brand, ProductID): yang terakhir di brand itu.
    per_outlet: dict = {}
    for row in rows:
        kunci = (row.outlet_code, row.product_id)
        urutan = (row.last_sale_date or date.min, row.last_transaction_id or 0)
        if kunci not in per_outlet or urutan > per_outlet[kunci][0]:
            per_outlet[kunci] = (urutan, row)

    per_brand: dict = {}
    for (outlet, pid), (urutan, row) in per_outlet.items():
        brand = outlet_brand[outlet]
        grup = per_brand.setdefault((brand.id, pid), {"brand": brand, "outlet": {}, "terbaru": None})
        grup["outlet"][outlet] = row
        if grup["terbaru"] is None or urutan > grup["terbaru"][0]:
            grup["terbaru"] = (urutan, row)

    aktif = {
        (m.outlet_code, m.pos_product_id)
        for m in db.query(ProductPosMapping.outlet_code, ProductPosMapping.pos_product_id)
        .filter(ProductPosMapping.is_active.is_(True))
        .all()
    }

    usulan = {kode_impor(g["brand"].code, pid) for (_, pid), g in per_brand.items()}
    produk_per_kode = {p.code: p for p in db.query(Product).filter(Product.code.in_(usulan)).all()}
    kode_dipakai = {
        pc: pid for pc, pid in db.query(Product.product_code, Product.id).filter(Product.product_code.in_(usulan)).all()
    }

    hasil = []
    for (b_id, pid), grup in sorted(per_brand.items(), key=lambda x: (x[1]["brand"].code, x[0][1])):
        outlets = sorted(grup["outlet"])
        belum = [o for o in outlets if (o, pid) not in aktif]
        if not belum:
            continue

        brand = grup["brand"]
        terbaru = grup["terbaru"][1]
        kode = kode_impor(brand.code, pid)
        status, existing_id, alasan = STATUS_IMPOR_BARU, None, None

        produk = produk_per_kode.get(kode)
        if produk is not None:
            existing_id = produk.id
            if not produk.is_active:
                status, alasan = STATUS_IMPOR_BENTROK, f"Produk {kode} sudah ada tetapi nonaktif"
            elif produk.brand_id != b_id:
                status, alasan = STATUS_IMPOR_BENTROK, f"Produk {kode} sudah ada dengan brand lain"
            else:
                status = STATUS_IMPOR_TAMBAH_OUTLET
        elif kode in kode_dipakai:
            status, alasan = STATUS_IMPOR_BENTROK, f"Product Code {kode} sudah dipakai produk lain"

        hasil.append(
            KandidatImpor(
                brand_id=b_id,
                brand_code=brand.code,
                brand_name=brand.name,
                pos_product_id=pid,
                pos_product_name=terbaru.product_name or None,
                pos_product_group=terbaru.product_group or None,
                pos_product_dept=terbaru.product_dept or None,
                last_sale_date=terbaru.last_sale_date,
                outlet_codes=outlets,
                unmapped_outlet_codes=belum,
                proposed_code=kode,
                status=status,
                existing_product_id=existing_id,
                reason=alasan,
                info_outlet={
                    o: (grup["outlet"][o].product_name or None, grup["outlet"][o].product_group or None)
                    for o in belum
                },
            )
        )
    return hasil


def list_import_candidates(db, brand_id=None, q=None, limit=IMPORT_CANDIDATE_DEFAULT_LIMIT) -> list[KandidatImpor]:
    limit = max(1, min(limit or IMPORT_CANDIDATE_DEFAULT_LIMIT, IMPORT_CANDIDATE_MAX_LIMIT))
    return _kandidat_impor(db, brand_id=brand_id, q=q)[:limit]


def _petakan_outlet(db, product: Product, kandidat: KandidatImpor) -> list[str]:
    """Petakan outlet kandidat yang belum aktif ke produk; baris nonaktif dipakai ulang."""
    sekarang = utcnow()
    for outlet in kandidat.unmapped_outlet_codes:
        nama, grup = kandidat.info_outlet[outlet]
        row = (
            db.query(ProductPosMapping)
            .filter(
                ProductPosMapping.outlet_code == outlet,
                ProductPosMapping.pos_product_id == kandidat.pos_product_id,
            )
            .first()
        )
        if row is None:
            row = ProductPosMapping(outlet_code=outlet, pos_product_id=kandidat.pos_product_id, created_at=sekarang)
            db.add(row)
        else:
            row.updated_at = sekarang
        row.product_id = product.id
        row.pos_product_name = nama
        row.pos_product_group = grup
        row.is_active = True
    return list(kandidat.unmapped_outlet_codes)


def import_from_pos(db, items: list[tuple[int, int]]) -> list[HasilImpor]:
    """Buat produk master (atau tambah outlet ke produk yang sudah ada) dari penjualan.

    `items` = [(brand_id, pos_product_id)]. Kandidat dihitung ulang di sini —
    pilihan dari layar bisa sudah basi. Tiap item di savepoint sendiri: yang
    gagal dilewati tanpa membatalkan yang lain. Satu commit di akhir.
    """
    hasil = []
    for brand_id, pid in dict.fromkeys(items):
        [kandidat] = _kandidat_impor(db, brand_id=brand_id, pos_product_id=pid) or [None]
        if kandidat is None:
            hasil.append(
                HasilImpor(brand_id, pid, "dilewati", reason="Tidak ada outlet brand ini yang belum dipetakan")
            )
            continue
        if kandidat.status == STATUS_IMPOR_BENTROK:
            hasil.append(
                HasilImpor(
                    brand_id, pid, "dilewati", product_id=kandidat.existing_product_id, reason=kandidat.reason
                )
            )
            continue

        savepoint = db.begin_nested()
        try:
            if kandidat.status == STATUS_IMPOR_TAMBAH_OUTLET:
                product = db.get(Product, kandidat.existing_product_id)
                status = "ditambahkan"
            else:
                product = Product(
                    code=kandidat.proposed_code,
                    product_code=kandidat.proposed_code,
                    name=_potong(kandidat.pos_product_name, MAX_PRODUCT_NAME_LENGTH) or f"ProductID {pid}",
                    category=_potong(kandidat.pos_product_group, MAX_CATEGORY_LENGTH),
                    subcategory=_potong(kandidat.pos_product_dept, MAX_SUBCATEGORY_LENGTH),
                    brand_id=brand_id,
                    is_active=True,
                    created_at=utcnow(),
                )
                db.add(product)
                db.flush()
                status = "dibuat"
            outlets = _petakan_outlet(db, product, kandidat)
            db.flush()
            savepoint.commit()
        except IntegrityError:
            # Admin lain mengimpor / memetakan yang sama bersamaan.
            savepoint.rollback()
            hasil.append(HasilImpor(brand_id, pid, "dilewati", reason="Bentrok dengan perubahan lain, coba lagi"))
            continue

        hasil.append(HasilImpor(brand_id, pid, status, product_id=product.id, code=product.code, mapped_outlets=outlets))

    db.commit()
    return hasil
