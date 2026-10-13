"""Kirim rekap closing ke API eksternal (TODO Fase 8).

Kontrak: docs/usulan-kontrak-kirim-closing.md. Keputusan: TODO.md Fase 8.0.

Satu kiriman = satu outlet × satu tanggal produksi, disusun dari
`compare_with_pos` (void tidak pernah dihitung):

    closing   colorplateSold = sold, posQty = qty POS mentah (tanpa pengali)
    pos_only  produk POS yang terjual tanpa menu colorplate; colorplateSold = 0
    totalSold = colorplateSold + posQty; waste / adjustment / compensation
                dari colorplate saja. Angka kosong = 0.

Diblokir kalau ada menu colorplate yang belum dipetakan, atau ProductID yang
dipetakan ke lebih dari satu menu di outlet + tanggal itu (qty POS-nya akan
terhitung dobel).

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
from app.models.closing_report import STATUS_KIRIM_SAMPAI, ClosingExportLog
from app.services import closing_export_client, closing_report_service

DEFAULT_LIMIT = 50
MAX_LIMIT = 200

# Jauh di atas kiriman terlama (3 percobaan × timeout 10 dtk + jeda ≈ 33 dtk).
BATAS_MACET = timedelta(minutes=5)
PESAN_MACET = "macet: tidak ada hasil dari API tujuan (proses terhenti)"


class BelumDikonfigurasi(Exception):
    """CLOSING_EXPORT_URL / CLOSING_EXPORT_TOKEN kosong."""


class TidakAdaClosing(Exception):
    pass


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
class Blokir:
    menu_belum_dipetakan: list[MenuBelumDipetakan] = field(default_factory=list)
    produk_dobel: list[ProdukDobel] = field(default_factory=list)

    def __bool__(self):
        return bool(self.menu_belum_dipetakan or self.produk_dobel)


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
    menu_belum_dipetakan: list[MenuBelumDipetakan]
    produk_dobel: list[ProdukDobel]
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


def _item(baris) -> dict:
    colorplate = _angka(baris.sold)
    pos = _angka(baris.pos_qty)
    produk = baris.products[0] if baris.menu_id is None else None
    return {
        "source": "closing" if baris.menu_id is not None else "pos_only",
        "menuId": str(baris.menu_id) if baris.menu_id is not None else None,
        "menuCode": baris.menu_code,
        "menuName": baris.menu_name,
        "productId": produk.product_id if produk else None,
        "productName": produk.product_name if produk else None,
        "colorplateSold": colorplate,
        "posQty": pos,
        "totalSold": _angka(colorplate + pos),
        "waste": _angka(baris.waste),
        "adjustment": _angka(baris.adjustment),
        "compensation": _angka(baris.compensation),
    }


def susun_isi(outlet_code: str, production_date: date, baris) -> dict:
    """Bagian payload yang di-hash — tanpa messageId / sentAt / sequence."""
    return {
        "outlet": {"code": outlet_code},
        "productionDate": production_date.isoformat(),
        "items": [_item(b) for b in baris],
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
        if not b.products:
            blokir.menu_belum_dipetakan.append(MenuBelumDipetakan(b.menu_id, b.menu_code, b.menu_name))
        for p in b.products:
            menu_per_produk.setdefault(p.product_id, []).append((p, b))

    for product_id, pasangan in sorted(menu_per_produk.items()):
        if len(pasangan) > 1:
            blokir.produk_dobel.append(
                ProdukDobel(
                    product_id=product_id,
                    product_name=pasangan[0][0].product_name,
                    menus=sorted(b.menu_code or b.menu_name or str(b.menu_id) for _, b in pasangan),
                )
            )
    return blokir


def _baris_pasangan(db, outlet_code, production_date):
    return closing_report_service.compare_with_pos(
        db, outlet=outlet_code, start_date=production_date, end_date=production_date, include_deleted=False
    )


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

    baris = _baris_pasangan(db, outlet_code, production_date)
    if not any(b.menu_id is not None for b in baris):
        raise TidakAdaClosing()
    blokir = periksa_blokir(baris)
    if blokir:
        raise Diblokir(blokir)

    terakhir = _log_terakhir(db, outlet_code, production_date)
    if _sedang_berjalan(terakhir):
        raise SedangDikirim()
    if terakhir is not None and _macet(terakhir):
        terakhir.status = "gagal"
        terakhir.error = PESAN_MACET
        terakhir.finished_at = utcnow()

    isi = susun_isi(outlet_code, production_date, baris)
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
    """Status kirim setiap outlet × tanggal produksi yang punya closing, terbaru dulu."""
    per_pasangan: dict[tuple, list] = {}
    for b in closing_report_service.compare_with_pos(
        db, outlet=outlet, start_date=start_date, end_date=end_date, include_deleted=False
    ):
        per_pasangan.setdefault((b.outlet_code, b.production_date), []).append(b)
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
    for (outlet_code, production_date), baris in per_pasangan.items():
        riwayat = logs.get((outlet_code, production_date), [])
        terakhir = riwayat[-1] if riwayat else None
        sampai = next((log for log in reversed(riwayat) if log.status in STATUS_KIRIM_SAMPAI), None)
        isi = susun_isi(outlet_code, production_date, baris)
        blokir = periksa_blokir(baris)

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
                menu_belum_dipetakan=blokir.menu_belum_dipetakan,
                produk_dobel=blokir.produk_dobel,
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
