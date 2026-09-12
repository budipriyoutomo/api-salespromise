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

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Waktu UTC sekarang, tanpa tzinfo."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
