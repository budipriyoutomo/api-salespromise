-- ============================================================
-- Migration 006: Mapping product group untuk publish RabbitMQ (TODO Fase 6)
-- ============================================================
--
-- Sebelumnya group yang dipublish di-hardcode `COLORPLATE` di
-- SalesService.get_sales_colorplate. Tabel ini membuat daftar group bisa
-- ditambah / dinonaktifkan admin lewat /api/product-groups tanpa deploy.
--
-- Aturan:
--   - product_group disimpan dalam bentuk normal: TRIM + UPPER. POS bisa
--     mengirim `Colorplate ` atau ` PROMO BANDUNG`; pencocokan ke orderdetail
--     memakai UPPER(TRIM("Group")). CHECK di bawah menjaga supaya jalur lain
--     (mis. psql manual) tidak menyimpan bentuk yang tidak akan pernah cocok.
--   - Tidak ada penghapusan. Group dimatikan lewat is_active = FALSE.
--
-- Seed COLORPLATE WAJIB: tanpa itu publish di produksi berhenti mengirim
-- event colorplate begitu versi ini dideploy.
--
-- Hanya CREATE TABLE + INSERT. Tabel ordertransaction / orderdetail tidak
-- disentuh sama sekali.
--
-- Idempotent: aman dijalankan ulang. Seed memakai ON CONFLICT DO NOTHING,
-- jadi status is_active yang sudah diubah admin tidak ditimpa.
-- ============================================================

CREATE TABLE IF NOT EXISTS product_group_mappings (
    id              SERIAL          PRIMARY KEY,

    product_group   VARCHAR(255)    NOT NULL,
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE,

    created_at      TIMESTAMP       NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP       DEFAULT NULL,

    CONSTRAINT uq_product_group_mappings_group UNIQUE (product_group),
    CONSTRAINT ck_product_group_mappings_normal CHECK (
        product_group <> '' AND product_group = UPPER(TRIM(product_group))
    )
);

INSERT INTO product_group_mappings (product_group, is_active)
VALUES ('COLORPLATE', TRUE)
ON CONFLICT (product_group) DO NOTHING;
