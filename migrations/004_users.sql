-- ============================================================
-- Migration 004: Tabel users (login dashboard / frontend terpisah)
-- ============================================================
--
-- Terpisah dari api_keys:
--   api_keys → mesin POS, untuk endpoint /api/sync/*
--   users    → manusia, untuk endpoint baca yang dipakai frontend
--
-- Role:
--   admin   — akses penuh semua outlet
--   manager — baca data semua outlet
--   outlet  — baca data outletnya sendiri saja (outlet_code wajib diisi)
--
-- Password disimpan sebagai hash bcrypt, tidak pernah plaintext.
-- Buat user pertama dengan:
--   python manage_users.py create --email admin@maharasa.id --role admin
-- ============================================================

CREATE TABLE IF NOT EXISTS users (
    id              SERIAL          PRIMARY KEY,

    email           VARCHAR(255)    NOT NULL,
    password_hash   VARCHAR(255)    NOT NULL,
    full_name       VARCHAR(255)    DEFAULT NULL,

    role            VARCHAR(20)     NOT NULL DEFAULT 'outlet',
    outlet_code     VARCHAR(20)     DEFAULT NULL,

    is_active       BOOLEAN         NOT NULL DEFAULT TRUE,

    created_at      TIMESTAMP       NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP       DEFAULT NULL,

    CONSTRAINT uq_users_email UNIQUE (email),
    CONSTRAINT ck_users_role CHECK (role IN ('admin', 'manager', 'outlet')),

    -- Role 'outlet' tanpa outlet_code akan selalu ditolak 403 oleh aplikasi.
    -- Ditegakkan di database supaya tidak bisa masuk lewat jalur lain.
    CONSTRAINT ck_users_outlet_scope CHECK (
        role <> 'outlet' OR outlet_code IS NOT NULL
    )
);

CREATE INDEX IF NOT EXISTS idx_users_email
    ON users (email);

CREATE INDEX IF NOT EXISTS idx_users_outlet
    ON users (outlet_code);
