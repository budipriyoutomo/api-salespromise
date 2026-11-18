-- ============================================================
-- Migration 021: Baris pembayaran per transaksi (orderpaydetail)
-- ============================================================
--
-- Agen POS mengirim key `payments` di setiap elemen `sales`
-- (docs/handoff-sync-api-payments.md). Dibutuhkan rekap closing ke ERP
-- (kontrak revisi 3): `payments` per tujuan kunjungan.
--
-- 1. Tabel baru `orderpaydetail`.
--    Kunci (outlet_code, TransactionID, ComputerID, PayDetailID) mengikuti PK
--    tabel pembayaran POS. Jenis bayar dikunci per outlet (PayTypeID); jenis
--    sistem POS tidak disimpan. FK ke ordertransaction sama seperti orderdetail.
--
-- 2. Kolom baru `ordertransaction.payments_received_at` (nullable, tanpa
--    default). NULL = pembayaran transaksi belum diketahui (agen lama atau view
--    belum dipasang). Diisi setiap kali POS mengirim key `payments`, termasuk
--    `payments: []`. Baris lama tetap NULL.
--
-- HANYA CREATE TABLE dan ADD COLUMN nullable. Tidak ada baris yang diubah
-- atau dihapus. ADD COLUMN nullable tanpa default tidak menulis ulang tabel,
-- tetapi memegang lock singkat ACCESS EXCLUSIVE di ordertransaction.
--
-- Idempotent: aman dijalankan ulang.
-- ============================================================

CREATE TABLE IF NOT EXISTS orderpaydetail (
    outlet_code             VARCHAR(20)     NOT NULL,
    "TransactionID"         INTEGER         NOT NULL,
    "ComputerID"            INTEGER         NOT NULL,
    "PayDetailID"           INTEGER         NOT NULL,
    "SaleDate"              DATE            DEFAULT NULL,
    "PayTypeID"             INTEGER         NOT NULL,
    "PayTypeCode"           VARCHAR(50)     DEFAULT NULL,
    "PayTypeName"           VARCHAR(255)    DEFAULT NULL,
    "PayTypeDisplayName"    VARCHAR(255)    DEFAULT NULL,
    "Amount"                NUMERIC(18,4)   NOT NULL DEFAULT 0,
    "CashChange"            NUMERIC(18,4)   NOT NULL DEFAULT 0,
    "IsFromEDC"             SMALLINT        NOT NULL DEFAULT 0,
    "IsSale"                SMALLINT        NOT NULL DEFAULT 0,
    "IsOtherReceipt"        SMALLINT        NOT NULL DEFAULT 0,
    received_at             TIMESTAMP       NOT NULL,
    CONSTRAINT orderpaydetail_pkey
        PRIMARY KEY (outlet_code, "TransactionID", "ComputerID", "PayDetailID"),
    CONSTRAINT orderpaydetail_transaction_fkey
        FOREIGN KEY ("TransactionID", outlet_code)
        REFERENCES ordertransaction ("TransactionID", outlet_code)
);

-- Rekap closing: penjumlahan per outlet + tanggal.
CREATE INDEX IF NOT EXISTS ix_orderpaydetail_outlet_saledate
    ON orderpaydetail (outlet_code, "SaleDate");

ALTER TABLE ordertransaction ADD COLUMN IF NOT EXISTS payments_received_at TIMESTAMP DEFAULT NULL;
