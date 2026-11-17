-- ============================================================
-- Migration 020: Warna piring untuk menu closing
-- ============================================================
--
-- Kirim rekap closing ke ERP (kontrak revisi 3): produk COLORPLATE POS tidak
-- lagi dikirim sebagai item tersendiri. Pendapatan piring masuk ke `prices`
-- menu closing: colorplateSold × harga piring warna menu itu. Laporan closing
-- tidak membawa warna, jadi admin mengisinya per menu.
--
--   platecolor     nama warna seperti di data COLORPLATE POS (mis. "RED").
--                  NULL = belum diisi. Menu dengan sold > 0 tanpa warna
--                  memblokir kirim rekap.
--   platecolor_by  email admin yang terakhir mengisi / mengubah
--   platecolor_at  waktu diisi (UTC tanpa timezone, seperti kolom lain)
--
-- HANYA ADD COLUMN di closing_menus, semuanya nullable tanpa default. Tidak
-- ada baris yang diubah atau dihapus, tabel lain tidak disentuh. ADD COLUMN
-- nullable tidak menulis ulang tabel, tetapi tetap memegang lock singkat
-- ACCESS EXCLUSIVE di closing_menus.
--
-- Idempotent: aman dijalankan ulang.
-- ============================================================

ALTER TABLE closing_menus ADD COLUMN IF NOT EXISTS platecolor VARCHAR(255) DEFAULT NULL;
ALTER TABLE closing_menus ADD COLUMN IF NOT EXISTS platecolor_by VARCHAR(255) DEFAULT NULL;
ALTER TABLE closing_menus ADD COLUMN IF NOT EXISTS platecolor_at TIMESTAMP DEFAULT NULL;
