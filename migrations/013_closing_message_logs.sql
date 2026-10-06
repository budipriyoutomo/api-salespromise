-- ============================================================
-- Migration 013: Log pesan closing report dari RabbitMQ
-- ============================================================
--
-- Setiap pesan `closingreport.submitted` yang diputuskan consumer (ack atau
-- DLQ) dicatat satu baris, supaya admin bisa memeriksa dari dashboard pesan
-- apa yang datang, isinya, dan kenapa ditolak — tanpa membuka log server atau
-- RabbitMQ Management.
--
--   status       baru / revisi / revisi_lama / duplikat  (tersimpan, di-ack)
--                ditolak                                 (masuk DLQ)
--   reason       alasan penolakan, mis. "gagal validasi"
--   errors       detail error validasi (loc / msg / type)
--   warnings     catatan untuk pesan yang tetap disimpan, mis. outlet belum
--                terdaftar, compensation negatif
--   payload      JSON pesan apa adanya; body_text kalau bukan JSON
--   message_id / outlet_code diambil dari payload walau pesannya ditolak;
--   closing_report_id / report_date / item_count hanya untuk pesan yang lolos
--   validasi
--
-- Pesan yang dikembalikan ke antrean karena database putus tidak dicatat —
-- ia dicatat saat diproses ulang.
--
-- Hanya CREATE TABLE / CREATE INDEX. Tidak ada seed, dan tabel lain tidak
-- disentuh. Tidak ada pembersihan otomatis.
--
-- Idempotent: aman dijalankan ulang.
-- ============================================================

CREATE TABLE IF NOT EXISTS closing_message_logs (
    id                  BIGSERIAL       PRIMARY KEY,

    received_at         TIMESTAMP       NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    status              VARCHAR(20)     NOT NULL,
    reason              VARCHAR(255)    DEFAULT NULL,
    errors              JSONB           DEFAULT NULL,
    warnings            JSONB           DEFAULT NULL,

    message_id          VARCHAR(255)    DEFAULT NULL,
    closing_report_id   UUID            DEFAULT NULL,
    outlet_code         VARCHAR(255)    DEFAULT NULL,
    report_date         DATE            DEFAULT NULL,
    item_count          INTEGER         DEFAULT NULL,
    revision_id         INTEGER         DEFAULT NULL REFERENCES closing_report_revisions (id),

    body_bytes          INTEGER         NOT NULL,
    payload             JSONB           DEFAULT NULL,
    body_text           TEXT            DEFAULT NULL,

    CONSTRAINT ck_closing_message_logs_status
        CHECK (status IN ('baru', 'revisi', 'revisi_lama', 'duplikat', 'ditolak'))
);

CREATE INDEX IF NOT EXISTS ix_closing_message_logs_received_at
    ON closing_message_logs (received_at);

CREATE INDEX IF NOT EXISTS ix_closing_message_logs_status_received_at
    ON closing_message_logs (status, received_at);

CREATE INDEX IF NOT EXISTS ix_closing_message_logs_message_id
    ON closing_message_logs (message_id);
