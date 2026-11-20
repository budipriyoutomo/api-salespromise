"""Helper waktu.

`datetime.utcnow()` deprecated sejak Python 3.12, tapi penggantinya yang
disarankan (`datetime.now(timezone.utc)`) menghasilkan objek ber-timezone.

Kolom `created_at` / `updated_at` di database bertipe `TIMESTAMP` tanpa
timezone. Kalau diisi datetime ber-timezone, PostgreSQL menafsirkan angkanya
apa adanya dan nilai tersimpan bisa bergeser beberapa jam dari data lama.

Karena itu helper ini mengembalikan datetime **naive dalam UTC** — persis
seperti perilaku `datetime.utcnow()` yang digantikan, tanpa peringatan
deprecation.
"""

from datetime import date, datetime, timedelta, timezone

# WIB = UTC+7 tetap (Indonesia tidak memakai DST). Offset tetap, bukan
# ZoneInfo("Asia/Jakarta"): image slim belum tentu membawa data tzdata.
WIB = timezone(timedelta(hours=7))


def _sekarang_utc() -> datetime:
    # Dipisah supaya test bisa menetapkan "sekarang".
    return datetime.now(timezone.utc)


def utcnow() -> datetime:
    """Waktu UTC sekarang, tanpa tzinfo."""
    return _sekarang_utc().replace(tzinfo=None)


def hari_ini_wib() -> date:
    """Tanggal hari ini di WIB — tanggal bisnis yang dipakai `SaleDate` POS.

    Server/container berjalan di UTC; tanpa ini, pukul 00:00–07:00 WIB masih
    terhitung tanggal kemarin.
    """
    return _sekarang_utc().astimezone(WIB).date()
