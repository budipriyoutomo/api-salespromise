-- ============================================================
-- Pemeriksaan TODO 0.5 — apakah data item/transaksi bertabrakan antar outlet?
-- ============================================================
--
-- SEMUA QUERY DI FILE INI READ-ONLY. Untuk jaminan tambahan, jalankan di
-- dalam transaksi read-only supaya PostgreSQL sendiri menolak penulisan:
--
--   BEGIN TRANSACTION READ ONLY;
--   \i migrations/checks/orderdetail_outlet_collision.sql
--   ROLLBACK;
--
-- File ini TIDAK dijalankan migrate.py (hanya pola NNN_nama.sql yang dianggap migrasi).
--
-- ------------------------------------------------------------
-- TEMUAN 2026-09-15 (database lokal maharasa_pos, 1 outlet, 14 transaksi)
-- ------------------------------------------------------------
-- 1. `ordertransaction` punya PRIMARY KEY ("TransactionID") — TANPA outlet.
--    Index unik ("TransactionID", outlet_code) memang ada, tapi PK yang lebih
--    sempit tetap berlaku. Akibatnya outlet kedua yang mengirim TransactionID
--    yang sudah dipakai outlet lain TIDAK menimpa diam-diam, melainkan GAGAL
--    (UniqueViolation pada ordertransaction_pkey) dan seluruh batch sync-nya
--    di-rollback. Outlet itu tidak akan pernah bisa sync.
--
--    Karena PK itu, query 1 di bawah SELALU kosong — hasil kosong BUKAN bukti
--    aman. Jalankan query 0 dulu untuk melihat constraint yang berlaku.
--
--    TERVERIFIKASI pada salinan `maharasa_pos_uji`: sync OUTLET_UJI dengan
--    TransactionID 6057 (milik STTSM) -> UniqueViolation ordertransaction_pkey.
--
-- 2. `OrderDetailID` adalah nomor baris PER TRANSAKSI (selalu mulai dari 1),
--    bukan nomor global. Begitu dua outlet berbagi TransactionID, kunci item
--    (OrderDetailID, TransactionID, ProductID) hampir pasti ikut bertabrakan.
--
-- 3. FK orderdetail("TransactionID") -> ordertransaction("TransactionID")
--    bergantung pada PK sempit itu, jadi PK tidak bisa diubah tanpa FK ikut diubah.
-- ============================================================


-- 0. Constraint & index yang benar-benar berlaku.
--    Kalau ordertransaction_pkey = PRIMARY KEY ("TransactionID"), temuan 1 berlaku.
SELECT conrelid::regclass AS tabel, conname, pg_get_constraintdef(oid) AS definisi
FROM pg_constraint
WHERE conrelid IN ('ordertransaction'::regclass, 'orderdetail'::regclass)
ORDER BY 1, 2;

SELECT tablename, indexname, indexdef
FROM pg_indexes
WHERE tablename IN ('ordertransaction', 'orderdetail')
ORDER BY 1, 2;


-- 1. Apakah ada TransactionID yang dipakai lebih dari satu outlet?
--    Hanya bermakna kalau PK ordertransaction SUDAH memuat outlet_code (lihat 0).
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


-- 3. Rentang OrderDetailID & TransactionID per outlet.
--    Rentang TransactionID yang tumpang tindih antar outlet = penomoran per POS
--    (berisiko). OrderDetailID yang mulai dari 1 = nomor baris per transaksi.
SELECT
    t.outlet_code,
    MIN(d."OrderDetailID") AS detail_min,
    MAX(d."OrderDetailID") AS detail_max,
    MIN(t."TransactionID") AS txn_min,
    MAX(t."TransactionID") AS txn_max,
    COUNT(*)               AS baris_item
FROM orderdetail d
JOIN ordertransaction t
  ON t."TransactionID" = d."TransactionID"
GROUP BY t.outlet_code
ORDER BY t.outlet_code;


-- 4. Prasyarat migrasi perbaikan. SEMUA harus 0 sebelum migrasi boleh jalan.
SELECT
    (SELECT COUNT(*) FROM ordertransaction WHERE outlet_code IS NULL) AS transaksi_tanpa_outlet,
    (SELECT COUNT(*) FROM orderdetail d
      WHERE NOT EXISTS (SELECT 1 FROM ordertransaction t
                        WHERE t."TransactionID" = d."TransactionID")) AS item_yatim;


-- 5. Log sync yang gagal karena PK (cari di logs/api.log server):
--      grep 'ordertransaction_pkey' logs/api.log
--    Kalau ada, outlet yang bersangkutan sudah pernah ditolak.


-- ------------------------------------------------------------
-- Rencana perbaikan (BELUM dibuat, menunggu persetujuan) — lihat TODO 0.5.
-- Rencana lama di file ini (hanya menambah index unik) TIDAK cukup: PK sempit
-- dan FK di atas tetap akan menolak outlet kedua.
-- ------------------------------------------------------------
