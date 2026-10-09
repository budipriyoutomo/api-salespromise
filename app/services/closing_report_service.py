"""Penyimpanan closing report dari RabbitMQ (`closingreport.submitted`) — TODO Fase 7.

Tidak ada baris yang dihapus. Aturan per pesan (jawaban pengirim 2026-10-05,
docs/jawaban-pengirim-closing.md):

    messageId sudah tersimpan           → DUPLIKAT, tidak ada yang berubah.
                                          Retry pengirim membawa sentAt baru
                                          dengan isi identik, jadi sentAt tidak
                                          ikut menentukan duplikat.
    messageId baru, sentAt >= aktif     → REVISI, revisi lama is_current = FALSE
    messageId baru, sentAt <  aktif     → REVISI_LAMA, disimpan tapi tidak aktif

Saat ini pengirim tidak punya alur revisi (messageId = closingReportId), jadi
praktis hanya BARU / DUPLIKAT yang terjadi. Jalur revisi dipertahankan untuk
`version` berikutnya.

Menu yang belum pernah terlihat otomatis masuk `closing_menus` — kuncinya
menuId; menuCode hanya atribut (bisa berubah, unik per brand, bisa null).

Kode outlet dicocokkan ke `api_keys.outlet_code` setelah normalisasi (huruf
kecil, hanya alfanumerik) dan disimpan dengan kode POS, supaya perbandingan
dengan penjualan cukup mencocokkan persis.
"""

import re
from dataclasses import dataclass
from datetime import date
from enum import Enum

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.core.time import utcnow
from app.models.api_key import ApiKey
from app.models.closing_report import (
    ClosingMenu,
    ClosingReport,
    ClosingReportItem,
    ClosingReportRevision,
)
from app.models.sales import Sales
from app.models.sales_items import SalesItems
from app.schemas.closing_report_event import ClosingReportSubmitted
from app.services import closing_menu_service, product_menu_service
from app.services.sales_service import SalesService, item_join

# Dua consumer bisa menyimpan laporan / menu yang sama bersamaan; yang kalah
# kena unique constraint dan cukup mengulang sekali — percobaan kedua melihat
# baris yang sudah di-commit pemenangnya.
MAX_PERCOBAAN = 2


class StatusSimpan(str, Enum):
    BARU = "baru"
    REVISI = "revisi"
    REVISI_LAMA = "revisi_lama"
    DUPLIKAT = "duplikat"


@dataclass
class HasilSimpan:
    status: StatusSimpan
    report_id: int
    revision_id: int
    # Outlet belum ada di api_keys — tetap disimpan, hanya untuk log.
    outlet_dikenal: bool


def simpan_closing_report(db, event: ClosingReportSubmitted, raw_payload: dict) -> HasilSimpan:
    """Simpan satu pesan dalam satu transaksi, lalu commit.

    `raw_payload` adalah JSON pesan apa adanya, disimpan untuk audit.
    """
    for percobaan in range(1, MAX_PERCOBAAN + 1):
        try:
            hasil = _simpan(db, event, raw_payload)
            db.commit()
            return hasil
        except IntegrityError:
            db.rollback()
            if percobaan == MAX_PERCOBAAN:
                raise


def normalisasi_kode_outlet(kode: str) -> str:
    """Sama dengan cara pengirim mencocokkan data POS: huruf kecil, hanya alfanumerik."""
    return re.sub(r"[^a-z0-9]", "", (kode or "").lower())


def _kode_outlet_pos(db, kode: str) -> str | None:
    """Kode outlet POS (`api_keys`) yang cocok setelah normalisasi, atau None."""
    dicari = normalisasi_kode_outlet(kode)
    if not dicari:
        return None
    for (kode_pos,) in db.query(ApiKey.outlet_code).all():
        if normalisasi_kode_outlet(kode_pos) == dicari:
            return kode_pos
    return None


