"""Update products.product_code dari export POS (ProductData.csv).

Kunci: kolom CSV `ProductID` == products.code (tampil "ProductID" di /produk).
Nilai: kolom CSV `ProductCode` → products.product_code (dinormalisasi trim + huruf besar).

Bawaan DRY-RUN: hanya membaca DB (transaksi READ ONLY) dan menampilkan rencana.

    python update_product_code_csv.py ProductData.csv                     # dry-run
    python update_product_code_csv.py ProductData.csv --report hasil.csv  # dry-run + daftar lengkap
    python update_product_code_csv.py ProductData.csv --sql update.sql    # tulis SQL, tidak dijalankan
    python update_product_code_csv.py ProductData.csv --apply             # jalankan UPDATE

--apply berjalan dalam satu transaksi. Tiap UPDATE mensyaratkan product_code
masih sama dengan nilai saat rencana dibuat; kalau jumlah baris yang berubah
tidak sama dengan rencana, semuanya di-rollback. Produk yang tidak ada di CSV
dan ProductID CSV yang tidak ada di DB tidak disentuh.
"""

import argparse
import csv
import sys
from collections import Counter, defaultdict

from sqlalchemy import text

from app.database import engine

MAX_LEN = 50


def norm(value) -> str:
    # Sama dengan product_service.normalize_product_code.
    return (value or "").strip(" ").upper()


def read_csv(path: str, encoding: str) -> dict[str, set[str]]:
    with open(path, encoding=encoding, newline="") as f:
        reader = csv.DictReader(f)
        missing = {"ProductID", "ProductCode"} - set(reader.fieldnames or [])
        if missing:
            sys.exit(f"Kolom CSV tidak ada: {', '.join(sorted(missing))}")
        per_pid: dict[str, set[str]] = defaultdict(set)
        for row in reader:
            pid = norm(row["ProductID"])
            if pid:
                per_pid[pid].add(norm(row["ProductCode"]))
    return per_pid


def load_products(conn):
    return conn.execute(
        text(
            "SELECT p.id, p.code, p.product_code, p.name, b.code AS brand "
            "FROM products p LEFT JOIN brands b ON b.id = p.brand_id ORDER BY p.code"
        )
    ).mappings().all()


def build_plan(products, per_pid):
    plan = []  # dict: status, row, new, note
    for p in products:
        codes = per_pid.get(p["code"])
        if codes is None:
            plan.append({"status": "TIDAK_ADA_DI_CSV", "row": p, "new": None, "note": ""})
            continue
        if len(codes) > 1:
            plan.append({"status": "AMBIGU", "row": p, "new": None, "note": "CSV: " + ", ".join(sorted(codes))})
            continue
        new = next(iter(codes))
        if not new:
            status = "CSV_KOSONG"
        elif len(new) > MAX_LEN:
            status = "TERLALU_PANJANG"
        elif new == p["product_code"]:
            status = "SAMA"
        else:
            status = "UBAH"
        plan.append({"status": status, "row": p, "new": new, "note": ""})

    # product_code unik: cek hasil akhir setelah semua UBAH diterapkan.
    final = {item["row"]["code"]: item["row"]["product_code"] for item in plan}
    for item in plan:
        if item["status"] == "UBAH":
            final[item["row"]["code"]] = item["new"]
    count = Counter(v for v in final.values() if v)
    for item in plan:
        if item["status"] == "UBAH" and count[item["new"]] > 1:
            others = [k for k, v in final.items() if v == item["new"] and k != item["row"]["code"]]
            item["status"] = "BENTROK"
            item["note"] = "dipakai juga oleh ProductID " + ", ".join(others)
    return plan


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def write_sql(path: str, changes) -> None:
    values = ",\n".join(
        f"    ({sql_literal(i['row']['code'])}, {sql_literal(i['row']['product_code'] or '')}, {sql_literal(i['new'])})"
        for i in changes
    )
    sql = f"""-- Update products.product_code dari ProductData.csv ({len(changes)} baris).
-- Hanya mengubah baris yang product_code-nya masih sama dengan saat rencana dibuat.
-- Jalankan dengan psql; kalau jumlah baris tidak {len(changes)}, transaksi dibatalkan.
BEGIN;

CREATE TEMP TABLE _pc_update (code VARCHAR(50), old_pc VARCHAR(50), new_pc VARCHAR(50)) ON COMMIT DROP;
INSERT INTO _pc_update (code, old_pc, new_pc) VALUES
{values};

DO $$
DECLARE n integer;
BEGIN
    UPDATE products p
       SET product_code = u.new_pc, updated_at = (now() AT TIME ZONE 'utc')
      FROM _pc_update u
     WHERE p.code = u.code
       AND COALESCE(p.product_code, '') = u.old_pc;
    GET DIAGNOSTICS n = ROW_COUNT;
    IF n <> {len(changes)} THEN
        RAISE EXCEPTION 'Diharapkan {len(changes)} baris, yang berubah %%. Dibatalkan.', n;
    END IF;
    RAISE NOTICE '% baris product_code diperbarui', n;
END $$;

COMMIT;
"""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(sql.replace("%%", "%"))


