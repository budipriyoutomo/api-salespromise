# TODO — Sync API (Persiapan Pengembangan & Pemisahan Frontend)

Dibuat: 2026-09-11 · Basis commit: `b66417f`

Status: **Fase 0, 1, 2, dan 4 selesai. Fase 3 sebagian besar selesai.**
Sisa: Alembic, idempotensi publish, bulk upsert, structured logging,
rate limiting endpoint sync — semuanya **tidak memblokir frontend**.

Backend siap dipakai frontend terpisah: CORS aktif, auth user terpisah dari
API key mesin POS, data ter-scope per outlet, response ter-skema, dan endpoint
admin untuk mengelola key maupun user sudah tersedia.

Pengembangan memakai **TDD**: tulis test dulu, baru kodenya.
Lihat [tests/README.md](tests/README.md).

---

## Fase 0 — Bug Blocker ✅ SELESAI

Dikerjakan 2026-09-11 dengan TDD (test dulu, baru kode).

- [x] **0.1 `GET /api/sales/colorplate` pakai class `Request`.** Sekarang outlet
      diambil dari identitas user lewat `resolve_outlet_scope`.
      Penjaga: `test_routes_sales.py::test_outlet_di_scope_dari_identitas`
- [x] **0.2 Signature colorplate tidak cocok.** Kontraknya disatukan jadi
      `start_date` + `end_date`. Route publish mengirim tanggal yang sama untuk
      keduanya (rentang satu hari).
- [x] **0.3 `get_sales` memfilter kolom yang tidak ada.** `Sales.outlet` menjadi
      `Sales.outlet_code`, `Sales.sales_date` menjadi `Sales.sale_date`.
- [x] **0.4 File migrasi ketinggalan dari produksi.**
      `migrations/002_unique_indexes.sql` — **kode tidak diubah**, `index_elements`
      tetap `["TransactionID", "outlet_code"]` sesuai instruksi.
      Migrasinya memeriksa **kolom** index, bukan namanya, jadi aman dijalankan
      di database yang index-nya sudah ada dengan nama berbeda — terdeteksi dan
      dilewati, bukan diduplikasi. Sudah diuji terhadap database asli.
- [x] **0.6 `updated_at` di `api_keys`.** Ditambahkan lewat migrasi 003.
- [x] **0.7 `HTTPException` di middleware jadi 500.** Middleware dihapus,
      diganti dependency — 401 sekarang keluar sebagai JSON yang benar.
- [x] **0.8 Health `/` kena auth.** `/` dan `/health` terbuka.
      Catatan: `EXCLUDED_PATHS` lama memakai `startswith`, jadi menambahkan `"/"`
      ke daftar itu akan membuka **seluruh** endpoint. Masalah itu hilang dengan
      sendirinya setelah pindah ke dependency.
- [x] **0.9 Kredensial di `consumer.py`.** Sekarang wajib dari env, tanpa default.
      Password lama tetap perlu dirotasi — sudah terlanjur masuk git history.
- [x] **0.10 `requirements.txt` UTF-16.** Ditulis ulang sebagai UTF-8.

### Ditunda atas keputusanmu

- [ ] **0.5 `orderdetail` tanpa `outlet_code`.**
      Query pemeriksaannya sudah disiapkan di
      `migrations/checks/orderdetail_outlet_collision.sql` — tiga query read-only
      untuk memastikan apakah tabrakan antar outlet benar-benar terjadi di data
      produksi. Kalau query pertama mengembalikan nol baris, item ini bisa ditutup
      tanpa perubahan apa pun.

---

## Fase 1 — Fondasi Frontend Terpisah ✅ SELESAI

- [x] **1.1 CORS.** Origin dibaca dari env `CORS_ORIGINS` (dipisah koma),
      `allow_credentials=False` karena token lewat header. Bukan `*`.