def _simpan(db, event: ClosingReportSubmitted, raw_payload: dict) -> HasilSimpan:
    data = event.data
    kode_pos = _kode_outlet_pos(db, data.outlet.code)
    outlet_dikenal = kode_pos is not None
    # Outlet yang belum terdaftar disimpan apa adanya (keputusan 7.0 no. 5).
    kode_outlet = kode_pos or data.outlet.code

    # FOR UPDATE: revisi untuk laporan yang sama diproses bergantian.
    laporan = (
        db.query(ClosingReport)
        .filter(ClosingReport.closing_report_id == data.closing_report_id)
        .with_for_update()
        .first()
    )

    if laporan is None:
        laporan = ClosingReport(closing_report_id=data.closing_report_id)
        _isi_header(laporan, event, kode_outlet)
        db.add(laporan)
        db.flush()
        status = StatusSimpan.BARU
    else:
        sama = (
            db.query(ClosingReportRevision)
            .filter(
                ClosingReportRevision.report_id == laporan.id,
                ClosingReportRevision.message_id == event.message_id,
            )
            .first()
        )
        if sama is not None:
            return HasilSimpan(StatusSimpan.DUPLIKAT, laporan.id, sama.id, outlet_dikenal)

        aktif = (
            db.query(ClosingReportRevision)
            .filter(ClosingReportRevision.report_id == laporan.id, ClosingReportRevision.is_current.is_(True))
            .first()
        )
        if aktif is None or event.sent_at >= aktif.sent_at:
            status = StatusSimpan.REVISI
            if aktif is not None:
                aktif.is_current = False
                # Flush dulu: index unik revisi aktif menolak dua baris aktif
                # walau hanya sesaat.
                db.flush()
            _isi_header(laporan, event, kode_outlet)
            laporan.updated_at = utcnow()
        else:
            status = StatusSimpan.REVISI_LAMA

    revisi = ClosingReportRevision(
        report_id=laporan.id,
        message_id=event.message_id,
        version=event.version,
        sent_at=event.sent_at,
        is_current=status is not StatusSimpan.REVISI_LAMA,
        raw_payload=raw_payload,
    )
    db.add(revisi)
    db.flush()

    db.add_all(
        ClosingReportItem(
            revision_id=revisi.id,
            menu_id=item.menu_id,
            menu_code=item.menu_code,
            menu_name=item.menu_name,
            production_date=item.production_date,
            sold=item.sold,
            waste=item.waste,
            adjustment=item.adjustment,
            compensation=item.compensation,
        )
        for item in data.items
    )

    _catat_menu(db, event, perbarui_nama=status is not StatusSimpan.REVISI_LAMA)
    db.flush()

    return HasilSimpan(status, laporan.id, revisi.id, outlet_dikenal)


def _isi_header(laporan: ClosingReport, event: ClosingReportSubmitted, kode_outlet: str):
    data = event.data
    laporan.report_date = data.date
    laporan.outlet_code = kode_outlet
    laporan.outlet_name = data.outlet.name
    laporan.brand_code = data.brand.code
    laporan.brand_name = data.brand.name


def _catat_menu(db, event: ClosingReportSubmitted, perbarui_nama: bool):
    """Daftarkan menuId baru; mapping ke ProductID tidak disentuh.

    Revisi lama hanya memperbarui `last_seen_at`, supaya kode & nama menu yang
    tampil tetap dari pesan terbaru.
    """
    # Satu menu bisa muncul beberapa kali (tanggal produksi berbeda); yang
    # terakhir di pesan dipakai.
    per_id = {item.menu_id: item for item in event.data.items}
    brand = event.data.brand.code
    sekarang = utcnow()

    ada = {m.menu_id: m for m in db.query(ClosingMenu).filter(ClosingMenu.menu_id.in_(per_id)).all()}

    for menu_id, item in per_id.items():
        menu = ada.get(menu_id)
        if menu is None:
            db.add(
                ClosingMenu(
                    menu_id=menu_id,
                    menu_code=item.menu_code,
                    menu_name=item.menu_name,
                    brand_code=brand,
                    first_seen_at=sekarang,
                    last_seen_at=sekarang,
                )
            )
            continue

        menu.last_seen_at = sekarang
        if perbarui_nama:
            menu.menu_code = item.menu_code
            menu.menu_name = item.menu_name
            menu.brand_code = brand


