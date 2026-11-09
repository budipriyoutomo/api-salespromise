"""Kirim rekap closing ke API eksternal (TODO Fase 8).

Kontrak: docs/usulan-kontrak-kirim-closing.md. Keputusan: TODO.md Fase 8.0,
perbaikan rekap: todo_perbaikan.md.

Satu kiriman = satu outlet × satu tanggal produksi. Void tidak pernah dihitung.

    closing   satu item per menu closing (dari `compare_with_pos`):
              colorplateSold = sold, posQty = qty POS mentah (tanpa pengali)
    pos_only  produk POS NON-colorplate yang tidak dipetakan ke menu closing,
              memakai identitas master `products` (code, product_code, name).
              Beberapa ProductID POS ke satu master dijumlah. colorplateSold = 0.
    totalSold = colorplateSold + posQty; waste / adjustment / compensation
                dari colorplate saja. Angka kosong = 0.

Produk colorplate — group COLORPLATE aktif, atau ProductID yang punya konversi
warna aktif (`colorplate_publish_service.aturan_colorplate`) — TIDAK dikirim
sebagai item: penjualannya sudah terwakili `sold` menu closing.

Outlet yang brand-nya `requires_closing = FALSE` (migrasi 019) boleh dikirim
tanpa closing report: isinya hanya item `pos_only`. Outlet tanpa brand tetap
wajib closing.

Diblokir kalau:
- menu closing belum dipetakan (kecuali ditandai "tidak ada di POS", migrasi 018);
- ProductID dipetakan ke lebih dari satu menu di outlet + tanggal itu;
- produk colorplate dipetakan ke menu closing (qty-nya akan terhitung dobel);
- produk non-colorplate belum punya master aktif dengan product_code;
- tanpa closing, tetapi produk colorplate terjual (`sold`-nya belum ada).

`compare_with_pos` tidak diubah: tampilan perbandingan `/closing` tetap
melihat data POS apa adanya.

Log dicatat `mengirim` sebelum request berangkat, supaya `message_id` sudah
tersimpan kalau proses mati di tengah jalan. `mengirim` yang dimulai lebih dari
BATAS_MACET lalu dianggap macet: kiriman baru menandainya gagal lalu
menggantikannya, dan kirim ulang diizinkan. Tidak ada baris yang dihapus.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.core.time import utcnow
from app.models.brand import Brand, OutletBrandMapping
from app.models.closing_report import STATUS_KIRIM_SAMPAI, ClosingExportLog
from app.models.product import Product
from app.models.sales import Sales
from app.models.sales_items import SalesItems
from app.services import closing_export_client, closing_report_service, colorplate_publish_service
from app.services.sales_service import SalesService, item_join

DEFAULT_LIMIT = 50
MAX_LIMIT = 200

# Jauh di atas kiriman terlama (3 percobaan × timeout 10 dtk + jeda ≈ 33 dtk).
BATAS_MACET = timedelta(minutes=5)
PESAN_MACET = "macet: tidak ada hasil dari API tujuan (proses terhenti)"


class BelumDikonfigurasi(Exception):
    """CLOSING_EXPORT_URL / CLOSING_EXPORT_TOKEN kosong."""


class TidakAdaClosing(Exception):
    pass


class TidakAdaPenjualan(Exception):
    """Brand boleh kirim tanpa closing, tetapi tidak ada data untuk dikirim di tanggal itu."""


class SedangDikirim(Exception):
    """Kiriman terakhir outlet + tanggal ini masih berstatus `mengirim`."""


class LogTidakDitemukan(Exception):
    pass


class TidakBisaDiulang(Exception):
    pass


@dataclass
class MenuBelumDipetakan:
    menu_id: object
    menu_code: str | None
    menu_name: str | None


@dataclass
class ProdukDobel:
    product_id: int
    product_name: str | None
    # Kode menu (atau nama, kalau kodenya kosong) yang memetakan produk ini.
    menus: list[str]


@dataclass
class ProdukPos:
    product_id: int
    product_name: str | None


@dataclass
class Blokir:
    menu_belum_dipetakan: list[MenuBelumDipetakan] = field(default_factory=list)
    produk_dobel: list[ProdukDobel] = field(default_factory=list)
    # Produk colorplate / berkonversi dipetakan ke menu: qty-nya sudah ada di `sold`.
    produk_colorplate_dipetakan: list[ProdukDobel] = field(default_factory=list)
    # Produk non-colorplate tanpa mapping aktif ke master `products` yang punya product_code.
    produk_belum_master: list[ProdukPos] = field(default_factory=list)
    # Kirim tanpa closing, tetapi produk colorplate terjual: `sold`-nya belum ada.
    colorplate_tanpa_closing: list[ProdukPos] = field(default_factory=list)

    def __bool__(self):
        return bool(
            self.menu_belum_dipetakan
            or self.produk_dobel
            or self.produk_colorplate_dipetakan
            or self.produk_belum_master
            or self.colorplate_tanpa_closing
        )


class Diblokir(Exception):
    def __init__(self, blokir: Blokir):
        super().__init__("rekap closing belum bisa dikirim")
        self.blokir = blokir


@dataclass
class StatusPasangan:
    outlet_code: str
    production_date: date
    # belum_dikirim / terkirim / perlu_kirim_ulang — dibanding kiriman terakhir yang sampai.
    status: str
    can_send: bool
    item_count: int
    total_sold: float
    # False = brand tanpa syarat closing, rekap hanya dari POS.
    has_closing: bool
    menu_belum_dipetakan: list[MenuBelumDipetakan]
    produk_dobel: list[ProdukDobel]
    produk_colorplate_dipetakan: list[ProdukDobel]
    produk_belum_master: list[ProdukPos]
    colorplate_tanpa_closing: list[ProdukPos]
    last_attempt: ClosingExportLog | None
    last_sent: ClosingExportLog | None


# ---------------------------------------------------------------------------
# Isi payload
# ---------------------------------------------------------------------------


def _angka(nilai):
    """None → 0; qty POS (Numeric) jadi int kalau bulat, selain itu float."""
    if nilai is None:
        return 0
    if isinstance(nilai, (float, Decimal)):
        return int(nilai) if nilai == int(nilai) else float(nilai)
    return nilai


def _item_menu(baris) -> dict:
    colorplate = _angka(baris.sold)
    pos = _angka(baris.pos_qty)
    return {
        "source": "closing",
        "menuId": str(baris.menu_id),
        "menuCode": baris.menu_code,
        "menuName": baris.menu_name,
        "productId": None,
        "productCode": None,
        "productName": None,
        "colorplateSold": colorplate,
        "posQty": pos,
        "totalSold": _angka(colorplate + pos),
        "waste": _angka(baris.waste),
        "adjustment": _angka(baris.adjustment),
        "compensation": _angka(baris.compensation),
    }


def _item_produk(produk: Product, qty) -> dict:
    pos = _angka(qty)
    return {
        "source": "pos_only",
        "menuId": None,
        "menuCode": None,
        "menuName": None,
        "productId": produk.code,
        "productCode": produk.product_code,
        "productName": produk.name,
        "colorplateSold": 0,
        "posQty": pos,
        "totalSold": pos,
        "waste": 0,
        "adjustment": 0,
        "compensation": 0,
    }


@dataclass
class RekapPasangan:
    outlet_code: str
    production_date: date
    # Baris menu closing dari `compare_with_pos`; kosong = tanpa closing.
    baris_menu: list = field(default_factory=list)
    # Item `pos_only` yang sudah disusun (per master produk).
    items_produk: list = field(default_factory=list)
    blokir: Blokir = field(default_factory=Blokir)


def susun_isi(rekap: RekapPasangan) -> dict:
    """Bagian payload yang di-hash — tanpa messageId / sentAt / sequence."""
    return {
        "outlet": {"code": rekap.outlet_code},
        "productionDate": rekap.production_date.isoformat(),
        "items": [_item_menu(b) for b in rekap.baris_menu] + rekap.items_produk,
    }


def hash_isi(isi: dict) -> str:
    teks = json.dumps(isi, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(teks.encode("utf-8")).hexdigest()


def periksa_blokir(baris) -> Blokir:
    blokir = Blokir()
    menu_per_produk: dict[int, list] = {}
    for b in baris:
        if b.menu_id is None:
            continue
        if not b.products and not b.not_in_pos:
            blokir.menu_belum_dipetakan.append(MenuBelumDipetakan(b.menu_id, b.menu_code, b.menu_name))
        for p in b.products:
            menu_per_produk.setdefault(p.product_id, []).append((p, b))

    for product_id, pasangan in sorted(menu_per_produk.items()):
        if len(pasangan) > 1:
            blokir.produk_dobel.append(
                ProdukDobel(
                    product_id=product_id,
                    product_name=pasangan[0][0].product_name,
                    menus=sorted(_label_menu(b) for _, b in pasangan),
                )
            )
    return blokir


def _penjualan_per_group(db, pasangan: set) -> list:
    """Qty POS per (outlet, tanggal, ProductID, group). Void tidak dihitung."""
    if not pasangan:
        return []
    tanggal = [d for _, d in pasangan]
    grup = SalesService._normalized_product_group()
    query = (
        db.query(
            Sales.outlet_code,
            Sales.sale_date,
            SalesItems.product_id,
            grup.label("grup"),
            func.sum(SalesItems.qty).label("qty"),
            func.max(func.trim(SalesItems.product_name)).label("nama"),
        )
        .join(Sales, item_join)
        .filter(
            Sales.outlet_code.in_(sorted({o for o, _ in pasangan})),
            Sales.sale_date >= min(tanggal),
            Sales.sale_date <= max(tanggal),
        )
    )
    query = SalesService._active_sales(query, include_deleted=False)
    rows = query.group_by(Sales.outlet_code, Sales.sale_date, SalesItems.product_id, grup).all()
    return [r for r in rows if (r.outlet_code, r.sale_date) in pasangan]


def _outlet_tanpa_syarat_closing(db, outlets=None) -> set:
    """Outlet yang brand-nya `requires_closing = FALSE`. Outlet tanpa brand tidak termasuk."""
    query = (
        db.query(OutletBrandMapping.outlet_code)
        .join(Brand, Brand.id == OutletBrandMapping.brand_id)
        .filter(Brand.requires_closing.is_(False))
    )
    if outlets is not None:
        query = query.filter(OutletBrandMapping.outlet_code.in_(sorted(set(outlets))))
    return {o for (o,) in query.all()}


def _pasangan_pos(db, outlets, start_date, end_date) -> set:
    """Outlet × tanggal yang punya penjualan, untuk brand tanpa syarat closing.

    Butuh rentang tanggal: tanpa itu tidak dicari, supaya status tanpa filter
    tidak memindai seluruh riwayat penjualan.
    """
    if not outlets or start_date is None or end_date is None:
        return set()
    query = (
        db.query(Sales.outlet_code, Sales.sale_date)
        .filter(Sales.outlet_code.in_(sorted(outlets)), Sales.sale_date >= start_date, Sales.sale_date <= end_date)
        .distinct()
    )
    return {(o, d) for o, d in SalesService._active_sales(query, include_deleted=False).all()}


def _label_menu(b) -> str:
    return b.menu_code or b.menu_name or str(b.menu_id)


def susun_rekap(db, outlet=None, start_date=None, end_date=None) -> list[RekapPasangan]:
    """Rekap per outlet × tanggal: menu closing + produk non-colorplate di master."""
    menu_per_pasangan: dict = {}
    for b in closing_report_service.compare_with_pos(
        db, outlet=outlet, start_date=start_date, end_date=end_date, include_deleted=False
    ):
        # Baris tanpa menu dari compare_with_pos disusun ulang di bawah dari data POS.
        if b.menu_id is not None:
            menu_per_pasangan.setdefault((b.outlet_code, b.production_date), []).append(b)

    bebas = _outlet_tanpa_syarat_closing(db, [outlet] if outlet else None)
    pasangan = set(menu_per_pasangan) | _pasangan_pos(db, bebas, start_date, end_date)
    if not pasangan:
        return []

    aturan = colorplate_publish_service.aturan_colorplate(db)
    # Sumber yang sama dengan tab Perbandingan.
    master = closing_report_service._master_per_pos(db, {o for o, _ in pasangan})
    rekap = {
        k: RekapPasangan(k[0], k[1], menu_per_pasangan.get(k, []), blokir=periksa_blokir(menu_per_pasangan.get(k, [])))
        for k in pasangan
    }

    # ProductID yang qty-nya sudah masuk posQty menu closing.
    tampil = {(k, p.product_id) for k, baris in menu_per_pasangan.items() for b in baris for p in b.products}
    colorplate: dict = {}
    produk: dict = {}
    belum_master: dict = {}
    for r in _penjualan_per_group(db, pasangan):
        qty = float(r.qty or 0)
        if not qty:
            continue
        k = (r.outlet_code, r.sale_date)
        if aturan.termasuk(r.product_id, r.grup):
            colorplate.setdefault(k, {})[r.product_id] = r.nama
            continue
        if (k, r.product_id) in tampil:
            continue
        master_produk = master.get((r.outlet_code, r.product_id))
        if master_produk is None or not master_produk.product_code:
            belum_master.setdefault(k, {})[r.product_id] = r.nama
            continue
        # Dua ProductID POS bisa menunjuk satu produk master: qty dijumlah.
        total = produk.setdefault(k, {}).setdefault(master_produk.id, [master_produk, 0.0])
        total[1] += qty

    for k, isi in rekap.items():
        isi.items_produk = sorted(
            (_item_produk(p, qty) for p, qty in produk.get(k, {}).values()),
            key=lambda i: (i["productName"] or "", i["productCode"] or ""),
        )
        isi.blokir.produk_belum_master = [ProdukPos(pid, n) for pid, n in sorted(belum_master.get(k, {}).items())]
        if isi.baris_menu:
            per_produk: dict = {}
            for b in isi.baris_menu:
                for p in b.products:
                    if p.product_id in colorplate.get(k, {}) or p.product_id in aturan.konversi:
                        per_produk.setdefault(p.product_id, (p.product_name, []))[1].append(_label_menu(b))
            isi.blokir.produk_colorplate_dipetakan = [
                ProdukDobel(pid, nama, sorted(menus)) for pid, (nama, menus) in sorted(per_produk.items())
            ]
        else:
            isi.blokir.colorplate_tanpa_closing = [
                ProdukPos(pid, n) for pid, n in sorted(colorplate.get(k, {}).items())
            ]

    # Tanpa closing dan tanpa apa pun untuk dikirim (mis. semua qty 0) tidak ditampilkan.
    hasil = [r for r in rekap.values() if r.baris_menu or r.items_produk or r.blokir]
    return sorted(hasil, key=lambda r: (r.production_date, r.outlet_code))


# ---------------------------------------------------------------------------
# Kirim
# ---------------------------------------------------------------------------


def _cek_konfigurasi():
    if not settings.closing_export_configured:
        raise BelumDikonfigurasi()


def _macet(log: ClosingExportLog) -> bool:
    return log.status == "mengirim" and log.started_at < utcnow() - BATAS_MACET


def _sedang_berjalan(log: ClosingExportLog | None) -> bool:
    return log is not None and log.status == "mengirim" and not _macet(log)


def _log_terakhir(db, outlet_code, production_date) -> ClosingExportLog | None:
    return (
        db.query(ClosingExportLog)
        .filter(ClosingExportLog.outlet_code == outlet_code, ClosingExportLog.production_date == production_date)
        .order_by(ClosingExportLog.sequence.desc())
        .first()
    )


def kirim(db, outlet_code: str, production_date: date, sent_by: str) -> ClosingExportLog:
    _cek_konfigurasi()

    daftar = susun_rekap(db, outlet=outlet_code, start_date=production_date, end_date=production_date)
    if not daftar:
        if _outlet_tanpa_syarat_closing(db, [outlet_code]):
            raise TidakAdaPenjualan()
        raise TidakAdaClosing()
    rekap = daftar[0]
    if rekap.blokir:
        raise Diblokir(rekap.blokir)

    terakhir = _log_terakhir(db, outlet_code, production_date)
    if _sedang_berjalan(terakhir):
        raise SedangDikirim()
    if terakhir is not None and _macet(terakhir):
        terakhir.status = "gagal"
        terakhir.error = PESAN_MACET
        terakhir.finished_at = utcnow()

    isi = susun_isi(rekap)
    message_id = uuid.uuid4()
    sequence = (terakhir.sequence if terakhir else 0) + 1
    payload = {
        "messageId": str(message_id),
        "sentAt": utcnow().isoformat(timespec="seconds") + "Z",
        "sequence": sequence,
        **isi,
    }
    log = ClosingExportLog(
        outlet_code=outlet_code,
        production_date=production_date,
        sequence=sequence,
        message_id=message_id,
        content_hash=hash_isi(isi),
        item_count=len(isi["items"]),
        payload=payload,
        status="mengirim",
        attempts=0,
        sent_by=sent_by,
    )
    db.add(log)
    try:
        db.commit()
    except IntegrityError:
        # Admin lain menekan kirim untuk outlet + tanggal yang sama bersamaan.
        db.rollback()
        raise SedangDikirim()

    return _jalankan(db, log.id, payload, str(message_id))


def kirim_ulang(db, log_id: int) -> ClosingExportLog:
    """Ulang kiriman yang gagal (atau macet di `mengirim`) dengan payload & messageId yang sama."""
    _cek_konfigurasi()

    log = db.get(ClosingExportLog, log_id)
    if log is None:
        raise LogTidakDitemukan()
    if log.status in STATUS_KIRIM_SAMPAI:
        raise TidakBisaDiulang("kiriman ini sudah sampai di API tujuan")
    if _sedang_berjalan(log):
        raise TidakBisaDiulang("kiriman ini masih sedang berjalan")
    if _log_terakhir(db, log.outlet_code, log.production_date).id != log.id:
        raise TidakBisaDiulang("sudah ada kiriman yang lebih baru untuk outlet dan tanggal ini")

    payload, message_id = log.payload, str(log.message_id)
    log.status = "mengirim"
    log.started_at = utcnow()
    log.finished_at = None
    db.commit()

    return _jalankan(db, log_id, payload, message_id)


def _jalankan(db, log_id: int, payload: dict, message_id: str) -> ClosingExportLog:
    # Tidak ada transaksi terbuka selama menunggu API tujuan.
    db.commit()
    hasil = closing_export_client.kirim(
        payload,
        message_id=message_id,
        url=settings.CLOSING_EXPORT_URL,
        token=settings.CLOSING_EXPORT_TOKEN,
        timeout=settings.CLOSING_EXPORT_TIMEOUT,
        max_retries=settings.CLOSING_EXPORT_MAX_RETRIES,
    )

    log = db.get(ClosingExportLog, log_id)
    log.status = hasil.status
    log.attempts = (log.attempts or 0) + hasil.attempts
    log.http_status = hasil.http_status
    log.response_body = hasil.response_body
    log.error = hasil.error[:255] if hasil.error else None
    log.finished_at = utcnow()
    db.commit()
    return log


# ---------------------------------------------------------------------------
# Status & riwayat
# ---------------------------------------------------------------------------


def status_pasangan(db, outlet=None, start_date=None, end_date=None) -> list[StatusPasangan]:
    """Status kirim setiap outlet × tanggal produksi yang punya closing, terbaru dulu.

    Outlet brand tanpa syarat closing juga muncul untuk tanggal yang punya
    penjualan, asalkan rentang tanggal diisi.
    """
    per_pasangan = {
        (r.outlet_code, r.production_date): r
        for r in susun_rekap(db, outlet=outlet, start_date=start_date, end_date=end_date)
    }
    if not per_pasangan:
        return []

    logs: dict[tuple, list[ClosingExportLog]] = {}
    for log in (
        db.query(ClosingExportLog)
        .filter(
            ClosingExportLog.outlet_code.in_({o for o, _ in per_pasangan}),
            ClosingExportLog.production_date.in_({d for _, d in per_pasangan}),
        )
        .order_by(ClosingExportLog.sequence)
    ):
        logs.setdefault((log.outlet_code, log.production_date), []).append(log)

    hasil = []
    for (outlet_code, production_date), rekap in per_pasangan.items():
        riwayat = logs.get((outlet_code, production_date), [])
        terakhir = riwayat[-1] if riwayat else None
        sampai = next((log for log in reversed(riwayat) if log.status in STATUS_KIRIM_SAMPAI), None)
        isi = susun_isi(rekap)
        blokir = rekap.blokir

        if sampai is None:
            status = "belum_dikirim"
        elif sampai.content_hash == hash_isi(isi):
            status = "terkirim"
        else:
            status = "perlu_kirim_ulang"

        hasil.append(
            StatusPasangan(
                outlet_code=outlet_code,
                production_date=production_date,
                status=status,
                can_send=not blokir and not _sedang_berjalan(terakhir),
                item_count=len(isi["items"]),
                total_sold=_angka(sum(i["totalSold"] for i in isi["items"])),
                has_closing=bool(rekap.baris_menu),
                menu_belum_dipetakan=blokir.menu_belum_dipetakan,
                produk_dobel=blokir.produk_dobel,
                produk_colorplate_dipetakan=blokir.produk_colorplate_dipetakan,
                produk_belum_master=blokir.produk_belum_master,
                colorplate_tanpa_closing=blokir.colorplate_tanpa_closing,
                last_attempt=terakhir,
                last_sent=sampai,
            )
        )

    hasil.sort(key=lambda s: s.outlet_code)
    hasil.sort(key=lambda s: s.production_date, reverse=True)
    return hasil


def list_logs(db, outlet=None, start_date=None, end_date=None, status=None, limit=DEFAULT_LIMIT, offset=0):
    """Kiriman terbaru dulu; filter tanggal = tanggal produksi. Mengembalikan (baris, total)."""
    query = db.query(ClosingExportLog)
    if outlet:
        query = query.filter(ClosingExportLog.outlet_code == outlet)
    if start_date:
        query = query.filter(ClosingExportLog.production_date >= start_date)
    if end_date:
        query = query.filter(ClosingExportLog.production_date <= end_date)
    if status:
        query = query.filter(ClosingExportLog.status == status)

    total = query.with_entities(func.count(ClosingExportLog.id)).scalar()
    rows = query.order_by(ClosingExportLog.id.desc()).limit(limit).offset(offset).all()
    return rows, total


def get_log(db, log_id: int) -> ClosingExportLog | None:
    return db.get(ClosingExportLog, log_id)
