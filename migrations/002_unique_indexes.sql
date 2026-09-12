-- ============================================================
-- Migration 002: Unique index pendukung ON CONFLICT
-- ============================================================
--
-- Kode `sync_sales` memakai:
--
--   index_elements=["TransactionID", "outlet_code"]                    (ordertransaction)
--   index_elements=["OrderDetailID", "TransactionID", "ProductID"]     (orderdetail)
--
-- PostgreSQL menolak ON CONFLICT yang tidak punya unique index persis sama.
--
-- ------------------------------------------------------------
-- AMAN DIJALANKAN BERULANG, DAN AMAN DI PRODUKSI
-- ------------------------------------------------------------
-- Migrasi ini memeriksa KOLOM index yang ada, bukan namanya. Ini penting:
-- `CREATE INDEX IF NOT EXISTS` hanya membandingkan nama, sehingga index yang
-- sudah ada dengan nama berbeda tidak akan terdeteksi dan kamu berakhir dengan
-- dua index identik yang memperlambat setiap INSERT.
--
-- Contoh nyata: di satu database, index yang dibutuhkan sudah ada dengan nama
-- `idx_ordertransaction_trx_outlet`, bukan nama yang dipakai di bawah ini.
--
-- Untuk melihat kondisi sekarang:
--
--   SELECT indexname, indexdef FROM pg_indexes
--   WHERE tablename IN ('ordertransaction', 'orderdetail');
-- ============================================================


-- ------------------------------------------------------------
-- ordertransaction ("TransactionID", outlet_code)
-- ------------------------------------------------------------
-- Satu TransactionID boleh muncul di banyak outlet, tapi hanya sekali
-- per outlet.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_index i
        JOIN pg_class t ON t.oid = i.indrelid
        WHERE t.relname = 'ordertransaction'
          AND i.indisunique
          AND (
              SELECT array_agg(a.attname::text ORDER BY a.attname::text)
              FROM unnest(i.indkey) AS k(attnum)
              JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum
          ) = ARRAY['TransactionID', 'outlet_code']
    ) THEN
        CREATE UNIQUE INDEX uq_ordertransaction_txn_outlet
            ON ordertransaction ("TransactionID", outlet_code);
        RAISE NOTICE 'Index unik (TransactionID, outlet_code) dibuat.';
    ELSE
        RAISE NOTICE 'Index unik (TransactionID, outlet_code) sudah ada — dilewati.';
    END IF;
END $$;


-- ------------------------------------------------------------
-- orderdetail ("OrderDetailID", "TransactionID", "ProductID")
-- ------------------------------------------------------------
-- CATATAN (TODO 0.5): kunci ini belum memuat outlet_code. Kalau OrderDetailID
-- tidak dijamin unik lintas outlet, dua outlet bisa saling menimpa baris item.
-- Jalankan migrations/checks/orderdetail_outlet_collision.sql untuk memeriksa
-- apakah tabrakan itu benar-benar terjadi di data produksi.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_index i
        JOIN pg_class t ON t.oid = i.indrelid
        WHERE t.relname = 'orderdetail'
          AND i.indisunique
          AND (
              SELECT array_agg(a.attname::text ORDER BY a.attname::text)
              FROM unnest(i.indkey) AS k(attnum)
              JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum
          ) = ARRAY['OrderDetailID', 'ProductID', 'TransactionID']
    ) THEN
        CREATE UNIQUE INDEX uq_orderdetail_detail_txn_product
            ON orderdetail ("OrderDetailID", "TransactionID", "ProductID");
        RAISE NOTICE 'Index unik (OrderDetailID, TransactionID, ProductID) dibuat.';
    ELSE
        RAISE NOTICE 'Index unik (OrderDetailID, TransactionID, ProductID) sudah ada — dilewati.';
    END IF;
END $$;


-- ------------------------------------------------------------
-- Index pendukung query dashboard (filter outlet + rentang tanggal).
-- Bukan unique, jadi IF NOT EXISTS sudah memadai.
-- ------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_ordertransaction_outlet_saledate
    ON ordertransaction (outlet_code, "SaleDate");