# ---------------------------------------------------------------------------
# Baca — dashboard (TODO 7.6)
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def _ringkasan(laporan: ClosingReport) -> dict:
    aktif = next((r for r in laporan.revisions if r.is_current), None)
    return {
        "closing_report_id": laporan.closing_report_id,
        "report_date": laporan.report_date,
        "outlet_code": laporan.outlet_code,
        "outlet_name": laporan.outlet_name,
        "brand_code": laporan.brand_code,
        "brand_name": laporan.brand_name,
        "sent_at": aktif.sent_at if aktif else None,
        "received_at": aktif.received_at if aktif else None,
        "revision_count": len(laporan.revisions),
        "item_count": aktif.item_count if aktif else 0,
    }


def _filter_laporan(query, outlet=None, start_date=None, end_date=None):
    if outlet:
        query = query.filter(ClosingReport.outlet_code == outlet)
    if start_date:
        query = query.filter(ClosingReport.report_date >= start_date)
    if end_date:
        query = query.filter(ClosingReport.report_date <= end_date)
    return query


def list_reports(db, outlet=None, start_date=None, end_date=None, limit=DEFAULT_LIMIT, offset=0):
    """Ringkasan laporan, terbaru dulu. Mengembalikan (baris, total)."""
    query = _filter_laporan(db.query(ClosingReport), outlet, start_date, end_date)
    total = query.count()
    rows = (
        query.order_by(ClosingReport.report_date.desc(), ClosingReport.outlet_code, ClosingReport.id)
        .limit(limit)
        .offset(offset)
        .all()
    )
    return [_ringkasan(r) for r in rows], total


def _urutan_item(i: ClosingReportItem):
    # production_date / menu_code boleh null (migrasi 012): tanpa tanggal di
    # depan, tanpa kode di belakang.
    return (i.production_date or date.min, i.menu_code is None, i.menu_code or "", i.menu_name)


def get_report(db, closing_report_id, outlet=None) -> dict | None:
    """Detail laporan. Laporan outlet lain dianggap tidak ada (404, bukan 403)."""
    laporan = (
        _filter_laporan(db.query(ClosingReport), outlet)
        .filter(ClosingReport.closing_report_id == closing_report_id)
        .first()
    )
    if laporan is None:
        return None

    aktif = next((r for r in laporan.revisions if r.is_current), None)
    hasil = _ringkasan(laporan)
    hasil["items"] = sorted(aktif.items, key=_urutan_item) if aktif else []
    # Terbaru dulu.
    hasil["revisions"] = sorted(laporan.revisions, key=lambda r: (r.sent_at, r.id), reverse=True)
    return hasil


@dataclass
class ProdukPerbandingan:
    product_id: int
    product_name: str | None
    # Group POS (dinormalisasi) dari penjualan di rentang ini; None kalau tidak terjual.
    product_group: str | None
    multiplier: int
    # Dipetakan ke salah satu menu colorplate (mapping aktif).
    is_mapped: bool


@dataclass
class BarisPerbandingan:
    """Satu menu colorplate per outlet & tanggal produksi, berdampingan dengan POS.

    Baris tanpa menu (`menu_id` None, angka colorplate None) = produk POS yang
    terjual tetapi qty-nya tidak tampil di baris menu mana pun — belum
    dipetakan, bukan colorplate, atau menunya tidak ada di colorplate hari itu.
    """

    outlet_code: str
    production_date: date
    menu_id: object | None
    menu_code: str | None
    menu_name: str | None
    sold: int | None
    waste: int | None
    adjustment: int | None
    compensation: int | None
    # Mapping aktif menu ini (atau satu produk untuk baris tanpa menu); kosong = belum dipetakan.
    products: list[ProdukPerbandingan]
    # Σ qty orderdetail produk-produk di atas; None kalau belum dipetakan.
    pos_qty: float | None


