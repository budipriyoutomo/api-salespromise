-- ============================================================
-- Migration 023: Harga satuan & nilai rupiah per item closing report (v3)
-- ============================================================
--
-- Pesan `closingreport.submitted` version 3 membawa harga per item
-- (docs/bi-closing-report-v3-harga.md). Sampai sekarang harga itu hanya ada
-- di closing_report_revisions.raw_payload. Kolom ini membuatnya bisa dibaca
-- API / dashboard tanpa membongkar JSONB (TODO 7.10).
--
--   unit_price           harga satu piring (harga warna piring, bukan menu)
--   sold_amount          sold × unit_price, 2 desimal
--   waste_amount         waste × unit_price
--   adjustment_amount    adjustment × unit_price, boleh negatif
--   compensation_amount  compensation × unit_price, boleh negatif
--
-- NUMERIC(14,2): sampai 999.999.999.999,99 — sama dengan batas skema pesan.
-- NULL = item dari pesan v1 / v2 (tanpa harga). Tidak ada backfill: laporan
-- lama mendapat harga lewat kiriman ulang v3 sebagai revisi baru.
--
-- HANYA ADD COLUMN di closing_report_items, semuanya nullable tanpa default.
-- Tidak ada baris yang diubah atau dihapus, tabel lain tidak disentuh. ADD
-- COLUMN nullable tidak menulis ulang tabel, tetapi tetap memegang lock
-- singkat ACCESS EXCLUSIVE di closing_report_items.
--
-- Idempotent: aman dijalankan ulang.
-- ============================================================

ALTER TABLE closing_report_items ADD COLUMN IF NOT EXISTS unit_price NUMERIC(14,2) DEFAULT NULL;
ALTER TABLE closing_report_items ADD COLUMN IF NOT EXISTS sold_amount NUMERIC(14,2) DEFAULT NULL;
ALTER TABLE closing_report_items ADD COLUMN IF NOT EXISTS waste_amount NUMERIC(14,2) DEFAULT NULL;
ALTER TABLE closing_report_items ADD COLUMN IF NOT EXISTS adjustment_amount NUMERIC(14,2) DEFAULT NULL;
ALTER TABLE closing_report_items ADD COLUMN IF NOT EXISTS compensation_amount NUMERIC(14,2) DEFAULT NULL;
