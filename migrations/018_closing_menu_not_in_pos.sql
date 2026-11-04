-- ============================================================
-- Migration 018: Tanda "tidak ada di POS" untuk menu closing
-- ============================================================
--
-- Sebagian menu colorplate memang tidak punya produk di POS, jadi tidak akan
-- pernah bisa dipetakan ke ProductID. Tanpa tanda ini, menu itu selamanya
-- "belum dipetakan" dan memblokir kirim rekap closing ke API eksternal
-- (Fase 8) untuk setiap outlet × tanggal yang memuatnya.
--
--   not_in_pos     TRUE = admin menyatakan menu ini tidak ada di POS. Tidak
--                  memblokir kiriman; terkirim dengan posQty 0.
--   not_in_pos_by  email admin yang menandai
--   not_in_pos_at  waktu ditandai (UTC tanpa timezone, seperti kolom lain)
--
-- Tanda dan mapping ProductID aktif tidak boleh ada bersamaan; aturan itu
-- dijaga aplikasi (closing_menu_service), admin memilih dari frontend.
--
-- HANYA ADD COLUMN di closing_menus. Default FALSE: semua menu yang sudah ada
-- tetap seperti sebelumnya (belum dipetakan tetap memblokir). Tidak ada baris
-- yang diubah atau dihapus, tabel lain tidak disentuh. ADD COLUMN dengan
-- default konstan tidak menulis ulang tabel (PostgreSQL 11+).
--
-- Idempotent: aman dijalankan ulang.
-- ============================================================

ALTER TABLE closing_menus ADD COLUMN IF NOT EXISTS not_in_pos BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE closing_menus ADD COLUMN IF NOT EXISTS not_in_pos_by VARCHAR(255) DEFAULT NULL;
ALTER TABLE closing_menus ADD COLUMN IF NOT EXISTS not_in_pos_at TIMESTAMP DEFAULT NULL;
