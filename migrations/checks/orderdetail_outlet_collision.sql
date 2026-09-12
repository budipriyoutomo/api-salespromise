-- ============================================================
-- Pemeriksaan TODO 0.5 — apakah OrderDetailID bertabrakan antar outlet?
-- ============================================================
--
-- Tabel `orderdetail` tidak punya kolom `outlet_code`. Kunci konflik upsert-nya
-- adalah ("OrderDetailID", "TransactionID", "ProductID") saja.
--
-- Kalau nomor OrderDetailID digenerate per outlet (bukan global), dua outlet
-- bisa mengirim kombinasi yang sama, dan yang datang belakangan MENIMPA baris
-- outlet lain tanpa error apa pun — kerusakan diam.
--
-- Jalankan ketiga query ini di PRODUKSI sebelum memutuskan apakah perlu
-- menambah `outlet_code` ke `orderdetail`. Semuanya read-only.
-- ============================================================


-- 1. Apakah ada TransactionID yang dipakai lebih dari satu outlet?
--    Kalau hasilnya kosong, item tidak mungkin bertabrakan dan TODO 0.5
--    bisa ditutup tanpa perubahan apa pun.
SELECT
    "TransactionID",
    COUNT(DISTINCT outlet_code) AS jumlah_outlet,
    STRING_AGG(DISTINCT outlet_code, ', ') AS outlet
FROM ordertransaction
GROUP BY "TransactionID"
HAVING COUNT(DISTINCT outlet_code) > 1
ORDER BY jumlah_outlet DESC
LIMIT 50;


-- 2. Berapa banyak baris orderdetail yang terhubung ke TransactionID
--    milik lebih dari satu outlet? Ini perkiraan luas dampaknya.
SELECT COUNT(*) AS baris_item_berisiko
FROM orderdetail d
WHERE d."TransactionID" IN (
    SELECT "TransactionID"
    FROM ordertransaction
    GROUP BY "TransactionID"
    HAVING COUNT(DISTINCT outlet_code) > 1
);


-- 3. Rentang OrderDetailID per outlet.
--    Rentang yang tumpang tindih = penomoran per outlet (berisiko).
--    Rentang yang terpisah rapi = penomoran global (aman).
SELECT
    t.outlet_code,
    MIN(d."OrderDetailID") AS id_terkecil,
    MAX(d."OrderDetailID") AS id_terbesar,
    COUNT(*)               AS jumlah_baris
FROM orderdetail d
JOIN ordertransaction t
  ON t."TransactionID" = d."TransactionID"
GROUP BY t.outlet_code
ORDER BY t.outlet_code;


-- ------------------------------------------------------------
-- KALAU TERBUKTI BERTABRAKAN, langkah perbaikannya:
--
--   ALTER TABLE orderdetail ADD COLUMN outlet_code VARCHAR(20);
--
--   UPDATE orderdetail d
--   SET outlet_code = t.outlet_code
--   FROM ordertransaction t
--   WHERE t."TransactionID" = d."TransactionID";
--
--   DROP INDEX IF EXISTS uq_orderdetail_detail_txn_product;
--   CREATE UNIQUE INDEX uq_orderdetail_detail_txn_product_outlet
--       ON orderdetail ("OrderDetailID", "TransactionID", "ProductID", outlet_code);
--
-- Lalu di app/services/sales_service.py tambahkan "outlet_code" ke
-- index_elements milik insert(SalesItems) dan kirim outlet_code di values().
--
-- PERHATIAN: baris yang sudah saling menimpa TIDAK bisa dipulihkan dari sini —
-- datanya sudah hilang. Perlu sync ulang dari POS untuk rentang tanggal terdampak.
-- ------------------------------------------------------------
