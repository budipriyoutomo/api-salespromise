# TODO — Sync API (Persiapan Pengembangan & Pemisahan Frontend)

Dibuat: 2026-09-11 · Basis commit: `b66417f`

Status: **Fase 0, 1, 2, 4, dan 5 selesai. Fase 3 sebagian besar selesai.
Fase 6 selesai di backend.**
Sisa: Alembic, idempotensi publish, bulk upsert, rate limiting endpoint sync,
halaman product group di frontend — semuanya **tidak memblokir frontend**.

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
      produksi. ~~Kalau query pertama mengembalikan nol baris, item ini bisa ditutup
      tanpa perubahan apa pun.~~ **Keliru — lihat temuan di bawah.**

      **Temuan 2026-09-15** — diperiksa read-only (`readonly=True`, rollback) di
      database lokal `maharasa_pos` (PG 16, `localhost:5433`): 1 outlet (`STTSM`),
      14 transaksi, 85 item. **Bukan produksi**, jadi belum mewakili banyak outlet.

      1. **`ordertransaction` ber-PK `("TransactionID")` saja.** Index unik
         `(TransactionID, outlet_code)` ada, tapi PK sempit tetap berlaku. Outlet
         kedua yang mengirim TransactionID yang sudah dipakai outlet lain **gagal
         `UniqueViolation`** — seluruh batch sync-nya di-rollback, bukan menimpa.
         Karena itu query 1 **selalu** kosong; hasil kosong bukan bukti aman.
         **Terverifikasi** di salinan `maharasa_pos_uji` (pg_dump dari `maharasa_pos`,
         14/85 baris cocok): `sync_sales` sungguhan untuk `OUTLET_UJI` dengan
         TransactionID 6057 (milik STTSM) → `UniqueViolation` pada
         `ordertransaction_pkey`, `Key ("TransactionID")=(6057) already exists`.
         Data STTSM identik sebelum & sesudah. Database asli hanya dibaca.
      2. **`OrderDetailID` = nomor baris per transaksi** (selalu 1..N). Begitu
         TransactionID berbagi antar outlet, kunci item ikut bertabrakan.
      3. **FK `orderdetail("TransactionID")` → `ordertransaction("TransactionID")`**
         bergantung pada PK sempit itu.
      4. Model SQLAlchemy juga PK `transaction_id` saja, sehingga
         `tests/integration/test_sync_postgres.py::test_transaction_id_sama_dari_dua_outlet_tersimpan_terpisah`
         kemungkinan besar **gagal** kalau dijalankan — test integrasi belum pernah jalan.
      5. Query yang men-join item ke transaksi hanya lewat `TransactionID`:
         `get_sales_colorplate`, `get_top_products`, `get_sale_detail` (item).
      6. `schema_migrations` belum ada di DB lokal — index outlet dibuat manual.

      Kesimpulan: masalahnya **struktural**, bukan soal data. Selama hanya ada satu
      outlet belum ada kerusakan; outlet kedua dengan TransactionID yang tumpang
      tindih akan langsung gagal sync.

      **Rencana (menunggu persetujuan — migrasi otomatis jalan saat container start):**
      - [ ] Migrasi `007_outlet_code_composite_keys.sql` (006 sudah dipakai Fase 6), **tanpa DELETE**, satu transaksi:
            pra-cek (abort kalau ada `outlet_code` NULL / item yatim), `orderdetail`
            tambah `outlet_code` + backfill dari `ordertransaction`, PK kedua tabel
            menjadi komposit dengan `outlet_code`, FK komposit, index unik upsert item
            ditambah `outlet_code`. Yang di-drop hanya constraint/index, bukan baris.
      - [ ] Kode: model, `sync_sales` (kirim `outlet_code` di item + `index_elements`),
            join 3 query di atas memakai `outlet_code`.
      - [ ] Test unit (TDD) + test integrasi dua outlet dengan TransactionID &
            OrderDetailID yang sama.
      - [ ] Uji migrasi pada **salinan** database (`pg_dump` → DB terpisah), bukan aslinya.
      - [ ] Jalankan `migrations/checks/orderdetail_outlet_collision.sql` di **produksi**
            (read-only) sebelum deploy.

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