- [x] **1.2 Pemisahan auth.** API key outlet hanya untuk `/api/sync/*` dan
      `/api/sales/publish`; JWT user untuk endpoint baca. Keduanya saling menolak.
- [x] **1.3 Tabel & model `users`** + role admin/manager/outlet.
      CHECK constraint di DB menolak role `outlet` tanpa `outlet_code`.
- [x] **1.4 Endpoint auth:** `login`, `refresh`, `me`, `logout`.
- [x] **1.5 Outlet scoping.** Celah lama ditutup: `?outlet=` tidak lagi diteruskan
      mentah. User role `outlet` yang meminta outlet lain mendapat 403.
- [x] **1.6 API key di-hash.** SHA-256, key lama tetap berlaku
      (migrasi 003 menghitung hash dari key yang sudah tersimpan).
      `manage_keys.py list` hanya menampilkan prefix.
- [x] **1.7 Pagination.** `limit` (default 50, maks 500) + `offset`, urutan
      deterministik, plus `total` dan `has_more` di response.
- [x] **1.8 Response model.** Objek ORM tidak lagi dikirim mentah; OpenAPI
      lengkap sehingga frontend bisa men-generate tipe.
- [x] **1.9 Validasi tanggal.** `start_date`/`end_date` bertipe `date`, format
      salah ditolak 422.

### Tambahan yang ikut dikerjakan

- [x] `manage_users.py` — CLI user dashboard. Tanpa ini tidak ada cara membuat
      user pertama, jadi frontend tidak akan pernah bisa login.
- [x] `GET /api/outlets` (item 2.6) — diperlukan untuk menguji `require_roles`.
- [x] Penjaga auth di `tests/unit/test_app_wiring.py` — endpoint `/api` baru yang
      lupa diberi dependency auth langsung membuat test gagal.
- [x] Index `(outlet_code, "SaleDate")` (item 2.8) — ikut di migrasi 002.

### Yang berubah dan perlu diperhatikan saat deploy

1. **`JWT_SECRET` wajib.** Aplikasi menolak start tanpa itu. Sudah ditambahkan
   ke `.env` lokal dan `.env.example`; server produksi perlu diisi manual.
2. **Migrasi 003 harus jalan bersamaan dengan deploy.** Di antara deploy kode
   baru dan migrasi, API key lama tidak akan cocok — kode mencari hash,
   database masih menyimpan plaintext. Window-nya singkat tapi nyata.
3. **`app/middleware/api_key_auth.py` dihapus.** Diganti `app/dependencies/auth.py`.
4. **Bentuk response `GET /api/sales/` berubah** — sekarang ada objek `pagination`,
   dan field baris dibatasi response model.
5. **`POST /api/sales/publish` tetap memakai API key**, bukan JWT, karena
   dipicu mesin POS.

---

## Fase 2 — Endpoint Dashboard ✅ SELESAI

- [x] 2.1 `GET /api/sales/summary` — omzet, jumlah transaksi, diskon, rata-rata per struk.
- [x] 2.2 `GET /api/sales/daily` — time series harian, terurut kronologis.
- [x] 2.3 `GET /api/sales/by-outlet` — perbandingan antar outlet, khusus admin & manager.
- [x] 2.4 `GET /api/sales/top-products` — ranking produk, bisa difilter `product_group`.
- [x] 2.5 `GET /api/sales/{transaction_id}` — detail transaksi + item.
      Transaksi outlet lain menghasilkan 404, bukan 403, supaya nomor transaksi
      tidak bisa dipetakan lewat beda status code.
- [x] 2.6 `GET /api/outlets` — daftar outlet untuk dropdown filter.
- [x] 2.7 Status sync per outlet — dipasang di `GET /api/outlets/sync-status`,
      bukan `/api/sync/status` seperti rencana awal: prefix `/api/sync` khusus
      autentikasi mesin POS, sedangkan ini dibaca manusia lewat dashboard.
