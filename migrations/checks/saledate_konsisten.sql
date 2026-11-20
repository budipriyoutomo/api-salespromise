-- ============================================================
-- Pemeriksaan: apakah "SaleDate" item/pembayaran selalu sama dengan
-- "SaleDate" transaksinya?
-- ============================================================
--
-- SEMUA QUERY DI FILE INI READ-ONLY. Jalankan di dalam transaksi read-only
-- supaya PostgreSQL sendiri menolak penulisan:
--
--   BEGIN TRANSACTION READ ONLY;
--   \i migrations/checks/saledate_konsisten.sql
--   ROLLBACK;
--
-- atau lewat `python scripts/explain_laporan.py --cek-saja`.
-- File ini TIDAK dijalankan migrate.py (hanya pola NNN_nama.sql).
--
-- Kenapa penting: rencana menambah filter tanggal redundan di
-- orderdetail."SaleDate" (supaya index ix_orderdetail_saledate_outlet bisa
-- dipakai) HANYA aman kalau tanggal item = tanggal transaksinya. Item yang
-- tanggalnya beda akan ikut / tidak ikut terhitung secara berbeda → angka
-- laporan berubah.
--
-- Catatan dari kode (sales_service.sync_sales):
--   - orderdetail."SaleDate"   diisi dari payload ITEM (item.sale_date) —
--     dikirim POS terpisah, TIDAK disalin dari transaksi. Bisa berbeda.
--   - orderpaydetail."SaleDate" disalin dari transaksi saat insert. Bisa
--     berbeda hanya kalau transaksi kemudian di-upsert dengan tanggal lain.
--   - ordertransaction."SaleDate" nullable; orderdetail."SaleDate" NOT NULL.
--
-- Separator antar-query: titik koma di akhir baris (dipakai script).

-- 1. orderdetail vs ordertransaction — ringkasan.
--    saledate_beda > 0 berarti filter redundan TIDAK aman tanpa penanganan.
SELECT
    'orderdetail' AS tabel,
    count(*) AS total_baris,
    count(*) FILTER (WHERE t."TransactionID" IS NULL) AS tanpa_transaksi,
    count(*) FILTER (WHERE t."TransactionID" IS NOT NULL AND t."SaleDate" IS NULL) AS transaksi_saledate_null,
    count(*) FILTER (
        WHERE t."TransactionID" IS NOT NULL AND d."SaleDate" IS DISTINCT FROM t."SaleDate"
    ) AS saledate_beda,
    count(DISTINCT (d.outlet_code, d."TransactionID")) FILTER (
        WHERE t."TransactionID" IS NOT NULL AND d."SaleDate" IS DISTINCT FROM t."SaleDate"
    ) AS transaksi_terdampak
FROM orderdetail d
LEFT JOIN ordertransaction t
    ON t."TransactionID" = d."TransactionID" AND t.outlet_code = d.outlet_code;

-- 2. orderpaydetail vs ordertransaction — ringkasan.
SELECT
    'orderpaydetail' AS tabel,
    count(*) AS total_baris,
    count(*) FILTER (WHERE t."TransactionID" IS NULL) AS tanpa_transaksi,
    count(*) FILTER (WHERE t."TransactionID" IS NOT NULL AND t."SaleDate" IS NULL) AS transaksi_saledate_null,
    count(*) FILTER (
        WHERE t."TransactionID" IS NOT NULL AND p."SaleDate" IS DISTINCT FROM t."SaleDate"
    ) AS saledate_beda,
    count(DISTINCT (p.outlet_code, p."TransactionID")) FILTER (
        WHERE t."TransactionID" IS NOT NULL AND p."SaleDate" IS DISTINCT FROM t."SaleDate"
    ) AS transaksi_terdampak
FROM orderpaydetail p
LEFT JOIN ordertransaction t
    ON t."TransactionID" = p."TransactionID" AND t.outlet_code = p.outlet_code;

-- 3. Rincian selisih orderdetail per outlet & selisih hari (kalau ada).
SELECT
    d.outlet_code,
    d."SaleDate" - t."SaleDate" AS selisih_hari,
    count(*) AS baris,
    count(DISTINCT d."TransactionID") AS transaksi,
    min(t."SaleDate") AS tanggal_transaksi_awal,
    max(t."SaleDate") AS tanggal_transaksi_akhir
FROM orderdetail d
JOIN ordertransaction t
    ON t."TransactionID" = d."TransactionID" AND t.outlet_code = d.outlet_code
WHERE d."SaleDate" IS DISTINCT FROM t."SaleDate"
GROUP BY d.outlet_code, d."SaleDate" - t."SaleDate"
ORDER BY baris DESC
LIMIT 50;
