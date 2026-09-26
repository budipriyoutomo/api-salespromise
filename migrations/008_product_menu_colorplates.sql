-- ============================================================
-- Migration 008: Konversi menu ke warna colorplate
-- ============================================================
--
-- Sejak migrasi ini publish RabbitMQ hanya mengirim format colorplate
-- ({platecolor, outlet, date, sold}). Menu dari group lain (mis. PROMO
-- "Buy 1 Get 2 RED") ikut terhitung lewat tabel ini:
--
--   sold(warna) = qty COLORPLATE warna itu
--               + Σ qty menu × multiplier   (menu aktif, baris aktif)
--
-- Aturan:
--   - Satu menu boleh dipetakan ke beberapa warna (Buy 1 RED Get 1 BLUE).
--   - platecolor disimpan seperti nama menu COLORPLATE di data penjualan;
--     pencocokan tidak peka huruf besar/kecil & spasi di tepi.
--   - Menu aktif tanpa baris aktif di sini TIDAK dipublish.
--   - Tidak ada penghapusan. Baris dimatikan lewat is_active = FALSE.
--
-- Hanya CREATE TABLE, tanpa seed.
--
-- Idempotent: aman dijalankan ulang.
-- ============================================================

CREATE TABLE IF NOT EXISTS product_menu_colorplates (
    id                  SERIAL          PRIMARY KEY,

    menu_mapping_id     INTEGER         NOT NULL REFERENCES product_menu_mappings (id),
    platecolor          VARCHAR(255)    NOT NULL,
    multiplier          INTEGER         NOT NULL DEFAULT 1,
    is_active           BOOLEAN         NOT NULL DEFAULT TRUE,

    created_at          TIMESTAMP       NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMP       DEFAULT NULL,

    CONSTRAINT uq_product_menu_colorplates_menu_color UNIQUE (menu_mapping_id, platecolor),
    CONSTRAINT ck_product_menu_colorplates_multiplier CHECK (multiplier > 0)
);

CREATE INDEX IF NOT EXISTS ix_product_menu_colorplates_menu
    ON product_menu_colorplates (menu_mapping_id);
