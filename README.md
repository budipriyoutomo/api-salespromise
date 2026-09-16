# Sales Sync API

FastAPI service untuk menerima data transaksi penjualan dari outlet, menyimpannya
ke PostgreSQL, dan menyediakan endpoint baca untuk dashboard frontend terpisah.

---

## Stack

- **Python** 3.10+
- **FastAPI**
- **SQLAlchemy** (PostgreSQL dialect)
- **Pydantic v2**
- **PostgreSQL 14+**
- **RabbitMQ** (publish event rekap per product group)
- **PyJWT + bcrypt** (auth user dashboard)

---

## Dua jalur autentikasi

Ini pembeda paling penting dari versi sebelumnya. Endpoint dibagi berdasarkan
**siapa** yang memanggilnya:

| Jalur | Dipakai oleh | Kredensial | Endpoint |
|---|---|---|---|
| API key outlet | Mesin POS | `Authorization: Bearer <API_KEY>` | `POST /api/sync/sales`, `POST /api/sales/publish` |
| JWT user | Frontend dashboard | `Authorization: Bearer <ACCESS_TOKEN>` | `GET /api/sales/`, `/by-group`, `/colorplate`, `/api/outlets`, `/api/auth/*` |

Keduanya tidak bisa saling menggantikan: API key outlet ditolak di endpoint
dashboard, dan JWT user ditolak di endpoint sync.

**API key disimpan sebagai hash SHA-256** — key mentah hanya ditampilkan sekali
saat dibuat, dan tidak tersimpan di mana pun.

**Outlet ditentukan identitas, bukan query param.** User dengan role `outlet`
yang mengirim `?outlet=OUTLET_LAIN` mendapat 403, bukan data outlet lain.

---

## Setup

### 1. Install dependency

```bash
cp .env.example .env
pip install -r requirements.txt

# untuk menjalankan test
pip install -r requirements-dev.txt
```

### 2. Konfigurasi `.env`

```env
DB_USER=xxx
DB_PASS=xxx
DB_HOST=localhost
DB_PORT=5432
DB_NAME=xxx
LOG_LEVEL=INFO
LOG_FORMAT=json          # atau text
LOG_FILE=logs/api.log

RABBITMQ_HOST=xxx
RABBITMQ_USER=xxx
RABBITMQ_PASSWORD=xxx

# WAJIB — aplikasi menolak start tanpa ini
JWT_SECRET=<secret acak panjang>
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

# Origin frontend, dipisah koma. Jangan pakai "*".
CORS_ORIGINS=http://localhost:3000

# Pembatasan percobaan login (0 = mematikan)
LOGIN_MAX_ATTEMPTS=10
LOGIN_WINDOW_SECONDS=300

# Batas transaksi per request sync
MAX_SALES_PER_REQUEST=1000
```

Generate `JWT_SECRET`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### 3. Jalankan migrasi

```bash
python migrate.py            # jalankan semua migrasi yang belum tercatat, urut
python migrate.py --status   # lihat mana yang sudah / belum jalan
```

