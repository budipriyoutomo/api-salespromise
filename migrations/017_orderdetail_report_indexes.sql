-- migrate:no-transaction
-- ============================================================
-- Migration 017: Index orderdetail untuk query dashboard (TODO 9.1)
-- ============================================================
--
-- HANYA menambah index. Tidak ada baris yang diubah atau dihapus, dan tidak
-- ada constraint / kolom yang disentuh.
--
-- CONCURRENTLY: tabel tetap bisa dibaca DAN ditulis selama index dibangun —
-- sync POS tidak berhenti. Konsekuensinya:
--   - tidak bisa di dalam transaksi, jadi file ini dijalankan migrate.py
--     statement per statement (penanda di baris pertama);
--   - lebih lambat dari CREATE INDEX biasa, dan menunggu transaksi yang
--     sedang berjalan selesai. Di tabel besar bisa beberapa menit per index;
--     container API baru start setelah migrasi selesai. Jalankan saat sepi,
--     atau lebih dulu lewat `python migrate.py` dari container sekali pakai.
--   - kalau gagal di tengah, index tertinggal berstatus INVALID. migrate.py
--     berhenti dan menyebut namanya, bukan melewatinya diam-diam.
--
-- Index lama `idx_orderdetail_transactionid` dan `idx_orderdetail_productid`
-- sengaja dibiarkan — tidak ada yang di-drop di migrasi ini.
--
-- Cek hasil:
--   SELECT c.relname, i.indisvalid
--   FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
--   WHERE i.indrelid = 'orderdetail'::regclass;

-- Join item → transaksi (`item_join`) di semua laporan: TransactionID +
-- outlet_code. PK orderdetail diawali OrderDetailID, jadi tidak bisa dipakai.
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_orderdetail_txn_outlet
    ON orderdetail ("TransactionID", outlet_code);

-- Filter rentang tanggal langsung di orderdetail (/api/sales/product-groups).
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_orderdetail_saledate_outlet
    ON orderdetail ("SaleDate", outlet_code);

-- Filter group yang dinormalisasi: SalesService._normalized_product_group()
-- menghasilkan upper(trim("Group")) — ekspresinya harus persis sama.
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_orderdetail_group_norm
    ON orderdetail ((upper(trim("Group"))));

-- Nama/group terbaru per ProductID (_info_terbaru, _info_terbaru_banyak).
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_orderdetail_product_terbaru
    ON orderdetail ("ProductID", "SaleDate" DESC, "TransactionID" DESC);
