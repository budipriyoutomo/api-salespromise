"""
Jalankan migrasi SQL di `migrations/` secara berurutan.

Usage:
    python migrate.py            # jalankan migrasi yang belum tercatat
    python migrate.py --status   # lihat mana yang sudah / belum jalan

Dipanggil otomatis oleh Dockerfile sebelum gunicorn start. Sengaja saat START
container, bukan saat BUILD: `docker build` tidak punya akses ke database —
tidak tersambung ke network postgres, dan `.env` tidak ikut masuk image.

Aturan:
- Hanya file berpola `NNN_nama.sql` yang dianggap migrasi. `orderdetail.sql`
  dan `ordertransaction.sql` adalah dump MySQL lama berisi DROP TABLE, dan
  `checks/` berisi query diagnosis — keduanya TIDAK boleh ikut jalan.
- File yang sudah jalan dicatat di tabel `schema_migrations` dan dilewati pada
  start berikutnya.
- Database yang migrasinya dulu dijalankan manual lewat psql belum punya
  catatan itu, jadi 001-005 akan dijalankan ulang sekali. Aman karena semuanya
  idempoten. Migrasi baru WAJIB tetap idempoten.
- Setiap file jalan dalam transaksinya sendiri. Gagal di tengah = file itu
  di-rollback utuh, tidak dicatat, dan proses keluar dengan kode 1 sehingga
  gunicorn tidak ikut start di atas skema setengah jadi.
- Advisory lock mencegah dua container menjalankan migrasi bersamaan.
"""

import argparse
import re
import sys
import time
from pathlib import Path

import psycopg2
from sqlalchemy.exc import DBAPIError

from app.database import engine

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
POLA_FILE = re.compile(r"^\d{3}_[A-Za-z0-9_]+\.sql$")

# Angka bebas, asal konsisten — hanya kunci untuk pg_advisory_lock.
ADVISORY_LOCK_ID = 7_210_001

DDL_TABEL_CATATAN = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename    VARCHAR(255)    PRIMARY KEY,
    applied_at  TIMESTAMP       NOT NULL DEFAULT NOW()
)
"""


def daftar_migrasi(folder: Path = MIGRATIONS_DIR) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.is_file() and POLA_FILE.match(p.name))


def sambung(percobaan: int = 10, jeda: float = 3.0):
    """Database di network eksternal bisa belum siap saat container start."""
    for ke in range(1, percobaan + 1):
        try:
            return engine.raw_connection()
        except (DBAPIError, psycopg2.OperationalError) as e:
            if ke == percobaan:
                raise
            print(f"[migrate] Database belum siap ({ke}/{percobaan}): {str(e).strip()}")
            time.sleep(jeda)


def _sudah_jalan(cur) -> set[str]:
    cur.execute("SELECT filename FROM schema_migrations")
    return {row[0] for row in cur.fetchall()}


def _cetak_notice(conn):
    # RAISE NOTICE dari migrasi (mis. 002) supaya kelihatan di `docker logs`.
    notices = getattr(conn, "notices", None)
    if notices:
        for n in notices:
            print(f"[migrate]   {n.strip()}")
        del notices[:]


def jalankan(conn, files: list[Path]) -> list[str]:
    """Jalankan file yang belum tercatat. Mengembalikan nama file yang dijalankan."""
    cur = conn.cursor()
    try:
        # Lock level session: tetap dipegang melewati commit per file, dan
        # lepas sendiri saat koneksi ditutup.
        cur.execute("SELECT pg_advisory_lock(%s)", (ADVISORY_LOCK_ID,))
        cur.execute(DDL_TABEL_CATATAN)
        conn.commit()

        tercatat = _sudah_jalan(cur)
        dijalankan = []

        for f in files:
            if f.name in tercatat:
                continue

            print(f"[migrate] Menjalankan {f.name} ...")
            try:
                # Tanpa parameter, psycopg2 mengirim SQL apa adanya — banyak
                # statement dan blok DO $$ dalam satu file tetap jalan.
                cur.execute(f.read_text(encoding="utf-8-sig"))
                cur.execute("INSERT INTO schema_migrations (filename) VALUES (%s)", (f.name,))
                conn.commit()
            except Exception:
                conn.rollback()
                print(f"[migrate] GAGAL di {f.name} — di-rollback, migrasi setelahnya tidak dijalankan.")
                raise
            finally:
                _cetak_notice(conn)

            dijalankan.append(f.name)

        return dijalankan
    finally:
        cur.close()


def tampilkan_status(conn, files: list[Path]):
    cur = conn.cursor()
    try:
        cur.execute("SELECT to_regclass('schema_migrations')")
        tercatat = _sudah_jalan(cur) if cur.fetchone()[0] else set()
    finally:
        cur.close()

    for f in files:
        tanda = "x" if f.name in tercatat else " "
        print(f"  [{tanda}] {f.name}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Jalankan migrasi database")
    parser.add_argument("--status", action="store_true", help="tampilkan status tanpa menjalankan apa pun")
    args = parser.parse_args(argv)

    files = daftar_migrasi()

    try:
        conn = sambung()
    except Exception as e:
        print(f"[migrate] Tidak bisa terhubung ke database: {e}")
        return 1

    try:
        if args.status:
            tampilkan_status(conn, files)
            return 0

        dijalankan = jalankan(conn, files)
    except Exception as e:
        print(f"[migrate] Error: {e}")
        return 1
    finally:
        conn.close()
        engine.dispose()

    if dijalankan:
        print(f"[migrate] Selesai: {len(dijalankan)} migrasi dijalankan.")
    else:
        print("[migrate] Skema sudah terbaru, tidak ada migrasi baru.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
