-- ============================================================
-- Migration 015: Product Code & subkategori produk
-- ============================================================
--
-- Halaman produk kini memakai:
--   - products.code         → tampil sebagai "ProductID" (tidak berubah)
--   - products.product_code → "Product Code", wajib & unik lewat API
--   - products.subcategory  → opsional
--
-- product_code boleh NULL di database: produk yang dibuat sebelum migrasi ini
-- belum punya Product Code dan baru diisi admin saat produknya diubah. API
-- yang mewajibkannya. Index unik Postgres tidak menganggap NULL bentrok.
--
-- Kolom unit & price tidak dipakai lagi oleh API, tetapi SENGAJA tidak
-- dihapus — datanya tetap utuh.
--
-- Hanya ADD COLUMN / ADD CONSTRAINT / CREATE INDEX. Tidak ada baris yang
-- diubah atau dihapus. Idempotent: aman dijalankan ulang.
-- ============================================================

ALTER TABLE products ADD COLUMN IF NOT EXISTS product_code VARCHAR(50) DEFAULT NULL;
ALTER TABLE products ADD COLUMN IF NOT EXISTS subcategory  VARCHAR(100) DEFAULT NULL;

-- Bentuk normal sama dengan products.code: TRIM + UPPER.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_products_product_code_normal'
    ) THEN
        ALTER TABLE products ADD CONSTRAINT ck_products_product_code_normal CHECK (
            product_code IS NULL OR (product_code <> '' AND product_code = UPPER(TRIM(product_code)))
        );
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_products_product_code
    ON products (product_code);