- [x] 2.8 Index `(outlet_code, "SaleDate")` — ada di `002_unique_indexes.sql`.
- [x] 2.9 Export CSV — `GET /api/sales/export`, tanpa pagination, ter-scope per outlet.

### Perbedaan perilaku yang perlu diketahui

Endpoint laporan **mengecualikan** transaksi `Deleted=1`; `GET /api/sales/` dan
`/colorplate` masih ikut menghitungnya. Ini disengaja — mengubah endpoint lama
akan mengubah angka yang sudah dipublish ke RabbitMQ. Keputusannya ada di
item 4.5, dan sekarang jadi lebih mendesak karena dua endpoint menampilkan
angka yang berbeda untuk data yang sama.

---

## Fase 3 — Kualitas Kode & Infrastruktur (sebagian selesai)

### Selesai

- [x] **3.8a Rate limiting login.** `app/core/rate_limit.py`, sliding window
      per alamat pemanggil, default 10 percobaan / 5 menit, `429` + `Retry-After`.
      Dikunci per alamat, bukan per email — kalau per email, penyerang justru
      bisa mengunci akun orang lain dengan sengaja mengirim password salah.
      **Keterbatasan:** hitungan disimpan di memori proses, jadi dengan gunicorn
      4 worker batas efektifnya 4x lipat. Untuk penegakan sungguhan perlu Redis.
- [x] **3.2 `datetime.utcnow()` deprecated.** Diganti `app/core/time.py::utcnow()`
      yang mengembalikan datetime **naive-UTC**. Sengaja bukan
      `datetime.now(timezone.utc)` langsung: kolom DB bertipe `TIMESTAMP` tanpa
      timezone, dan mengisi datetime ber-timezone bisa menggeser nilai tersimpan
      beberapa jam dari data lama.
- [x] **3.3 Koneksi RabbitMQ bocor.** `get_rabbitmq_client()` sekarang generator
      dependency yang menutup koneksi di `finally`. Tidak dijadikan singleton
      karena `pika.BlockingConnection` tidak thread-safe sedangkan endpoint sync
      dijalankan di threadpool.
- [x] **3.6 Batas payload sync.** `MAX_SALES_PER_REQUEST` (default 1000),
      ditolak 422 di layer schema sebelum menyentuh database.
- [x] **3.9 Konfigurasi RabbitMQ terpusat** di `app/config.py`.
      `RABBITMQ_PASSWORD` tidak lagi punya default.
- [x] **3.10 `requirements-dev.txt` terpisah.**
- [x] **3.11 CI GitHub Actions** — lint (ruff) + unit test + **test integrasi
      terhadap PostgreSQL sungguhan**. Ini yang akhirnya akan memverifikasi item 0.4.
- [x] **3.12 `GET /health/ready`** — memeriksa database, 503 kalau bermasalah.
      `/health` sengaja tetap tidak menyentuh DB (liveness probe).
- [x] **3.13 Nama file migrasi** — `inital_schema.sql` → `001_initial_schema.sql`.
- [x] **3.14 README disinkronkan** dengan kode.
- [x] **Guard `init_db.py`.** `drop_all()` hanya jalan kalau
      `INIT_DB_CONFIRM=DROP-ALL` diisi persis.
- [x] **Konfigurasi dibaca saat instansiasi**, bukan saat class dibuat.
      Versi lama membuat test perlu `importlib.reload(app.config)`, dan itu
      menghasilkan objek `settings` baru sementara modul lain masih memegang
      yang lama — sumber kegagalan yang hanya muncul saat suite penuh dijalankan.

### Belum dikerjakan

- [ ] **3.1 Alembic.** Migrasi masih SQL manual bernomor. Guard `drop_all` sudah
      dipasang, tapi versioning skema yang sesungguhnya belum ada.
