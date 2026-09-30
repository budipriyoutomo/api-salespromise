-- ============================================================
-- Migration 009: Brand dan mapping outlet → brand
-- ============================================================
--
-- Mengelompokkan outlet per brand supaya laporan dashboard bisa difilter
-- `?brand=KODE` (list sales, summary, daily, by-outlet, top-products, export).
--
-- Aturan:
--   - Satu outlet paling banyak satu brand: outlet_code UNIQUE di tabel
--     mapping. Satu brand boleh punya banyak outlet.
--   - brands.code disimpan dalam bentuk normal: TRIM + UPPER, sama seperti
--     product_group_mappings. Kode tidak bisa diubah lewat API.
--   - outlet_code mengikuti api_keys.outlet_code (sumber daftar outlet), tapi
--     sengaja TANPA foreign key — tabel api_keys tidak disentuh.
--   - Tidak ada penghapusan. Brand dimatikan lewat is_active = FALSE; outlet
--     dilepas dari brand dengan brand_id = NULL.
--
-- Hanya CREATE TABLE / INDEX, tanpa seed. Tabel ordertransaction, orderdetail,
-- dan api_keys tidak disentuh sama sekali.
--
-- Idempotent: aman dijalankan ulang.
-- ============================================================

CREATE TABLE IF NOT EXISTS brands (
    id              SERIAL          PRIMARY KEY,

    code            VARCHAR(20)     NOT NULL,
    name            VARCHAR(255)    NOT NULL,
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE,

    created_at      TIMESTAMP       NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP       DEFAULT NULL,

    CONSTRAINT uq_brands_code UNIQUE (code),
    CONSTRAINT ck_brands_code_normal CHECK (
        code <> '' AND code = UPPER(TRIM(code))
    ),
    CONSTRAINT ck_brands_name CHECK (TRIM(name) <> '')
);

CREATE TABLE IF NOT EXISTS outlet_brand_mappings (
    id              SERIAL          PRIMARY KEY,

    outlet_code     VARCHAR(20)     NOT NULL,
    brand_id        INTEGER         DEFAULT NULL REFERENCES brands (id),

    created_at      TIMESTAMP       NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP       DEFAULT NULL,

    CONSTRAINT uq_outlet_brand_mappings_outlet UNIQUE (outlet_code)
);

CREATE INDEX IF NOT EXISTS ix_outlet_brand_mappings_brand
    ON outlet_brand_mappings (brand_id);
