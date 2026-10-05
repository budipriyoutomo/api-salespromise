-- ============================================================
-- Migration 011: Closing report dari RabbitMQ (TODO Fase 7)
-- ============================================================
--
-- Sistem lain mengirim event `closingreport.submitted`: closing harian per
-- outlet berisi sold / waste / adjustment / compensation per menu. Data ini
-- dibandingkan dengan penjualan POS (orderdetail) per tanggal produksi.
--
-- Tabel:
--   closing_reports           satu baris per closingReportId (header terbaru)
--   closing_report_revisions  satu baris per kiriman, payload mentah untuk audit
--   closing_report_items      item milik satu revisi
--   closing_menus             menuCode yang pernah muncul di pesan
--   closing_menu_products     menuCode -> ProductID POS x pengali
--
-- Aturan:
--   - closingReportId yang dikirim ulang = REVISI. Tidak ada baris yang
--     dihapus: kiriman baru mendapat revisi + item sendiri, revisi lama
--     dimatikan lewat is_current = FALSE. Paling banyak satu revisi aktif per
--     laporan (index uq_closing_report_revisions_current).
--   - Redelivery pesan yang sama (message_id + sent_at sama) ditolak unique,
--     jadi tidak menambah revisi.
--   - outlet_code disimpan apa adanya walau belum ada di api_keys — tanpa
--     foreign key, sama seperti outlet_brand_mappings.
--   - Satu menu boleh dipetakan ke beberapa ProductID (mis. paket isi 2 ->
--     pengali 2); satu ProductID boleh dipakai beberapa menu (mis. combo).
--   - Mapping dimatikan lewat is_active = FALSE, tidak dihapus.
--   - sent_at / received_at dalam UTC tanpa timezone, seperti kolom lain.
--
-- Hanya CREATE TABLE / CREATE INDEX. Tidak ada seed, tidak ada ALTER, dan
-- tabel yang sudah ada tidak disentuh.
--
-- Idempotent: aman dijalankan ulang.
-- ============================================================

CREATE TABLE IF NOT EXISTS closing_reports (
    id                  SERIAL          PRIMARY KEY,

    closing_report_id   UUID            NOT NULL,
    report_date         DATE            NOT NULL,
    outlet_code         VARCHAR(20)     NOT NULL,
    outlet_name         VARCHAR(255)    NOT NULL,
    brand_code          VARCHAR(20)     NOT NULL,
    brand_name          VARCHAR(255)    NOT NULL,

    created_at          TIMESTAMP       NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMP       DEFAULT NULL,

    CONSTRAINT uq_closing_reports_closing_report_id UNIQUE (closing_report_id)
);

CREATE INDEX IF NOT EXISTS ix_closing_reports_outlet_date
    ON closing_reports (outlet_code, report_date);


CREATE TABLE IF NOT EXISTS closing_report_revisions (
    id                  SERIAL          PRIMARY KEY,

    report_id           INTEGER         NOT NULL REFERENCES closing_reports (id),
    message_id          VARCHAR(255)    NOT NULL,
    version             SMALLINT        NOT NULL,
    sent_at             TIMESTAMP       NOT NULL,
    received_at         TIMESTAMP       NOT NULL DEFAULT NOW(),
    is_current          BOOLEAN         NOT NULL DEFAULT FALSE,
    raw_payload         JSONB           NOT NULL,

    CONSTRAINT uq_closing_report_revisions_message UNIQUE (report_id, message_id, sent_at)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_closing_report_revisions_current
    ON closing_report_revisions (report_id)
    WHERE is_current;


CREATE TABLE IF NOT EXISTS closing_report_items (
    id                  SERIAL          PRIMARY KEY,

    revision_id         INTEGER         NOT NULL REFERENCES closing_report_revisions (id),
    menu_id             UUID            NOT NULL,
    menu_code           VARCHAR(50)     NOT NULL,
    menu_name           VARCHAR(255)    NOT NULL,
    production_date     DATE            NOT NULL,

    sold                INTEGER         NOT NULL,
    waste               INTEGER         NOT NULL,
    -- Koreksi, boleh negatif.
    adjustment          INTEGER         NOT NULL,
    compensation        INTEGER         NOT NULL,

    CONSTRAINT uq_closing_report_items_menu_date UNIQUE (revision_id, menu_id, production_date),
    CONSTRAINT ck_closing_report_items_qty CHECK (sold >= 0 AND waste >= 0 AND compensation >= 0)
);

CREATE INDEX IF NOT EXISTS ix_closing_report_items_menu_date
    ON closing_report_items (menu_code, production_date);


CREATE TABLE IF NOT EXISTS closing_menus (
    id                  SERIAL          PRIMARY KEY,

    menu_code           VARCHAR(50)     NOT NULL,
    -- menuId / menuName terakhir yang terlihat di pesan, untuk tampilan.
    menu_id             UUID            NOT NULL,
    menu_name           VARCHAR(255)    NOT NULL,

    first_seen_at       TIMESTAMP       NOT NULL DEFAULT NOW(),
    last_seen_at        TIMESTAMP       NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_closing_menus_menu_code UNIQUE (menu_code)
);


CREATE TABLE IF NOT EXISTS closing_menu_products (
    id                  SERIAL          PRIMARY KEY,

    closing_menu_id     INTEGER         NOT NULL REFERENCES closing_menus (id),
    product_id          INTEGER         NOT NULL,
    -- Salinan untuk tampilan; pencocokan hanya lewat product_id.
    product_name        VARCHAR(255)    DEFAULT NULL,
    multiplier          INTEGER         NOT NULL DEFAULT 1,
    is_active           BOOLEAN         NOT NULL DEFAULT TRUE,

    created_at          TIMESTAMP       NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMP       DEFAULT NULL,

    CONSTRAINT uq_closing_menu_products_menu_product UNIQUE (closing_menu_id, product_id),
    CONSTRAINT ck_closing_menu_products_product_id CHECK (product_id > 0),
    CONSTRAINT ck_closing_menu_products_multiplier CHECK (multiplier > 0)
);

CREATE INDEX IF NOT EXISTS ix_closing_menu_products_product
    ON closing_menu_products (product_id);
