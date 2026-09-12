-- ============================================================
-- Migration 003: API key di-hash + kolom updated_at
-- ============================================================
--
-- Sebelumnya kolom `key` menyimpan API key MENTAH. Siapa pun yang bisa membaca
-- tabel ini (dump backup, akses read-only, kebocoran DB) langsung memegang
-- kredensial semua outlet.
--
-- Setelah migrasi ini kolom `key` berisi SHA-256 hex dari key tersebut.
-- Nama kolom sengaja TIDAK diubah supaya primary key tidak perlu dibongkar;
-- di sisi aplikasi atributnya dinamai `key_hash` (app/models/api_key.py).
--
-- KEY YANG SUDAH BEREDAR TETAP BERLAKU — mesin POS di lapangan tidak perlu
-- diapa-apakan. Lookup berubah dari `WHERE key = :token` menjadi
-- `WHERE key = sha256(:token)`, dan nilai hash-nya dihitung dari key lama.
--
-- Migrasi ini idempoten: baris yang sudah berbentuk hash dilewati.
--
-- ------------------------------------------------------------
-- URUTAN: jalankan SEBELUM men-deploy kode baru? TIDAK.
-- Jalankan SETELAH kode baru siap di-deploy, dalam window singkat —
-- di antara keduanya, key lama tidak akan cocok. Kalau butuh tanpa downtime,
-- deploy dulu kode yang menerima keduanya, baru migrasi, baru bersihkan.
-- ============================================================


-- Kolom prefix: potongan awal key, supaya `manage_keys.py list` masih bisa
-- membantu mengenali baris tanpa membocorkan keseluruhan key.
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS key_prefix VARCHAR(12);

-- TODO 0.6 — model SQLAlchemy sudah punya kolom ini sejak awal, DDL-nya belum.
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP;


-- Backfill prefix dari key mentah — HARUS dijalankan sebelum key di-hash.
UPDATE api_keys
SET key_prefix = LEFT(key, 8)
WHERE key_prefix IS NULL
  AND key !~ '^[0-9a-f]{64}$';


-- Hash key mentah di tempat. Baris yang sudah berupa hash 64-hex dilewati,
-- sehingga migrasi ini aman dijalankan berulang.
UPDATE api_keys
SET key = encode(sha256(key::bytea), 'hex'),
    updated_at = NOW()
WHERE key !~ '^[0-9a-f]{64}$';


-- Verifikasi: seharusnya mengembalikan 0 baris.
-- SELECT outlet_code FROM api_keys WHERE key !~ '^[0-9a-f]{64}$';