def compare_with_pos(db, outlet=None, start_date=None, end_date=None, include_deleted=False) -> list[BarisPerbandingan]:
    """Colorplate (revisi aktif) vs POS, per outlet / tanggal produksi / menu.

    Angka colorplate (sold, waste, adjustment, compensation) ditampilkan apa
    adanya. POS = Σ qty `orderdetail` dengan outlet & tanggal yang sama untuk
    ProductID yang dipetakan ke menu itu di `/closing-menu` — qty mentah POS,
    pengali mapping tidak diterapkan. Produk yang dipetakan ke beberapa menu
    muncul dengan qty POS yang sama di setiap menunya.

    - Tanggal produksi item dicocokkan dengan tanggal transaksi POS; item tanpa
      tanggal produksi memakai tanggal closing.
    - Menu yang belum dipetakan tetap tampil dengan `pos_qty` kosong.
    - Setiap produk POS yang terjual di outlet/tanggal itu tetapi qty-nya tidak
      tampil di baris menu mana pun — belum dipetakan, bukan colorplate, atau
      menunya tidak ada di colorplate — tampil sebagai baris tanpa menu, supaya
      kedua sistem bisa dikonsolidasi.
    - Hanya pasangan (outlet, tanggal) yang punya colorplate yang ditampilkan.
    - Transaksi `Deleted=1` dibuang kecuali `include_deleted`.
    """
    tanggal = func.coalesce(ClosingReportItem.production_date, ClosingReport.report_date)
    query = (
        db.query(
            ClosingReport.outlet_code,
            tanggal.label("tanggal"),
            ClosingReportItem.menu_id,
            func.sum(ClosingReportItem.sold).label("sold"),
            func.sum(ClosingReportItem.waste).label("waste"),
            func.sum(ClosingReportItem.adjustment).label("adjustment"),
            func.sum(ClosingReportItem.compensation).label("compensation"),
        )
        .join(ClosingReportRevision, ClosingReportRevision.report_id == ClosingReport.id)
        .join(ClosingReportItem, ClosingReportItem.revision_id == ClosingReportRevision.id)
        .filter(ClosingReportRevision.is_current.is_(True))
    )
    if outlet:
        query = query.filter(ClosingReport.outlet_code == outlet)
    if start_date:
        query = query.filter(tanggal >= start_date)
    if end_date:
        query = query.filter(tanggal <= end_date)

    # Beberapa closing untuk outlet & tanggal yang sama dijumlah.
    closing = {}
    for r in query.group_by(ClosingReport.outlet_code, tanggal, ClosingReportItem.menu_id):
        # SQLite mengembalikan hasil COALESCE tanggal sebagai teks.
        d = r.tanggal if isinstance(r.tanggal, date) else date.fromisoformat(str(r.tanggal))
        closing[(r.outlet_code, d, r.menu_id)] = r
    if not closing:
        return []

    pasangan = {(o, d) for o, d, _ in closing}
    mapping = closing_menu_service.active_mappings(db)
    menus = {m.menu_id: m for m in db.query(ClosingMenu).filter(ClosingMenu.menu_id.in_({k[2] for k in closing})).all()}
    pos, info_pos = _penjualan_pos(db, pasangan, include_deleted)

    # Nama: snapshot mapping → penjualan di rentang ini → penjualan terakhir.
    nama_produk: dict[int, str | None] = {pid: nama for pid, (nama, _) in info_pos.items()}
    for produk in mapping.values():
        for product_id, _, nama in produk:
            if nama:
                nama_produk[product_id] = nama
    terpetakan = {pid for produk in mapping.values() for pid, _, _ in produk}
    for product_id in terpetakan:
        if not nama_produk.get(product_id):
            info = product_menu_service._info_terbaru(db, product_id)
            nama_produk[product_id] = (info.product_name or None) if info else None

    def info_produk(product_id, multiplier):
        return ProdukPerbandingan(
            product_id=product_id,
            product_name=nama_produk.get(product_id),
            product_group=info_pos.get(product_id, (None, None))[1],
            multiplier=multiplier,
            is_mapped=product_id in terpetakan,
        )

    hasil = []
    for (o, d, menu_id), c in closing.items():
        m = menus.get(menu_id)
        produk = [info_produk(pid, mult) for pid, mult, _ in mapping.get(menu_id, [])]
        pos_qty = sum(pos.get((o, d, p.product_id), 0.0) for p in produk) if produk else None
        hasil.append(
            BarisPerbandingan(
                outlet_code=o,
                production_date=d,
                menu_id=menu_id,
                menu_code=m.menu_code if m else None,
                menu_name=m.menu_name if m else str(menu_id),
                sold=int(c.sold),
                waste=int(c.waste),
                adjustment=int(c.adjustment),
                compensation=int(c.compensation),
                products=produk,
                pos_qty=pos_qty,
            )
        )

    # Produk yang qty POS-nya belum tampil di baris menu mana pun.
    tampil = {(b.outlet_code, b.production_date, p.product_id) for b in hasil for p in b.products}
    for (o, d, product_id), qty in pos.items():
        if (o, d, product_id) in tampil or not qty:
            continue
        hasil.append(
            BarisPerbandingan(
                outlet_code=o,
                production_date=d,
                menu_id=None,
                menu_code=None,
                menu_name=None,
                sold=None,
                waste=None,
                adjustment=None,
                compensation=None,
                # Pengali milik pasangan menu–produk; tanpa menu tidak ada yang berlaku.
                products=[info_produk(product_id, 1)],
                pos_qty=qty,
            )
        )

    # Baris tanpa menu di belakang menu-menu outlet/tanggal yang sama, urut nama produk.
    def urutan(b):
        if b.menu_id is None:
            p = b.products[0]
            return (b.production_date, b.outlet_code, True, p.product_name or "", p.product_id, "")
        return (b.production_date, b.outlet_code, False, b.menu_name or "", 0, str(b.menu_id))

    hasil.sort(key=urutan)
    return hasil


