-- ============================================================
-- Migration 014: Master data product
-- ============================================================
--
-- Produk dikelola admin lewat /api/products. ProductID dari POS bisa berbeda
-- antar outlet, jadi tiap (outlet_code, ProductID) dipetakan ke satu produk
-- master lewat product_pos_mappings — dengan begitu produk yang sama di
-- beberapa outlet bisa dikenali sebagai satu produk.
--
-- Aturan:
--   - products.code disimpan dalam bentuk normal: TRIM + UPPER, sama seperti
--     brands.code. Kode tidak bisa diubah lewat API.
--   - Satu (outlet_code, pos_product_id) paling banyak satu baris mapping.
--     Pindah produk = UPDATE product_id, bukan baris baru.
--   - outlet_code tanpa foreign key, sama seperti outlet_brand_mappings.
--   - pos_product_name / pos_product_group hanya salinan untuk tampilan.
--   - Tidak ada penghapusan. Produk dan mapping dimatikan lewat
--     is_active = FALSE.
--
-- Hanya CREATE TABLE / INDEX, tanpa seed. Tabel ordertransaction, orderdetail,
-- dan brands tidak disentuh sama sekali.
--
-- Idempotent: aman dijalankan ulang.
-- ============================================================

CREATE TABLE IF NOT EXISTS products (
    id              SERIAL          PRIMARY KEY,

    code            VARCHAR(50)     NOT NULL,
    name            VARCHAR(255)    NOT NULL,
    category        VARCHAR(100)    DEFAULT NULL,
    unit            VARCHAR(20)     DEFAULT NULL,
    price           NUMERIC(18, 4)  NOT NULL DEFAULT 0,
    brand_id        INTEGER         DEFAULT NULL REFERENCES brands (id),
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE,

    created_at      TIMESTAMP       NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP       DEFAULT NULL,

    CONSTRAINT uq_products_code UNIQUE (code),
    CONSTRAINT ck_products_code_normal CHECK (
        code <> '' AND code = UPPER(TRIM(code))
    ),
    CONSTRAINT ck_products_name CHECK (TRIM(name) <> ''),
    CONSTRAINT ck_products_price CHECK (price >= 0)
);

CREATE INDEX IF NOT EXISTS ix_products_brand_id
    ON products (brand_id);

CREATE TABLE IF NOT EXISTS product_pos_mappings (
    id                  SERIAL          PRIMARY KEY,

    product_id          INTEGER         NOT NULL REFERENCES products (id),
    outlet_code         VARCHAR(20)     NOT NULL,
    pos_product_id      INTEGER         NOT NULL,
    pos_product_name    VARCHAR(255)    DEFAULT NULL,
    pos_product_group   VARCHAR(255)    DEFAULT NULL,
    is_active           BOOLEAN         NOT NULL DEFAULT TRUE,

    created_at          TIMESTAMP       NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMP       DEFAULT NULL,

    CONSTRAINT uq_product_pos_mappings_outlet_product UNIQUE (outlet_code, pos_product_id),
    CONSTRAINT ck_product_pos_mappings_pos_product_id CHECK (pos_product_id > 0)
);

CREATE INDEX IF NOT EXISTS ix_product_pos_mappings_product_id
    ON product_pos_mappings (product_id);