Sejak dashboard dibangun, `SaleResponse` **mengekspos kolom `deleted`**
(`tests/unit/test_sales_response_deleted.py`). Aditif, tanpa migrasi — kolomnya
sudah ada di tabel. Frontend memakainya untuk menandai struk yang dibatalkan.

Itu membuat inkonsistensi di atas jadi kelihatan oleh pengguna, bukan lagi
hanya di catatan ini: tabel transaksi menampilkan baris bertanda "Void" yang
tidak ikut terhitung di kartu ringkasan. Sampai item 4.5 diputuskan, selisih
itu memang akan terlihat.

### Kolom `must_change_password` pada `users`

Ditambahkan untuk dashboard (item 2.8 di `TODO.md` sync-frontend). Migrasi
`005_must_change_password.sql`, dikunci `tests/unit/test_must_change_password.py`.

Siklus hidupnya ada di `app/services/user_service.py`:

| jalur | penanda |
|---|---|
| `create_user` | TRUE — password ditentukan orang lain |
| `set_password` (reset oleh admin) | TRUE |
| `ganti_password_sendiri` | FALSE — pemiliknya memilih sendiri |

`set_password` dan `ganti_password_sendiri` sengaja dipisah walau keduanya
menulis hash: yang membedakan bukan nilainya, melainkan **siapa** yang memilih.
`POST /api/auth/change-password` memakai yang kedua.

DEFAULT-nya FALSE, bukan TRUE. Baris yang sudah ada dibuat sebelum kolom ini
lahir; memberi TRUE pada mereka akan memaksa setiap user yang sedang berjalan
mengganti password pada login berikutnya — mengunci orang demi kerapian.

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
- [x] **3.7 Structured logging JSON + `request_id`.** Dikerjakan 2026-09-15, TDD
      (`tests/unit/test_structured_logging.py`, 56 test).
      - `LOG_FORMAT=json` (default) / `text`; nilai lain ditolak `validate()` saat start.
        `LOG_FILE` baru, default `logs/api.log` — test suite mengarahkannya ke
        `os.devnull` supaya `LOGIN GAGAL` palsu tidak tercampur ke log developer.
      - `request_id` di contextvar (`app/core/request_context.py`), ikut terbawa ke
        thread pool endpoint `def`. Semua `logger.*` yang sudah ada otomatis
        membawanya — tidak ada pemanggilan log yang perlu diubah.
      - `RequestIdMiddleware` (`app/core/request_logging.py`), ASGI murni, paling luar.
        Memakai `X-Request-ID` dari klien kalau cocok `[A-Za-z0-9._-]{1,128}`
        (mencegah log injection), selain itu `uuid4().hex`. Selalu dikembalikan di header.
      - Access log satu baris per request: `method`, `path` (tanpa query string),
        `status_code`, `duration_ms`. INFO / WARNING (4xx) / ERROR (5xx + traceback).
        `/`, `/health`, `/health/ready` tidak dicatat.
      - Field tambahan cukup lewat `extra={...}`; `extra` tidak bisa menimpa field inti.

      **Perlu diperhatikan saat deploy:** format `logs/api.log` berubah dari teks
      ke JSON. Kalau ada yang mem-parse file itu, set `LOG_FORMAT=text` dulu.
      Respons 500 dari exception yang tidak tertangani **tidak** membawa header
      `X-Request-ID` (dibuat `ServerErrorMiddleware` Starlette di luar middleware
      ini), tapi log errornya tetap membawa `request_id`.
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

## Fase 5 — Frontend Terpisah (repo sendiri) ✅ SELESAI

> Checkbox di bawah disinkronkan 2026-09-15 dengan `TODO.md` sync-frontend,
> tempat seluruh fase padanannya sudah dicentang (1.5, 2.x, 4.x–9.x).

**Backend sudah siap.** Semua endpoint yang dibutuhkan halaman di bawah ini
sudah ada, ter-skema di OpenAPI, dan ter-scope per outlet.