def _penjualan_pos(db, pasangan, include_deleted) -> tuple[dict, dict]:
    """Semua produk POS yang terjual pada pasangan (outlet, tanggal) yang punya closing.

    Mengembalikan ((outlet, tanggal, product_id) → qty, product_id → (nama, group)).
    """
    tanggal = [d for _, d in pasangan]
    query = (
        db.query(
            SalesItems.product_id,
            Sales.outlet_code,
            Sales.sale_date,
            func.sum(SalesItems.qty).label("qty"),
            func.max(func.trim(SalesItems.product_name)).label("nama"),
            func.max(SalesService._normalized_product_group()).label("grup"),
        )
        .join(Sales, item_join)
        .filter(
            Sales.outlet_code.in_(sorted({o for o, _ in pasangan})),
            Sales.sale_date >= min(tanggal),
            Sales.sale_date <= max(tanggal),
        )
    )
    query = SalesService._active_sales(query, include_deleted=include_deleted)

    qty, info = {}, {}
    for row in query.group_by(SalesItems.product_id, Sales.outlet_code, Sales.sale_date):
        if (row.outlet_code, row.sale_date) not in pasangan:
            continue
        qty[(row.outlet_code, row.sale_date, row.product_id)] = float(row.qty or 0)
        nama, grup = info.get(row.product_id, (None, None))
        info[row.product_id] = (nama or row.nama or None, grup or row.grup or None)
    return qty, info