- [ ] **3.4 Publish belum idempoten.** Memanggil `/publish` dua kali untuk tanggal
      yang sama masih mengirim event dobel. Butuh `message_id` + tabel jejak publish.
      Perlu dibahas dulu: apakah consumer di sisi sana sudah idempoten?
- [ ] **3.5 Bulk upsert.** `sync_sales` masih `execute` per baris. Menyentuh jalur
      sync produksi, jadi sengaja tidak digabung dengan perubahan lain — sebaiknya
      dikerjakan sendiri setelah test integrasi pernah dijalankan sungguhan.
- [ ] **3.7 Structured logging JSON + `request_id`.**
- [ ] **3.8b Rate limiting endpoint sync.** Sengaja BELUM dipasang: mesin POS
      yang mengirim backlog besar setelah offline bisa tertahan sendiri.
      Perlu diukur dulu pola sync yang wajar sebelum menentukan batasnya.

---

## Fase 4 — Unit Test ✅ SELESAI

Dikerjakan 2026-09-11. Hasil: **197 passed, 11 xfailed, 12 skipped**, coverage **95%**.
Cara menjalankan dan konvensinya ada di [tests/README.md](tests/README.md).

- [x] 4.0 Setup — `pytest.ini`, `requirements-dev.txt`, `tests/conftest.py`,
      SQLite in-memory, factory data, client ber-autentikasi.
- [x] 4.1 `app/config.py` — 16 test (URL-encoding password, `validate()`, default env).
- [x] 4.2 Middleware API key — 22 test (header rusak, key nonaktif, `request.state`,
      penutupan session, path publik).
- [x] 4.3 `sync_sales` — 33 test (pemetaan kolom, klausa `ON CONFLICT`, urutan
      eksekusi, rollback, logging).
- [x] 4.4 `get_sales` — 8 test.
- [x] 4.5 `get_sales_colorplate` — 12 test (grouping, filter, join, item yatim).
- [x] 4.6 Schema Pydantic — 35 test.
- [x] 4.7 Route — 36 test (`/api/sync/sales`, `/api/sales`, `/colorplate`, `/publish`).
- [x] 4.8 `RabbitMQClient` — 18 test (pika di-mock).
- [x] 4.9 `manage_keys.py` — 19 test.
- [x] 4.11 Kerangka test integrasi Postgres — `tests/integration/test_sync_postgres.py`,
      dilewati otomatis kalau `TEST_DATABASE_URL` tidak diset.
- [x] `app/database.py` — 6 test (dependency `get_db`, konfigurasi pool).

### Sisa pekerjaan test

- [x] **4.10 Test auth user & RBAC** — selesai bersamaan dengan Fase 1
      (`test_auth_dependencies.py`, `test_routes_auth.py`).
- [ ] **Jalankan test integrasi minimal sekali** terhadap Postgres sungguhan.
      Ini yang akan memverifikasi item 0.4:
      ```bash
      TEST_DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/sync_test pytest tests/integration -v
      ```
- [x] Pasang CI (item 3.11) — `.github/workflows/tests.yml` menjalankan lint,
      unit test, dan test integrasi Postgres tiap push dan pull request.
- [ ] Tambah test tiap kali ada fitur baru — **tulis test lebih dulu**.

### Bug yang sudah terkunci oleh test

Semua `xfail` dari Fase 0 dan 1 sudah hijau dan markernya dihapus. Tinggal satu
yang tersisa, dan itu bukan bug melainkan keputusan yang belum diambil:

| Item | Test penjaga |
|---|---|
| 4.5 — transaksi `Deleted=1` ikut dihitung di colorplate? | `test_sales_service_queries.py::test_transaksi_terhapus_tidak_ikut_dihitung` |

---

## Fase 5 — Frontend Terpisah (repo sendiri)

**Backend sudah siap.** Semua endpoint yang dibutuhkan halaman di bawah ini
sudah ada, ter-skema di OpenAPI, dan ter-scope per outlet.

