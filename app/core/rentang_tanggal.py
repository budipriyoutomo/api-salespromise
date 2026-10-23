"""Batas panjang rentang tanggal untuk endpoint laporan.

Laporan lintas bertahun-tahun memindai sebagian besar tabel penjualan dan
menahan satu koneksi database selama itu. Dibatasi hanya kalau KEDUA tanggal
dikirim: pemanggil lama tanpa rentang tidak diputus, dan `statement_timeout`
(app/database.py) tetap jadi pengaman terakhir.
"""

from datetime import date

from fastapi import HTTPException, status

from app.config import settings


def cek_rentang_tanggal(start_date: date | None, end_date: date | None, maks_hari: int | None = None) -> None:
    maks_hari = settings.REPORT_MAX_RANGE_DAYS if maks_hari is None else maks_hari
    if not start_date or not end_date or maks_hari <= 0:
        return

    # Rentang terbalik menghasilkan data kosong, bukan query berat.
    if (end_date - start_date).days > maks_hari:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Rentang tanggal paling panjang {maks_hari} hari. Persempit rentangnya.",
        )