`migrate.py` menjalankan file berpola `NNN_nama.sql` di `migrations/` secara
urut dan mencatatnya di tabel `schema_migrations`, jadi yang sudah jalan
dilewati. Di Docker, ini dijalankan **otomatis** setiap container start (lihat
bagian [Docker](#docker)).

`orderdetail.sql` dan `ordertransaction.sql` di folder yang sama adalah dump
MySQL lama dan **tidak** ikut dijalankan, begitu juga isi `checks/`.

Semua migrasi aman dijalankan berulang — dan wajib tetap begitu untuk migrasi
baru. Database yang dulu dimigrasi manual lewat `psql` belum punya catatan di
`schema_migrations`, sehingga 001–005 dijalankan ulang sekali saat pertama kali
memakai `migrate.py`. `002` memeriksa **kolom** index yang
ada, bukan namanya — jadi index yang sudah ada dengan nama berbeda terdeteksi
dan dilewati, bukan diduplikasi. (`CREATE INDEX IF NOT EXISTS` hanya
membandingkan nama, dan itu tidak cukup di sini.)

> **Urutan deploy untuk database yang sudah berisi data:** jalankan migrasi 003
> bersamaan dengan deploy kode baru. Di antara keduanya, API key lama tidak akan
> cocok — kode mencari hash sementara database masih menyimpan plaintext.

### 4. Buat kredensial

```bash
# API key untuk mesin POS
python manage_keys.py generate --outlet OUTLET_001

# User admin untuk login dashboard
python manage_users.py create --email admin@maharasa.id --role admin
```

### 5. Jalankan server

```bash
uvicorn app.main:app --reload
```

Dokumentasi interaktif: <http://localhost:8000/docs>

---

## Manage API key outlet

```bash
python manage_keys.py generate --outlet OUTLET_001   # buat key baru
python manage_keys.py list                           # daftar key (prefix saja)
python manage_keys.py rotate --outlet OUTLET_001     # ganti key; yang lama mati
python manage_keys.py revoke --outlet OUTLET_001     # nonaktifkan
```

> CLI dan endpoint `/api/api-keys` memakai service yang sama
> (`app/services/api_key_service.py`), jadi aturannya persis sama di keduanya.

Output `generate`:

```
[+] API key berhasil dibuat untuk outlet 'OUTLET_001'
    Key: xK9mP2vQnR8sL4wT7uY1eA6hJ3bN0cF5dGpIqZmEs
    Simpan key ini — tidak bisa dilihat lagi!
```

`list` hanya menampilkan prefix, karena database memang tidak menyimpan key
mentahnya:

```
Outlet               Status     Created At                Key
------------------------------------------------------------------------------
OUTLET_001           aktif      2026-01-15 08:00:00       xK9mP2vQ...
OUTLET_002           aktif      2026-01-16 09:00:00       pZ3nQ7rY...
OUTLET_003           nonaktif   2026-01-10 07:00:00       bJ8cT1uW...
```

> Key yang hilang tidak bisa dipulihkan — revoke, lalu buat baru.

---

## Manage user dashboard

```bash
python manage_users.py create --email admin@maharasa.id --role admin
python manage_users.py create --email budi@maharasa.id --role manager
python manage_users.py create --email kasir@maharasa.id --role outlet --outlet OUTLET_001

python manage_users.py list
python manage_users.py password --email admin@maharasa.id
python manage_users.py deactivate --email budi@maharasa.id
python manage_users.py activate --email budi@maharasa.id
python manage_users.py delete --email budi@maharasa.id   # minta email diketik ulang; --yes untuk otomatisasi
```

**User seed pertama.** Di database kosong, buat satu admin sementara, login ke
dashboard, buat admin sungguhan dari halaman Users, lalu hapus seed-nya:

```bash
python manage_users.py create --email seed@maharasa.id --role admin --name "Seed (hapus)"
# ...login, buat admin sungguhan, logout...
python manage_users.py delete --email seed@maharasa.id
```

Seed tidak bisa dihapus selama ia admin aktif satu-satunya — buat admin
penggantinya dulu. User baru selalu diminta ganti password saat login pertama.

Password ditanyakan lewat prompt (tidak masuk shell history). Untuk otomatisasi,
pakai `--password`.

| Role | Kewenangan |
|---|---|
| `admin` | Akses penuh semua outlet |
| `manager` | Baca data semua outlet |
| `outlet` | Baca data outletnya sendiri saja (wajib `--outlet`) |

---

## Endpoint

### Auth

#### `POST /api/auth/login`

```json
{ "email": "admin@maharasa.id", "password": "rahasia123" }
```

```json
{
  "access_token": "eyJhbGciOi...",
  "refresh_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "expires_in": 1800,
  "user": {
    "id": 1,
    "email": "admin@maharasa.id",
    "full_name": "Budi",
    "role": "admin",
    "outlet_code": null,
    "is_active": true
  }
}
```

#### `POST /api/auth/refresh`

```json
{ "refresh_token": "eyJhbGciOi..." }
```

Access token baru dibuat dari data user **terkini** — perubahan role langsung berlaku.

#### `GET /api/auth/me`

Data user yang sedang login.

#### `POST /api/auth/logout`

JWT bersifat stateless; token sesungguhnya dibuang di sisi klien. Endpoint ini
hanya penanda supaya frontend punya tempat memanggil.

#### `POST /api/auth/change-password`

Ganti password sendiri — tersedia untuk semua role.

```json
{ "current_password": "lama123456", "new_password": "baru123456" }
```

Password lama tetap diminta walaupun pemanggil sudah membawa token valid:
tanpa itu, token yang dicuri bisa dipakai mengunci pemilik akun yang sah.

> `POST /api/auth/login` dibatasi `LOGIN_MAX_ATTEMPTS` percobaan (default 10)
> per `LOGIN_WINDOW_SECONDS` (default 300 detik) per alamat pemanggil.
> Melewati batas menghasilkan 429 dengan header `Retry-After`.
> Login yang berhasil mengosongkan hitungan.

---

### Administrasi (khusus role admin)

Manager sengaja tidak diberi akses ke sini: manager boleh membaca data semua
outlet, tapi tidak mengelola kredensial.

#### API key outlet

| Endpoint | Isi |
|---|---|
| `GET /api/api-keys` | Daftar key — hanya prefix, tidak pernah key mentah |
| `POST /api/api-keys` | Buat key untuk outlet baru |
| `POST /api/api-keys/{outlet_code}/rotate` | Ganti key; yang lama langsung mati |
| `POST /api/api-keys/{outlet_code}/revoke` | Nonaktifkan key |

`POST /api/api-keys` dan `/rotate` adalah **satu-satunya** response yang memuat
key mentah:

```json
{
  "success": true,
  "data": { "outlet_code": "OUTLET_009", "key_prefix": "xK9mP2vQ", "is_active": true },
  "api_key": "xK9mP2vQnR8sL4wT7uY1eA6hJ3bN0cF5dGpIqZmEs",
  "message": "Simpan key ini sekarang — tidak bisa dilihat lagi."
}
```

Outlet yang sudah punya key ditolak `409`, bukan ditimpa — menimpa berarti mesin
POS di lapangan langsung kehilangan akses tanpa peringatan. Untuk mengganti key
yang bocor, pakai `rotate`. `rotate` juga satu-satunya cara memulihkan outlet
yang key-nya sudah direvoke, karena key lamanya tidak diketahui siapa pun lagi.

#### User dashboard

| Endpoint | Isi |
|---|---|
| `GET /api/users` | Daftar user |
| `POST /api/users` | Buat user |
| `GET /api/users/{id}` | Detail user |
| `PATCH /api/users/{id}` | Ubah nama, role, outlet, status aktif |
| `POST /api/users/{id}/password` | Reset password user lain |

Pagar yang berlaku, supaya admin tidak mengunci dirinya sendiri keluar:

- Tidak bisa menonaktifkan atau menurunkan role akun sendiri → `400`
- Admin aktif terakhir tidak bisa diturunkan atau dinonaktifkan → `400`
- `email` tidak bisa diubah — email adalah subject JWT, mengubahnya membuat
  token yang sedang berjalan menunjuk user yang tidak ada lagi
- Role `outlet` wajib punya `outlet_code` → `422`

#### Product group (Fase 6)

Menentukan group mana yang dipublish oleh `POST /api/sales/publish`.

| Endpoint | Isi |
|---|---|
| `GET /api/product-groups` | Semua mapping, termasuk yang nonaktif |
| `POST /api/product-groups` | Tambah group — `{"product_group": "FOOD", "is_active": true}` |
| `PATCH /api/product-groups/{id}` | Aktifkan / nonaktifkan — `{"is_active": false}` |

- Nama disimpan dalam bentuk normal: spasi di ujung dibuang, huruf besar.
  `colorplate ` tersimpan sebagai `COLORPLATE` dan cocok dengan item POS
  bergroup `Colorplate`, ` COLORPLATE`, dan seterusnya. Data item tidak diubah.
- Duplikat ditolak `409`, termasuk group yang sedang nonaktif — aktifkan lewat `PATCH`.
- **Tidak ada DELETE.** Group dimatikan, barisnya tetap ada sebagai jejak.
  Nama juga tidak bisa diubah: salah ketik → buat baru, nonaktifkan yang lama.
- Migrasi 006 men-seed `COLORPLATE` dalam keadaan aktif, jadi publish setelah
  deploy berperilaku sama persis dengan sebelumnya.

---

### Sync (API key outlet)

#### `POST /api/sync/sales`

```
Authorization: Bearer <API_KEY_OUTLET>
```

> `outlet_code` otomatis dikenali dari API key — tidak perlu dikirim di body.

```json
{
  "sales": [
    {
      "transaction_id": 10001,
      "shop_id": 1,
      "sale_date": "2026-01-15",
      "paid_time": "2026-01-15T10:30:00",
      "receipt_total_amount": 150000.00,
      "receipt_pay_price": 150000.00,
      "vat_percent": 11.00,
      "transaction_vat": 14850.00,
      "items": [
        {
          "order_detail_id": 1,
          "transaction_id": 10001,
          "sale_date": "2026-01-15",
          "product_id": 101,
          "product_group": "COLORPLATE",
          "product_name": "RED",
          "qty": 2,
          "price": 75000.00,
          "retail_price": 75000.00
        }
      ]
    }
  ]
}
```

```json
{ "success": true, "inserted_sales": 1, "inserted_items": 1 }
```

---

### Baca (JWT user)

#### `GET /api/sales/`

Query param: `outlet`, `start_date`, `end_date`, `limit` (1–500, default 50), `offset`.

```json
{
  "success": true,
  "data": [ { "transaction_id": 10001, "outlet_code": "OUTLET_001", "...": "..." } ],
  "pagination": { "limit": 50, "offset": 0, "total": 1284, "has_more": true }
}
```

#### `GET /api/sales/by-group`

Rekap qty terjual per product group, dikelompokkan per group/produk/outlet/tanggal.

Query param: `product_group` (wajib, boleh diulang —
`?product_group=COLORPLATE&product_group=FOOD`), `outlet`, `start_date`, `end_date`.
Nama group tidak peka huruf besar/kecil maupun spasi di ujung.

```json
{
  "success": true,
  "data": [
    {
      "product_group": "FOOD",
      "product_name": "NASI GORENG",
      "outlet_code": "OUTLET_001",
      "sale_date": "2026-01-15",
      "sold": 5.0
    }
  ]
}
```

#### `GET /api/sales/colorplate`

Alias lama untuk `/by-group?product_group=COLORPLATE`, dipertahankan demi
kompatibilitas. Bentuk response-nya tidak berubah (tanpa field `product_group`).

#### `GET /api/sales/product-groups`

Nama group (bentuk normal) yang pernah muncul di data penjualan — untuk dropdown
dan untuk menemukan group baru dari POS. Ter-scope outlet. Berbeda dari
`/api/product-groups` (admin), yang berisi group yang **dipublish**.

#### `GET /api/outlets`

Daftar outlet untuk dropdown filter. Khusus role `admin` dan `manager`.

#### `GET /api/outlets/sync-status`

Kapan tiap outlet terakhir mengirim data — untuk mendeteksi outlet yang berhenti
sync. Ter-scope: user role `outlet` hanya melihat outletnya sendiri.

```json
{
  "success": true,
  "data": [
    {
      "outlet_code": "OUTLET_001",
      "last_sale_date": "2026-01-15",
      "last_synced_at": "2026-01-15T18:03:11",
      "total_transactions": 1284
    }
  ]
}
```

---

### Laporan dashboard (JWT user)

Semua endpoint di bawah ini menerima `outlet`, `start_date`, dan `end_date`,
dan **mengecualikan transaksi yang dibatalkan** (`Deleted=1`).

| Endpoint | Isi |
|---|---|
| `GET /api/sales/summary` | Jumlah transaksi, omzet, diskon, rata-rata per struk |
| `GET /api/sales/daily` | Time series harian untuk grafik |
| `GET /api/sales/by-outlet` | Perbandingan antar outlet (admin & manager saja) |
| `GET /api/sales/top-products` | Ranking produk (`product_group`, `limit` 1–100). Nama group dinormalisasi seperti `/by-group` |
| `GET /api/sales/export` | Unduh CSV seluruh hasil filter |
| `GET /api/sales/{transaction_id}` | Detail satu transaksi beserta itemnya |

`GET /api/sales/summary`:

```json
{
  "success": true,
  "data": {
    "total_transactions": 128,
    "total_amount": 19250000.0,
    "total_discount": 350000.0,
    "average_per_transaction": 150390.63
  }
}
```

> **Catatan konsistensi.** `GET /api/sales/`, `/by-group`, dan `/colorplate` masih IKUT
> menghitung transaksi `Deleted=1`, sedangkan endpoint laporan tidak.
> Perbedaan ini disengaja: mengubah endpoint lama akan mengubah angka yang
> sudah dipublish ke RabbitMQ. Lihat TODO 4.5.

`GET /api/sales/{transaction_id}` mengembalikan 404 untuk transaksi milik outlet
lain — bukan 403 — supaya nomor transaksi outlet lain tidak bisa dipetakan lewat
perbedaan status code.

---

### Publish event (API key outlet)

#### `POST /api/sales/publish`

```json
{ "date": "2026-01-15", "exchange": "posdata_exchange", "routing_key": "posdata.created" }
```

Mempublish satu event per baris rekap, untuk setiap group yang **aktif** di
`/api/product-groups`. Group `COLORPLATE` memakai bentuk lama — tidak berubah
sejak sebelum Fase 6:

```json
{
  "event": "posdata.created",
  "data": { "platecolor": "RED", "outlet": "OUTLET_001", "date": "2026-01-15", "sold": 4 },
  "meta": { "timestamp": "...", "source": "sync-sales-service", "version": "1.0" }
}
```

Group lain memakai bentuk generik, lewat exchange dan routing key yang sama:

```json
{
  "event": "posdata.created",
  "data": { "group": "FOOD", "product": "NASI GORENG", "outlet": "OUTLET_001", "date": "2026-01-15", "sold": 5 },
  "meta": { "timestamp": "...", "source": "sync-sales-service", "version": "1.0" }
}
```

> Consumer yang hanya mengenal `platecolor` harus sudah mengabaikan event tanpa
> field itu **sebelum** admin mengaktifkan group lain.

Tidak ada group aktif → `200` dengan `"message": "No active product groups to publish"`
dan `published: 0`.

> Belum idempoten — memanggil dua kali untuk tanggal yang sama mengirim event
> dobel. Lihat TODO 3.4.

---

### Health

| Endpoint | Untuk | Menyentuh DB |
|---|---|---|
| `GET /` | Cek cepat | Tidak |
| `GET /health` | Liveness probe | Tidak |
| `GET /health/ready` | Readiness probe — 503 kalau DB bermasalah | Ya |

Semuanya terbuka tanpa autentikasi. `/health` sengaja tidak menyentuh database:
kalau probe liveness ikut gagal saat database bermasalah, orchestrator akan
me-restart container yang sebenarnya sehat.

---

## Bentuk error

| Status | Kapan |
|---|---|
| 401 | Kredensial tidak ada, salah, nonaktif, atau token kedaluwarsa |
| 403 | Kredensial sah tapi tidak berhak atas outlet / endpoint tersebut |
| 422 | Body atau query param tidak lolos validasi |
| 500 | Kegagalan database / broker |

---

## Struktur Project

```
sync-api/
├── app/
│   ├── main.py                     # Entry point + CORS + wiring router
│   ├── config.py                   # Konfigurasi env (validasi saat import)
│   ├── database.py                 # SQLAlchemy engine & session
│   ├── core/
│   │   ├── security.py             # Hash API key, hash password, JWT
│   │   ├── rate_limit.py           # Penahan penebakan password
│   │   └── time.py                 # utcnow() naive-UTC
│   ├── dependencies/
│   │   └── auth.py                 # require_api_key, get_current_user, scoping
│   ├── models/
│   │   ├── api_key.py              # api_keys (kolom `key` berisi hash)
│   │   ├── product_group_mapping.py # product_group_mappings (group yang dipublish)
│   │   ├── user.py                 # users + definisi role
│   │   ├── sales.py                # ordertransaction
│   │   └── sales_items.py          # orderdetail
│   ├── routes/
│   │   ├── auth_routes.py          # /api/auth/*
│   │   ├── admin_routes.py         # /api/api-keys, /api/users, /api/product-groups (admin)
│   │   ├── sync_routes.py          # /api/sync/*      (API key)
│   │   ├── sales_routes.py         # /api/sales/*     (JWT + publish API key)
│   │   └── outlet_routes.py        # /api/outlets
│   ├── schemas/
│   │   ├── auth_schema.py
│   │   ├── admin_schema.py
│   │   ├── sales_schema.py         # request sync
│   │   ├── sales_response.py       # response model
│   │   └── sales_event.py
│   ├── services/
│   │   ├── sales_service.py        # upsert + query baca + laporan
│   │   ├── api_key_service.py      # dipakai route DAN CLI
│   │   ├── user_service.py         # dipakai route DAN CLI
│   │   ├── product_group_service.py # mapping group yang dipublish (tanpa hapus)
│   │   └── rabbitmq.py
│   └── utils/
│       └── logger.py
├── migrations/
│   ├── 001_initial_schema.sql
│   ├── 002_unique_indexes.sql      # index pendukung ON CONFLICT
│   ├── 003_hash_api_keys.sql       # hash key di tempat + updated_at
│   ├── 004_users.sql               # tabel users
│   ├── 005_must_change_password.sql
│   └── checks/
│       └── orderdetail_outlet_collision.sql
├── .github/workflows/tests.yml     # CI: lint + unit + integrasi Postgres
├── tests/                          # lihat tests/README.md
├── migrate.py                      # runner migrasi (otomatis saat container start)
├── manage_keys.py                  # CLI API key outlet
├── manage_users.py                 # CLI user dashboard
├── consumer.py                     # contoh consumer RabbitMQ
├── requirements.txt
├── requirements-dev.txt
├── pytest.ini
├── ruff.toml
└── TODO.md                         # rencana pengembangan berikutnya
```

---

## Test

```bash
pytest                                  # unit test
pytest --cov=app --cov-report=term-missing
ruff check app tests                    # lint
TEST_DATABASE_URL=postgresql+psycopg2://... pytest tests/integration -v
```

CI menjalankan ketiganya pada tiap push dan pull request —
lihat `.github/workflows/tests.yml`.

Detail dan konvensinya di [tests/README.md](tests/README.md).

---

## Catatan Penting

- API key disimpan sebagai **hash** di tabel `api_keys`, bukan plaintext
- Setiap outlet punya key unik — kalau satu bocor, hanya outlet itu yang terdampak
- `outlet_code` diambil dari key/identitas, tidak pernah dari body atau query param
- Upsert memakai `on_conflict_do_update` dengan kunci `(TransactionID, outlet_code)`
- Log ada di `LOG_FILE` (default `logs/api.log`), level dikontrol `LOG_LEVEL`.
  Format default **JSON satu baris per log** (`LOG_FORMAT=text` untuk develop).
  Setiap request mendapat `request_id` — dari header `X-Request-ID` kalau dikirim
  dan valid, selain itu dibuat baru — dan dikembalikan di header respons yang sama.
  Cari semua log satu request: `grep '"request_id": "<id>"' logs/api.log`
- Endpoint baru **wajib** punya dependency auth — dijaga oleh
  `tests/unit/test_app_wiring.py::test_semua_endpoint_api_punya_autentikasi`
- Satu request sync dibatasi `MAX_SALES_PER_REQUEST` (default 1000) transaksi
- `init_db.py` tidak lagi menghapus tabel kecuali `INIT_DB_CONFIRM=DROP-ALL`
  diisi — untuk perubahan skema di produksi, pakai `migrations/`

---

## Docker

```bash
cp .env.example .env
# isi .env, termasuk JWT_SECRET dan CORS_ORIGINS

docker compose up -d --build
```

Migrasi jalan **otomatis saat container start**, sebelum gunicorn — bukan saat
build, karena saat build database belum terjangkau. Kalau migrasi gagal,
container berhenti dan penyebabnya ada di `docker compose logs`. Kalau database
belum siap, `migrate.py` mencoba ulang beberapa kali dulu.

Setelah container jalan:

```bash
docker compose exec maharasa-apisales python migrate.py --status
docker compose exec maharasa-apisales python manage_keys.py generate --outlet OUTLET_001
docker compose exec maharasa-apisales python manage_users.py create --email admin@maharasa.id --role admin

docker compose logs -f maharasa-apisales
tail -f logs/api.log

docker compose down
```
