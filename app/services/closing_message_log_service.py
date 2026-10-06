"""Log pesan closing report dari RabbitMQ (migrasi 013).

Ditulis consumer untuk setiap pesan yang di-ack atau dibuang ke DLQ; dibaca
admin dari dashboard. Tidak ada baris yang dihapus atau diubah.
"""

from datetime import date, datetime, time, timedelta

from sqlalchemy import func, or_

from app.models.closing_report import STATUS_LOG_PESAN, ClosingMessageLog

DEFAULT_LIMIT = 50
MAX_LIMIT = 200

# received_at disimpan dalam UTC; filter tanggal di dashboard mengikuti jam
# operasional outlet (WIB, tanpa daylight saving).
OFFSET_WIB = timedelta(hours=7)


def catat_pesan(db, **kolom) -> ClosingMessageLog:
    log = ClosingMessageLog(**kolom)
    db.add(log)
    db.commit()
    return log


def _rentang_utc(start_date: date | None, end_date: date | None):
    awal = datetime.combine(start_date, time.min) - OFFSET_WIB if start_date else None
    akhir = datetime.combine(end_date + timedelta(days=1), time.min) - OFFSET_WIB if end_date else None
    return awal, akhir


def _filter(query, q=None, start_date=None, end_date=None):
    if q:
        pola = f"%{q.strip().lower()}%"
        query = query.filter(
            or_(
                func.lower(ClosingMessageLog.message_id).like(pola),
                func.lower(ClosingMessageLog.outlet_code).like(pola),
            )
        )
    awal, akhir = _rentang_utc(start_date, end_date)
    if awal:
        query = query.filter(ClosingMessageLog.received_at >= awal)
    if akhir:
        query = query.filter(ClosingMessageLog.received_at < akhir)
    return query


def list_logs(db, status=None, q=None, start_date=None, end_date=None, limit=DEFAULT_LIMIT, offset=0):
    """Log terbaru dulu. Mengembalikan (baris, total, jumlah per status).

    Jumlah per status mengikuti filter pencarian dan tanggal, tapi tidak filter
    status — supaya admin tetap melihat berapa pesan yang ditolak saat sedang
    melihat pesan yang diterima.
    """
    dasar = _filter(db.query(ClosingMessageLog), q, start_date, end_date)

    jumlah = dict.fromkeys(STATUS_LOG_PESAN, 0)
    for nama, n in (
        _filter(db.query(ClosingMessageLog.status, func.count()), q, start_date, end_date)
        .group_by(ClosingMessageLog.status)
        .all()
    ):
        jumlah[nama] = n

    query = dasar.filter(ClosingMessageLog.status == status) if status else dasar
    total = query.count()
    rows = (
        query.order_by(ClosingMessageLog.received_at.desc(), ClosingMessageLog.id.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    return rows, total, jumlah


def get_log(db, log_id: int) -> ClosingMessageLog | None:
    return db.get(ClosingMessageLog, log_id)
