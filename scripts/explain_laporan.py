"""EXPLAIN (ANALYZE, BUFFERS) query laporan dashboard — READ-ONLY.

Menjalankan fungsi `SalesService` yang sebenarnya dipakai endpoint laporan,
menangkap SQL persis yang dikirim ke Postgres, lalu menjalankan
`EXPLAIN (ANALYZE, BUFFERS)` untuk tiap statement. Dengan begitu yang dianalisis
adalah query aplikasi apa adanya, bukan salinan tulisan tangan yang bisa
melenceng.

Jaminan read-only:
- seluruh pekerjaan di SATU transaksi yang dibuka dengan
  `SET TRANSACTION READ ONLY` — Postgres sendiri menolak INSERT/UPDATE/DDL;
- transaksi SELALU di-rollback di akhir, berhasil maupun gagal;
- tidak memakai `app.database.engine` (yang membaca `.env`): koneksi hanya
  dari env `DATABASE_URL` yang diset eksplisit.

Catatan: EXPLAIN ANALYZE benar-benar MENJALANKAN query SELECT-nya. Tidak
menulis apa pun, tapi tetap membebani server — jangan arahkan ke produksi.
Host selain localhost ditolak kecuali diberi `--bukan-produksi`.

Pemakaian:
    DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5433/maharasa_pos \\
        python scripts/explain_laporan.py [--hari 30] [--akhir 2026-11-18]
        [--outlet STTSM] [--group COLORPLATE] [--cek-saja]
"""

import argparse
import os
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

CEK_SQL = ROOT / "migrations" / "checks" / "saledate_konsisten.sql"
HOST_LOKAL = {"localhost", "127.0.0.1", "::1"}
TABEL = ("ordertransaction", "orderdetail", "orderpaydetail")


def judul(teks):
    print(f"\n{'=' * 78}\n{teks}\n{'=' * 78}")


def cetak_baris(result):
    kolom = list(result.keys())
    baris = result.fetchall()
    if not baris:
        print("(kosong)")
        return
    lebar = [max(len(str(k)), *(len(str(r[i])) for r in baris)) for i, k in enumerate(kolom)]
    print("  ".join(str(k).ljust(w) for k, w in zip(kolom, lebar)))
    for r in baris:
        print("  ".join(str(v).ljust(w) for v, w in zip(r, lebar)))


def statement_dari_file(path):
    """Pisahkan file .sql per `;` di akhir baris, buang komentar `--`."""
    isi = []
    for baris in path.read_text(encoding="utf-8").splitlines():
        tanpa_komentar = baris.split("--", 1)[0].rstrip()
        if tanpa_komentar:
            isi.append(tanpa_komentar)
    return [s.strip() for s in "\n".join(isi).split(";") if s.strip()]


def info_database(conn):
    judul("Target & statistik tabel")
    cetak_baris(conn.exec_driver_sql("SELECT current_database() AS db, version() AS versi"))
    print()
    cetak_baris(
        conn.exec_driver_sql(
            """
            SELECT c.relname AS tabel,
                   c.reltuples::bigint AS perkiraan_baris,
                   pg_size_pretty(pg_total_relation_size(c.oid)) AS ukuran,
                   s.last_analyze, s.last_autoanalyze
            FROM pg_class c
            LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
            WHERE c.relname = ANY(%(t)s) AND c.relkind = 'r'
            ORDER BY c.relname
            """,
            {"t": list(TABEL)},
        )
    )
    print()
    cetak_baris(
        conn.exec_driver_sql(
            """
            SELECT t.relname AS tabel, c.relname AS index, i.indisvalid AS valid,
                   pg_get_indexdef(i.indexrelid) AS definisi
            FROM pg_index i
            JOIN pg_class c ON c.oid = i.indexrelid
            JOIN pg_class t ON t.oid = i.indrelid
            WHERE t.relname = ANY(%(t)s)
            ORDER BY t.relname, c.relname
            """,
            {"t": list(TABEL)},
        )
    )


def aman(conn, nama, kerja):
    """Jalankan satu bagian di SAVEPOINT: kalau gagal (mis. tabel/kolom belum
    ada karena DB belum dimigrasi), bagian lain tetap jalan. SAVEPOINT diizinkan
    di transaksi read-only, dan RELEASE tidak mengakhiri transaksinya."""
    sp = conn.begin_nested()
    try:
        hasil = kerja()
        sp.commit()
        return hasil
    except Exception as e:
        sp.rollback()
        print(f"\n!! {nama} GAGAL: {type(e).__name__}: {str(e).splitlines()[0]}")
        return None


def cek_saledate(conn):
    judul(f"Konsistensi SaleDate ({CEK_SQL.relative_to(ROOT)})")
    for i, sql in enumerate(statement_dari_file(CEK_SQL), start=1):
        print(f"\n-- query {i}")
        aman(conn, f"query {i}", lambda sql=sql: cetak_baris(conn.exec_driver_sql(sql)))