def write_report(path: str, plan) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["status", "products.id", "ProductID", "brand", "nama", "product_code_lama", "product_code_baru", "note"])
        for i in sorted(plan, key=lambda x: (x["status"], x["row"]["code"])):
            r = i["row"]
            w.writerow([i["status"], r["id"], r["code"], r["brand"], r["name"], r["product_code"], i["new"], i["note"]])


def apply(changes) -> int:
    with engine.begin() as conn:
        total = 0
        for i in changes:
            res = conn.execute(
                text(
                    "UPDATE products SET product_code = :new, updated_at = (now() AT TIME ZONE 'utc') "
                    "WHERE id = :id AND product_code IS NOT DISTINCT FROM :old"
                ),
                {"new": i["new"], "id": i["row"]["id"], "old": i["row"]["product_code"]},
            )
            total += res.rowcount
        if total != len(changes):
            raise RuntimeError(f"Diharapkan {len(changes)} baris, yang berubah {total}. Di-rollback.")
    return total


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv_path")
    ap.add_argument("--encoding", default="cp1252", help="encoding CSV (export POS: cp1252)")
    ap.add_argument("--report", help="tulis daftar lengkap rencana ke CSV ini")
    ap.add_argument("--sql", help="tulis SQL UPDATE ke file ini (tidak dijalankan)")
    ap.add_argument("--apply", action="store_true", help="jalankan UPDATE ke DB")
    ap.add_argument("--limit", type=int, default=10, help="jumlah contoh per status yang ditampilkan")
    args = ap.parse_args()

    per_pid = read_csv(args.csv_path, args.encoding)
    with engine.connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        products = load_products(conn)
        conn.rollback()

    plan = build_plan(products, per_pid)
    stat = Counter(i["status"] for i in plan)
    db_codes = {p["code"] for p in products}

    print(f"DB      : {engine.url.render_as_string(hide_password=True)}")
    print(f"CSV     : {len(per_pid)} ProductID unik, {sum(1 for k in per_pid if k not in db_codes)} tidak ada di DB (diabaikan)")
    print(f"Produk  : {len(products)}")
    for status, n in stat.most_common():
        print(f"  {status:17} {n}")

    for status in ("UBAH", "BENTROK", "AMBIGU", "CSV_KOSONG", "TERLALU_PANJANG", "TIDAK_ADA_DI_CSV"):
        items = [i for i in plan if i["status"] == status][: args.limit]
        if items:
            print(f"\nContoh {status}:")
            for i in items:
                r = i["row"]
                print(f"  {r['code']:>10}  {r['name'][:32]:32}  {r['product_code']!s:>10} -> {i['new']!s:<10} {i['note']}")

    if args.report:
        write_report(args.report, plan)
        print(f"\nLaporan: {args.report}")

    changes = [i for i in plan if i["status"] == "UBAH"]
    blocking = stat["BENTROK"] + stat["AMBIGU"]
    if args.sql:
        write_sql(args.sql, changes)
        print(f"SQL ({len(changes)} baris): {args.sql}")

    if not args.apply:
        print("\nDRY-RUN: tidak ada yang diubah. Tambah --apply untuk menjalankan.")
        return
    if blocking:
        sys.exit(f"\nDibatalkan: ada {blocking} baris BENTROK/AMBIGU. Bereskan dulu datanya.")
    if not changes:
        print("\nTidak ada yang perlu diubah.")
        return
    n = apply(changes)
    print(f"\nSELESAI: {n} product_code diperbarui.")


if __name__ == "__main__":
    main()