> Stack dipilih: **Next.js**. Repo dibuat di `D:\Project\maharasa\sync-frontend`,
> dan rencana kerja lengkapnya ada di `TODO.md` repo itu — termasuk kontrak API
> terverifikasi, matriks hak akses per role, dan daftar test.
>
> Pekerjaan backend yang memblokir frontend:
> - [x] omzet salah kolom → diperbaiki, omzet kini dari `ReceiptPayPrice`
> - [ ] **0.6 bentuk response tidak seragam** — `/api/auth/*` mengembalikan
>       objek polos, sisanya dibungkus `{success, data}`. Masih terbuka;
>       menyeragamkan lebih murah sekarang daripada setelah frontend jadi.

- [x] 5.1 Tentukan stack (Next.js / Vite+React / Nuxt) dan repo terpisah.
- [ ] 5.2 Generate API client dari `/openapi.json`.
- [ ] 5.3 Halaman login + penyimpanan token.
- [ ] 5.4 Dashboard: kartu ringkasan, grafik harian, filter outlet & tanggal.
- [ ] 5.5 Halaman daftar transaksi + detail.
- [ ] 5.6 Halaman manajemen API key outlet — endpoint `/api/api-keys` **sudah ada**.
- [ ] 5.7 Halaman manajemen user — endpoint `/api/users` **sudah ada**.
- [ ] 5.8 Halaman status sync per outlet — `/api/outlets/sync-status`.
- [ ] 5.9 Auto-refresh token + handling 401 global.
- [ ] 5.10 Env `API_BASE_URL` per environment.
- [ ] 5.11 Test frontend (Vitest + Testing Library) dan E2E (Playwright).

### Sebelum mulai — langkah di sisi backend

1. Jalankan migrasi 002, 003, 004 ke database yang dipakai.
2. Buat user admin: `python manage_users.py create --email ... --role admin`
3. Sesuaikan `CORS_ORIGINS` dengan origin frontend
   (Next.js `:3000`, Vite `:5173`).

---

## Keputusan

### Sudah diputuskan

1. **`TransactionID` unik per outlet.** Kunci konflik `(TransactionID, outlet_code)`
   sudah berjalan di produksi dan **tidak diubah**. Yang disinkronkan hanya file
   migrasinya (`002_unique_indexes.sql`).
2. **Auth frontend: JWT Bearer token.** Token dikirim lewat header `Authorization`,
   bukan cookie — karena itu CORS memakai `allow_credentials=False` dan tidak
   perlu proteksi CSRF. Kalau nanti ada aplikasi mobile, jalur ini sudah siap.
3. **API key di-hash di tempat.** Key yang sudah beredar di mesin POS tetap
   berlaku; tidak ada outlet yang perlu di-update manual.
4. **`orderdetail` ditunda** sampai data produksi diperiksa — lihat item 0.5.

### Masih terbuka

1. **Frontend baca dari DB yang sama atau lewat service read terpisah (CQRS)?**
   Kalau volume sync besar, query agregat dashboard bisa mengganggu jalur sync.
   Belum mendesak: pagination sudah membatasi beban query terberat.
2. **Colorplate satu-satunya konsumen event RabbitMQ?** Perlu dikonfirmasi supaya
   desain exchange/routing key tidak berubah lagi nanti.
3. **Transaksi `Deleted=1` / void ikut dihitung di rekap colorplate?**
   Sekarang ikut terhitung. Ada test `xfail` yang menunggu keputusan ini.
4. **Masa berlaku token.** Sekarang access 30 menit, refresh 7 hari. Perlu
   disesuaikan kalau kasir membuka dashboard seharian penuh.
5. **Pencabutan token.** JWT stateless — logout hanya membuang token di klien.
   Kalau perlu memutus akses seketika (mis. karyawan keluar), butuh denylist
   token di Redis/DB. Sementara ini, `manage_users.py deactivate` sudah memutus
   akses karena status user dicek ulang di setiap request.
