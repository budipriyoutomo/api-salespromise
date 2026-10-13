-- ============================================================
-- Migration 016: Log kirim rekap closing ke API eksternal (TODO Fase 8)
-- ============================================================
--
-- Admin menekan "Kirim" di /closing untuk satu outlet × satu tanggal
-- produksi; satu baris per kiriman. Kontrak: docs/usulan-kontrak-kirim-closing.md.
--
--   sequence      naik 1 per kiriman baru untuk outlet + tanggal yang sama;
--                 API tujuan menolak sequence yang lebih lama
--   message_id    unik per kiriman; dipakai ulang saat kiriman yang gagal
--                 diulang, supaya API tujuan bisa mengenali duplikat
--   content_hash  sha256 isi (outlet, tanggal, items) — dibandingkan dengan
--                 rekap terkini untuk status "perlu kirim ulang"
--   status        mengirim  dicatat sebelum request berangkat; dianggap macet
--                           kalau started_at lebih dari 5 menit lalu (proses
--                           mati di tengah jalan) — ditandai gagal saat
--                           outlet + tanggal itu dikirim lagi
--                 terkirim  2xx
--                 duplikat  409, isi sudah ada di API tujuan
--                 gagal     4xx lain, atau 429/5xx/timeout setelah retry habis
--   payload       body JSON persis seperti yang dikirim
--   response_body potongan body response API tujuan
--   started_at    awal percobaan terakhir (diperbarui saat kirim ulang)
--
-- Hanya CREATE TABLE / CREATE INDEX. Tidak ada seed, tabel lain tidak
-- disentuh, dan tidak ada pembersihan otomatis.
--
-- Idempotent: aman dijalankan ulang.
-- ============================================================

CREATE TABLE IF NOT EXISTS closing_export_logs (
    id                  BIGSERIAL       PRIMARY KEY,

    outlet_code         VARCHAR(20)     NOT NULL,
    production_date     DATE            NOT NULL,
    sequence            INTEGER         NOT NULL,
    message_id          UUID            NOT NULL,
    content_hash        VARCHAR(64)     NOT NULL,
    item_count          INTEGER         NOT NULL,
    payload             JSONB           NOT NULL,

    status              VARCHAR(20)     NOT NULL,
    attempts            INTEGER         NOT NULL DEFAULT 0,
    http_status         INTEGER         DEFAULT NULL,
    response_body       TEXT            DEFAULT NULL,
    error               VARCHAR(255)    DEFAULT NULL,

    sent_by             VARCHAR(255)    NOT NULL,
    created_at          TIMESTAMP       NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    started_at          TIMESTAMP       NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    finished_at         TIMESTAMP       DEFAULT NULL,

    CONSTRAINT uq_closing_export_logs_message_id UNIQUE (message_id),
    CONSTRAINT uq_closing_export_logs_sequence UNIQUE (outlet_code, production_date, sequence),
    CONSTRAINT ck_closing_export_logs_status
        CHECK (status IN ('mengirim', 'terkirim', 'duplikat', 'gagal')),
    CONSTRAINT ck_closing_export_logs_sequence CHECK (sequence > 0),
    CONSTRAINT ck_closing_export_logs_attempts CHECK (attempts >= 0)
);

CREATE INDEX IF NOT EXISTS ix_closing_export_logs_created_at
    ON closing_export_logs (created_at);

CREATE INDEX IF NOT EXISTS ix_closing_export_logs_status_created_at
    ON closing_export_logs (status, created_at);
