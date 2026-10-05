-- ============================================================
-- Migration 012: Penyesuaian tabel closing report setelah jawaban pengirim
-- ============================================================
--
-- Jawaban tim pengirim `closingreport.submitted` (2026-10-05,
-- docs/jawaban-pengirim-closing.md):
--
--   - menuCode bisa berubah, unik hanya per brand, dan bisa NULL. Kunci menu
--     yang stabil adalah menuId (UUID).
--   - productionDate bisa NULL (menu tanpa baris produksi hari itu).
--   - Retry membawa sentAt baru dengan isi identik — duplikat ditentukan oleh
--     messageId saja, bukan messageId + sentAt.
--   - compensation belum divalidasi >= 0 per menu di sisi pengirim. Diputuskan
--     diterima (consumer mencatat warning), jadi CHECK tidak lagi mencakupnya.
--
-- PERUBAHAN (hanya tabel closing_*, yang dibuat 011)
-- ---------------------------------------------------
--   closing_report_revisions  UNIQUE (report_id, message_id, sent_at)
--                             -> UNIQUE (report_id, message_id)
--   closing_report_items      menu_code, production_date boleh NULL
--                             CHECK qty tanpa compensation
--                             index (menu_code, production_date) -> (menu_id, production_date)
--   closing_menus             kunci menu_code -> menu_id, menu_code boleh NULL,
--                             + brand_code (menuCode unik per brand)
--
-- TIDAK ADA baris yang dihapus atau diubah. Kalau data yang ada melanggar
-- constraint baru (duplikat), migrasi BERHENTI (RAISE EXCEPTION) — keputusan
-- manual, bukan efek samping deploy. Tabel lama (api_keys, ordertransaction,
-- orderdetail, ...) tidak disentuh.
--
-- Idempoten: setiap langkah memeriksa kondisi sekarang, aman dijalankan ulang.
-- ============================================================

DO $$
DECLARE
    v_jumlah BIGINT;
BEGIN
    -- --------------------------------------------------------
    -- 0. Prasyarat: tidak ada duplikat yang menghalangi constraint baru
    -- --------------------------------------------------------
    SELECT COUNT(*) INTO v_jumlah FROM (
        SELECT 1 FROM closing_report_revisions
        GROUP BY report_id, message_id HAVING COUNT(*) > 1
    ) d;
    IF v_jumlah > 0 THEN
        RAISE EXCEPTION 'Migrasi 012 dibatalkan: % pasangan (report_id, message_id) punya lebih '
            'dari satu revisi. Tentukan revisi mana yang dipakai (keputusan manual), lalu jalankan ulang.',
            v_jumlah;
    END IF;

    SELECT COUNT(*) INTO v_jumlah FROM (
        SELECT 1 FROM closing_menus GROUP BY menu_id HAVING COUNT(*) > 1
    ) d;
    IF v_jumlah > 0 THEN
        RAISE EXCEPTION 'Migrasi 012 dibatalkan: % menu_id tercatat lebih dari sekali di closing_menus. '
            'Gabungkan dulu (keputusan manual), lalu jalankan ulang.', v_jumlah;
    END IF;

    -- --------------------------------------------------------
    -- 1. Revisi: dedup per message_id
    -- --------------------------------------------------------
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_closing_report_revisions_message_id') THEN
        ALTER TABLE closing_report_revisions
            ADD CONSTRAINT uq_closing_report_revisions_message_id UNIQUE (report_id, message_id);
    END IF;
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_closing_report_revisions_message') THEN
        ALTER TABLE closing_report_revisions DROP CONSTRAINT uq_closing_report_revisions_message;
    END IF;

    -- --------------------------------------------------------
    -- 2. Menu: kunci menu_id
    -- --------------------------------------------------------
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_closing_menus_menu_id') THEN
        ALTER TABLE closing_menus ADD CONSTRAINT uq_closing_menus_menu_id UNIQUE (menu_id);
    END IF;
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_closing_menus_menu_code') THEN
        ALTER TABLE closing_menus DROP CONSTRAINT uq_closing_menus_menu_code;
    END IF;
END $$;

ALTER TABLE closing_menus ALTER COLUMN menu_code DROP NOT NULL;
ALTER TABLE closing_menus ADD COLUMN IF NOT EXISTS brand_code VARCHAR(20) DEFAULT NULL;

-- --------------------------------------------------------
-- 3. Item: kode & tanggal produksi boleh NULL, compensation tanpa batas bawah
-- --------------------------------------------------------
ALTER TABLE closing_report_items ALTER COLUMN menu_code DROP NOT NULL;
ALTER TABLE closing_report_items ALTER COLUMN production_date DROP NOT NULL;

ALTER TABLE closing_report_items DROP CONSTRAINT IF EXISTS ck_closing_report_items_qty;
ALTER TABLE closing_report_items
    ADD CONSTRAINT ck_closing_report_items_qty CHECK (sold >= 0 AND waste >= 0);

DROP INDEX IF EXISTS ix_closing_report_items_menu_date;
CREATE INDEX IF NOT EXISTS ix_closing_report_items_menu_id_date
    ON closing_report_items (menu_id, production_date);