> Stack dipilih: **Next.js**. Repo dibuat di `D:\Project\maharasa\sync-frontend`,
> dan rencana kerja lengkapnya ada di `TODO.md` repo itu — termasuk kontrak API
> terverifikasi, matriks hak akses per role, dan daftar test.
>
> Pekerjaan backend yang memblokir frontend:
> - [x] omzet salah kolom → diperbaiki, omzet kini dari `ReceiptPayPrice`
> - [x] **0.6 bentuk response tidak seragam** — `/api/auth/*` mengembalikan
>       objek polos, sisanya dibungkus `{success, data}`. **Diputuskan di
>       sync-frontend: backend tidak diubah**, client yang mengenali dua bentuk
>       (dikunci `src/lib/api/client.test.ts` di repo itu).

- [x] 5.1 Tentukan stack (Next.js / Vite+React / Nuxt) dan repo terpisah.
- [x] 5.2 Generate API client dari `/openapi.json` — `src/types/api.ts`, `npm run gen:api`.
- [x] 5.3 Halaman login + penyimpanan token — BFF, token di cookie httpOnly.
- [x] 5.4 Dashboard: kartu ringkasan, grafik harian, filter outlet & tanggal.
- [x] 5.5 Halaman daftar transaksi + detail.
- [x] 5.6 Halaman manajemen API key outlet.
- [x] 5.7 Halaman manajemen user.
- [x] 5.8 Halaman status sync per outlet.
- [x] 5.9 Auto-refresh token + handling 401 global — reaktif lewat proxy BFF.
- [x] 5.10 Env `API_BASE_URL` per environment — dibaca saat runtime.
- [x] 5.11 Test frontend (Vitest + Testing Library) dan E2E (Playwright).

### Sebelum mulai — langkah di sisi backend

1. Jalankan migrasi 002, 003, 004 ke database yang dipakai.
2. Buat user admin: `python manage_users.py create --email ... --role admin`
3. Sesuaikan `CORS_ORIGINS` dengan origin frontend
   (Next.js `:3000`, Vite `:5173`).

---

## Fase 6 — Product Group Dinamis (pengganti hardcode `COLORPLATE`)

Dibuat: 2026-09-15 · Status: **✅ backend selesai 2026-09-15** · Sisa: halaman frontend (F2)

Sebelumnya `SalesService.get_sales_colorplate` memfilter
`SalesItems.product_group == "COLORPLATE"` secara hardcode. Sekarang group yang
dipublish dibaca dari tabel `product_group_mappings` yang dikelola admin.

Hasil: **706 passed, 13 skipped, 1 xfailed** (sebelumnya 623 passed). Ruff bersih.

**Diverifikasi di salinan `maharasa_pos_uji`**, dalam satu transaksi yang
di-ROLLBACK (salinannya pun tidak berubah):

- migrasi 006 dijalankan 2× → tetap satu baris seed `COLORPLATE` (idempoten);
- CHECK menolak nama tidak normal (`' food'` → `CheckViolation`);
- `get_sales_colorplate` baru **identik** dengan query hardcode lama (7 vs 7 baris);
- query multi-group & `GROUP BY UPPER(TRIM("Group"))` diterima PostgreSQL;
  ` PROMO BANDUNG` terbaca sebagai `PROMO BANDUNG`;
- jumlah transaksi/item 14/85 sebelum dan sesudah.

### A. Keputusan (diputuskan 2026-09-15)

