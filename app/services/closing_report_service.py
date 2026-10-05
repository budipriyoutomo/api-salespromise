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

STATUS_COCOK = "cocok"
STATUS_SELISIH = "selisih"
STATUS_BELUM_DIPETAKAN = "belum_dipetakan"
STATUS_TIDAK_ADA_DI_CLOSING = "tidak_ada_di_closing"


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
    hasil["items"] = sorted(aktif.items, key=lambda i: (i.production_date, i.menu_code)) if aktif else []
    # Terbaru dulu.
    hasil["revisions"] = sorted(laporan.revisions, key=lambda r: (r.sent_at, r.id), reverse=True)
    return hasil


@dataclass
class MenuPerbandingan:
    menu_id: object
    menu_code: str | None
    menu_name: str
    # Pengali mapping; None untuk menu yang belum dipetakan.
    multiplier: int | None
    sold: int
    waste: int
    adjustment: int
    compensation: int


@dataclass
class BarisPerbandingan:
    outlet_code: str
    production_date: date
    # None = baris menu yang belum dipetakan.
    product_id: int | None
    product_name: str | None
    menus: list[MenuPerbandingan]
    # Σ (sold + adjustment + compensation) × pengali; None kalau tidak ada di closing.
    closing_qty: int | None
    pos_qty: float | None
    # qty POS − closing (rumus pengirim).
    selisih: float | None
    status: str


def _total_closing(c) -> int:
    """Rumus rekonsiliasi pengirim: sold + adjustment + compensation."""
    return int(c.sold) + int(c.adjustment) + int(c.compensation)


def compare_with_pos(db, outlet=None, start_date=None, end_date=None, include_deleted=False) -> list[BarisPerbandingan]:
    """Closing (revisi aktif) vs penjualan POS, per outlet / tanggal produksi / ProductID.

    Diputuskan 2026-10-05 setelah jawaban pengirim (POS menjual sushi per warna
    piring, jadi beberapa menu bisa berbagi satu produk POS):

        closing(produk) = Σ menu yang dipetakan ke produk itu:
                              (sold + adjustment + compensation) × pengali
        selisih         = qty POS − closing(produk)

    - Tanggal produksi item dicocokkan dengan tanggal transaksi POS; item tanpa
      tanggal produksi memakai tanggal closing.
    - Menu yang belum dipetakan muncul sebagai baris sendiri (`belum_dipetakan`).
    - Hanya pasangan (outlet, tanggal) yang punya closing yang ditampilkan.
    - Produk terpetakan yang terjual di POS tanpa satu pun menunya di closing
      tampil sebagai `tidak_ada_di_closing`.
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
    menus = {m.menu_id: m for m in db.query(ClosingMenu).all()}
    pos = _qty_pos(db, mapping, pasangan, include_deleted)

    # product_id → [(menu_id, multiplier)], dan nama produk dari snapshot mapping.
    menu_per_produk: dict[int, list] = {}
    nama_produk: dict[int, str | None] = {}
    for menu_id, produk in mapping.items():
        for product_id, mult, nama in produk:
            menu_per_produk.setdefault(product_id, []).append((menu_id, mult))
            nama_produk.setdefault(product_id, nama)
    # Snapshot nama kosong → nama terakhir di data penjualan.
    for product_id, nama in list(nama_produk.items()):
        if not nama:
            info = product_menu_service._info_terbaru(db, product_id)
            nama_produk[product_id] = (info.product_name or None) if info else None

    def info_menu(menu_id, c, mult):
        m = menus.get(menu_id)
        return MenuPerbandingan(
            menu_id=menu_id,
            menu_code=m.menu_code if m else None,
            menu_name=m.menu_name if m else str(menu_id),
            multiplier=mult,
            sold=int(c.sold),
            waste=int(c.waste),
            adjustment=int(c.adjustment),
            compensation=int(c.compensation),
        )

    hasil = []
    for o, d in sorted(pasangan):
        for product_id in sorted(menu_per_produk):
            ikut = [
                (menu_id, mult, closing[(o, d, menu_id)])
                for menu_id, mult in menu_per_produk[product_id]
                if (o, d, menu_id) in closing
            ]
            pos_qty = pos.get((o, d, product_id), 0.0)
            if not ikut and not pos_qty:
                continue

            if ikut:
                closing_qty = sum(_total_closing(c) * mult for _, mult, c in ikut)
                selisih = pos_qty - closing_qty
                status = STATUS_COCOK if selisih == 0 else STATUS_SELISIH
            else:
                closing_qty, selisih, status = None, None, STATUS_TIDAK_ADA_DI_CLOSING

            hasil.append(
                BarisPerbandingan(
                    outlet_code=o,
                    production_date=d,
                    product_id=product_id,
                    product_name=nama_produk.get(product_id),
                    menus=sorted(
                        (info_menu(menu_id, c, mult) for menu_id, mult, c in ikut),
                        key=lambda m: (m.menu_name, str(m.menu_id)),
                    ),
                    closing_qty=closing_qty,
                    pos_qty=pos_qty,
                    selisih=selisih,
                    status=status,
                )
            )

        belum = [
            info_menu(menu_id, c, None)
            for (oo, dd, menu_id), c in closing.items()
            if (oo, dd) == (o, d) and menu_id not in mapping
        ]
        for m in sorted(belum, key=lambda m: (m.menu_name, str(m.menu_id))):
            hasil.append(
                BarisPerbandingan(
                    outlet_code=o,
                    production_date=d,
                    product_id=None,
                    product_name=None,
                    menus=[m],
                    closing_qty=m.sold + m.adjustment + m.compensation,
                    pos_qty=None,
                    selisih=None,
                    status=STATUS_BELUM_DIPETAKAN,
                )
            )
    return hasil


def _qty_pos(db, mapping, pasangan, include_deleted) -> dict:
    """(outlet, tanggal, product_id) → qty POS, hanya untuk pasangan yang punya closing."""
    product_ids = sorted({pid for produk in mapping.values() for pid, _, _ in produk})
    if not product_ids:
        return {}

    tanggal = [d for _, d in pasangan]
    query = (
        db.query(SalesItems.product_id, Sales.outlet_code, Sales.sale_date, func.sum(SalesItems.qty).label("qty"))
        .join(Sales, item_join)
        .filter(
            SalesItems.product_id.in_(product_ids),
            Sales.outlet_code.in_(sorted({o for o, _ in pasangan})),
            Sales.sale_date >= min(tanggal),
            Sales.sale_date <= max(tanggal),
        )
    )
    query = SalesService._active_sales(query, include_deleted=include_deleted)

    hasil = {}
    for row in query.group_by(SalesItems.product_id, Sales.outlet_code, Sales.sale_date):
        if (row.outlet_code, row.sale_date) in pasangan:
            hasil[(row.outlet_code, row.sale_date, row.product_id)] = float(row.qty or 0)
    return hasil