def tangkap_sql(conn, fungsi):
    """Jalankan `fungsi(session)` dan kembalikan [(sql, params)] yang dikirim."""
    tertangkap = []

    def rekam(_conn, _cursor, statement, parameters, _context, _executemany):
        # Session juga mengirim SAVEPOINT/RELEASE — hanya query baca yang di-EXPLAIN.
        if statement.lstrip().upper().startswith(("SELECT", "WITH")):
            tertangkap.append((statement, parameters))

    event.listen(conn, "before_cursor_execute", rekam)
    try:
        with Session(bind=conn, autoflush=False) as session:
            hasil = fungsi(session)
    finally:
        event.remove(conn, "before_cursor_execute", rekam)
    return tertangkap, hasil


def explain(conn, nama, fungsi):
    tertangkap, hasil = tangkap_sql(conn, fungsi)
    for i, (sql, params) in enumerate(tertangkap, start=1):
        judul(f"{nama} — statement {i}/{len(tertangkap)}")
        print(sql.strip())
        print(f"\nparams: {params}\n")
        rencana = [r[0] for r in conn.exec_driver_sql("EXPLAIN (ANALYZE, BUFFERS) " + sql, params)]
        print("\n".join(rencana))

        sorot = [r.strip() for r in rencana if any(k in r for k in ("Scan on", "Scan using", "Join", "Execution Time"))]
        print("\n>> ringkas:")
        for r in sorot:
            print(f"   {r}")
    return hasil


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hari", type=int, default=30, help="panjang rentang (default 30)")
    ap.add_argument("--akhir", type=date.fromisoformat, help="tanggal akhir; default SaleDate terbaru")
    ap.add_argument("--outlet", help="scope satu outlet (seperti user role outlet)")
    ap.add_argument("--group", default="COLORPLATE", help="product group untuk by-group (default COLORPLATE)")
    ap.add_argument("--cek-saja", action="store_true", help="hanya jalankan cek konsistensi SaleDate")
    ap.add_argument("--bukan-produksi", action="store_true", help="izinkan host selain localhost (mis. salinan pg_dump)")
    args = ap.parse_args()

    raw = os.environ.get("DATABASE_URL")
    if not raw:
        sys.exit("DATABASE_URL belum diset. Script ini sengaja tidak membaca .env.")
    url = make_url(raw)
    print(f"Target: {url.render_as_string(hide_password=True)}")
    if url.host not in HOST_LOKAL and not args.bukan_produksi:
        sys.exit(f"Host {url.host!r} bukan localhost. Pastikan BUKAN produksi, lalu ulangi dengan --bukan-produksi.")

    # Diimpor setelah pengecekan di atas: app.config memvalidasi env saat import.
    from app.services.sales_service import SalesService

    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            trans = conn.begin()
            try:
                conn.exec_driver_sql("SET TRANSACTION READ ONLY")
                conn.exec_driver_sql("SET LOCAL statement_timeout = '300s'")
                hanya_baca = conn.exec_driver_sql("SHOW transaction_read_only").scalar()
                if hanya_baca != "on":
                    sys.exit("Transaksi tidak read-only — berhenti.")
                print(f"transaction_read_only = {hanya_baca}")

                info_database(conn)
                cek_saledate(conn)
                if args.cek_saja:
                    return

                akhir = args.akhir or conn.exec_driver_sql('SELECT max("SaleDate") FROM ordertransaction').scalar()
                if akhir is None:
                    sys.exit("ordertransaction kosong — tidak ada yang bisa di-EXPLAIN.")
                awal = akhir - timedelta(days=args.hari - 1)
                f = dict(outlet=args.outlet, start_date=awal, end_date=akhir)
                judul(f"Rentang {awal} s/d {akhir} ({args.hari} hari), outlet={args.outlet or 'semua'}")

                def jalankan(nama, fungsi):
                    return aman(conn, nama, lambda: explain(conn, nama, fungsi))

                top = jalankan("get_top_products", lambda s: SalesService.get_top_products(s, limit=10, **f)) or []
                jalankan(
                    "get_sales_by_product_groups",
                    lambda s: SalesService.get_sales_by_product_groups(s, [args.group], **f),
                )
                ids = [r.product_id for r in top]
                if ids:
                    jalankan(
                        f"get_sales_by_product_ids (ids dari top products: {ids})",
                        lambda s: SalesService.get_sales_by_product_ids(s, ids, exclude_groups=[args.group], **f),
                    )
                else:
                    print("\n!! get_sales_by_product_ids dilewati: top products kosong.")
                jalankan("get_payment_summary", lambda s: SalesService.get_payment_summary(s, **f))
            finally:
                trans.rollback()
                print("\nTransaksi di-rollback.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
