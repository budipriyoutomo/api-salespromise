-- ============================================================
-- Migration 005: Penanda password sementara pada tabel users
-- ============================================================
--
-- Latar: admin pertama dibuat dengan password sementara, dan setiap reset
-- oleh admin menghasilkan password yang diketahui orang lain. Tanpa penanda
-- di `UserResponse`, frontend tidak punya cara tahu itu, jadi tidak bisa
-- memaksa penggantian saat login pertama.
--
-- Siklus hidupnya (ditegakkan di `app/services/user_service.py`):
--   create_user            -> TRUE   (password ditentukan orang lain)
--   set_password           -> TRUE   (reset paksa oleh admin)
--   ganti_password_sendiri -> FALSE  (pemiliknya memilih sendiri)
--
-- DEFAULT FALSE, bukan TRUE — disengaja.
-- Baris yang sudah ada dibuat sebelum kolom ini lahir. Memberi TRUE pada
-- mereka akan memaksa setiap user yang sedang berjalan mengganti password
-- pada login berikutnya, termasuk yang passwordnya memang sudah rahasia.
-- Itu mengunci orang keluar demi kerapian belaka.
--
-- Idempotent: aman dijalankan ulang.
-- ============================================================

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE;

-- Kalau ingin memaksa seluruh user yang ada ikut mengganti password,
-- jalankan ini SECARA SADAR dan terpisah — bukan bagian dari migrasi:
--
--   UPDATE users SET must_change_password = TRUE;
