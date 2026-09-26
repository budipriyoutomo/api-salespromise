-- ============================================================
-- Migration 007: Mapping per menu untuk publish RabbitMQ
-- ============================================================
--
-- Pelengkap migrasi 006. Mapping group mengirim SEMUA menu dalam satu group;
-- tabel ini memungkinkan admin memilih menu satu per satu (mis. hanya
-- "F birthday cake" dari group PROMO) tanpa mengaktifkan group-nya.
--
-- Aturan:
--   - Menu dikenali lewat product_id (kolom "ProductID" di orderdetail) —
--     tetap cocok walau nama menu diubah di POS.
--   - product_name / product_group hanya salinan untuk tampilan saat mapping
--     dibuat. Pencocokan publish TIDAK memakai kedua kolom itu.
--   - Publish mengirim GABUNGAN group aktif + menu aktif. Baris orderdetail
--     yang cocok keduanya tetap terhitung sekali.
--   - Tidak ada penghapusan. Menu dimatikan lewat is_active = FALSE.
--
-- Hanya CREATE TABLE. Tidak ada seed, jadi publish yang sudah berjalan tidak
-- berubah sampai admin menambahkan menu.
--
-- Idempotent: aman dijalankan ulang.
-- ============================================================

CREATE TABLE IF NOT EXISTS product_menu_mappings (
    id              SERIAL          PRIMARY KEY,

    product_id      INTEGER         NOT NULL,
    product_name    VARCHAR(255)    DEFAULT NULL,
    product_group   VARCHAR(255)    DEFAULT NULL,
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE,

    created_at      TIMESTAMP       NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP       DEFAULT NULL,

    CONSTRAINT uq_product_menu_mappings_product UNIQUE (product_id),
    CONSTRAINT ck_product_menu_mappings_product_id CHECK (product_id > 0)
);