- [x] **A1 → Opsi 3:** tabel `product_group_mappings` + CRUD admin.
- [x] **A2 → `COLORPLATE` tetap `platecolor`, group lain generik**
      `{"group", "product", "outlet", "date", "sold"}`, exchange & routing key sama.
      Pemetaannya di kode (`LEGACY_EVENT_FIELDS` di `sales_routes.py`), bukan
      kolom tabel — kontrak consumer tidak boleh berubah lewat dashboard.
      **Masih perlu dikabarkan ke tim consumer** sebelum admin mengaktifkan group
      lain: event tanpa `platecolor` akan mulai muncul (Keputusan terbuka #2).
- [x] **A3 → alias dipertahankan.** `GET /colorplate` dan payload `platecolor` tetap.
- [x] **A4 → trim spasi + case-insensitive.** Dicocokkan dengan
      `UPPER(TRIM("Group"))`; data item tidak diubah. Hanya spasi yang di-trim
      (sama dengan `TRIM` di PostgreSQL/SQLite), bukan tab/newline.
- [ ] **A5. Transaksi `Deleted=1`** — tetap menunggu 4.5. Rekap per group masih
      ikut menghitungnya, sama seperti colorplate sebelum Fase 6.

### B. Database

- [x] B1. `migrations/006_product_group_mappings.sql`: `id`, `product_group`
      (UNIQUE + CHECK bentuk normal), `is_active`, `created_at`, `updated_at`.
      Tanpa `event_field`/`routing_key` karena A2 diputuskan di kode.
      **Hanya CREATE TABLE + INSERT** — `ordertransaction`/`orderdetail` tidak disentuh.
- [x] B2. Seed `COLORPLATE` aktif, `ON CONFLICT DO NOTHING` (status yang sudah
      diubah admin tidak ditimpa).
- [x] B3. Model `app/models/product_group_mapping.py`.

### C. Service

- [x] C1. `SalesService.get_sales_by_product_group`.
- [x] C2. `SalesService.get_sales_by_product_groups` — `product_group` ikut di
      `select` & `group_by`. Daftar kosong → `[]`, **bukan** semua group (kalau
      tidak, publish bisa mengirim seluruh penjualan).
- [x] C3. `get_sales_colorplate` jadi alias tipis.
- [x] C4. `product_group_service.get_active_groups` (service terpisah, pola
      `api_key_service`).
- [x] C5. `SalesService.list_product_groups` — group ter-normalisasi dari data, ter-scope outlet.

### D. Route

- [x] D1. `GET /api/sales/by-group?product_group=...` — boleh diulang untuk beberapa group.
- [x] D2. `GET /api/sales/product-groups`.
- [x] D3. `/colorplate` tetap, lewat alias di service.
- [x] D4. `POST /publish` membaca group aktif, satu query untuk semuanya.
      Tanpa group aktif → `200 "No active product groups to publish"` + log warning.
      Gagal di tengah: perilaku lama dipertahankan (500, event yang sudah terkirim
      tidak ditarik — TODO 3.4).
- [x] D5. `/api/product-groups`: `GET`, `POST` (409 untuk duplikat, termasuk yang
      nonaktif), `PATCH /{id}` untuk `is_active`. **Tidak ada DELETE** (405) dan nama
      tidak bisa diubah — salah ketik: buat baru, nonaktifkan yang lama.
- [x] D6. `ProductGroupSalesRow`, `ProductGroupListResponse`, `ProductGroupMapping*`.

### E. Test

- [x] E1. `test_sales_service_queries.py` (per group, multi-group tidak tercampur,
      normalisasi, daftar kosong), `test_product_group_service.py`.
- [x] E2. Test lama `get_sales_colorplate` hijau **tanpa diubah**.
- [x] E3. `test_routes_product_groups.py` — scope outlet, 422, RBAC admin, 405 DELETE.
- [x] E4. `test_struktur_event_yang_dipublish` hijau tanpa diubah, ditambah test
      bahwa field generik tidak menempel di event colorplate. Test publish kini
      me-mock `get_sales_by_product_groups` dan men-seed mapping `COLORPLATE`.
- [x] E5. `test_app_wiring.py` — endpoint baru di penjaga JWT & OpenAPI.
- [x] E6. Test integrasi ditulis di `test_sync_postgres.py`, **belum dijalankan**:
      fixture-nya `drop_all`, jadi hanya boleh diarahkan ke database kosong khusus
      test. Sebagai gantinya query diverifikasi di salinan (lihat atas).
- [x] Tambahan: `test_migrate.py` menolak migrasi bernomor yang memuat
      `DELETE FROM`, `TRUNCATE`, `DROP TABLE/COLUMN/SCHEMA/DATABASE`.

### F. Frontend & dokumentasi

- [x] F1. `src/types/api.ts` di sync-frontend di-generate ulang dari skema OpenAPI
      terbaru (`openapi-typescript`, hanya penambahan 345 baris); `tsc --noEmit` lolos.
- [ ] F2. Dropdown group dan halaman kelola mapping. Proxy BFF sudah meneruskan
      `GET`/`POST`/`PATCH`, jadi tidak perlu diubah; nav admin di
      `src/lib/auth/access.ts` perlu entri baru.
- [x] F3. README: `/by-group`, `/product-groups`, `/api/product-groups`, bentuk event generik.
- [x] F4. **`top-products` ikut dinormalisasi** (pemblokir frontend 10.11).
      Filter `product_group` sebelumnya mencocokkan nama persis, jadi nilai dari
      dropdown `/api/sales/product-groups` (`PROMO BANDUNG`) tidak menemukan item
      yang tersimpan sebagai `' PROMO BANDUNG'`. Sekarang filter memakai
      `UPPER(TRIM("Group"))`, varian nama untuk produk yang sama digabung jadi satu
      baris, dan `product_group` di response dalam bentuk normal. Spasi saja =
      tanpa filter. TDD: 4 test merah dulu (`test_sales_service_reports.py`,
      `test_routes_reports.py`).
- [x] F5. **Diverifikasi ke server yang berjalan** (uvicorn `:8001` terhadap salinan
      `maharasa_pos_uji`, token untuk user yang ada di salinan):
      - endpoint baru 22/22 sesuai — 200/201, 401 tanpa token, 403 manager & outlet
        di `/api/product-groups`, 403 outlet meminta outlet lain, 404, 405 `DELETE`,
        409 duplikat, 422 kosong/spasi; OpenAPI memuat 30 path;
      - `top-products` 6/6 — filter `' promo bandung'` = qty data mentah, tanpa
        produk ganda, semua nama group cocok dengan isi dropdown.

      **Salinan `maharasa_pos_uji` sekarang BERUBAH permanen** (bukan lagi identik
      dengan `maharasa_pos`): migrasi 006 terpasang, mapping `FOOD` nonaktif hasil uji
      POST/PATCH, dan dua user uji `uji.manager@maharasa.id` / `uji.outlet@maharasa.id`
      (outlet `STTSM`). Transaksi & item tetap 14/85. `maharasa_pos` tidak disentuh.

### Catatan deploy

1. Migrasi 006 jalan otomatis saat container start, sebelum gunicorn — kode dan
   tabel datang bersamaan.
2. Setelah deploy, publish identik dengan sebelumnya (hanya `COLORPLATE` aktif).
   Group lain baru terkirim setelah admin menambahkannya.
3. **Perubahan kecil yang disengaja (A4):** `/colorplate` dan publish kini ikut
   menghitung item bergroup `Colorplate` / `COLORPLATE `. Di data lokal tidak ada
   varian seperti itu, tapi cek produksi dulu (read-only):
   `SELECT '[' || "Group" || ']', COUNT(*) FROM orderdetail WHERE UPPER(TRIM("Group")) = 'COLORPLATE' GROUP BY 1;`
   Lebih dari satu baris = angka colorplate yang dipublish akan naik.
   Hal yang sama berlaku untuk `top-products`: varian nama group kini digabung,
   jadi ranking bisa berubah untuk produk yang dulu terpecah jadi dua baris.
4. **Performa:** `UPPER(TRIM("Group"))` tidak memakai index. Kalau `orderdetail`
   sudah besar dan query terasa lambat, opsinya index ekspresi di `orderdetail` —
   DDL di tabel data (tidak menghapus apa pun), tetap minta persetujuan dulu.

### Catatan di luar scope

Join di query ini hanya `Sales.transaction_id == SalesItems.transaction_id`,
padahal `TransactionID` unik **per outlet**. Item 0.5 sudah membuktikan PK-nya
masih sempit; perbaikannya menunggu keputusan di sana dan akan ikut memperbaiki
semua group sekaligus.

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
