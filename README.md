# Sales Sync API

FastAPI service untuk menerima dan menyimpan data transaksi penjualan dari outlet ke database PostgreSQL.

---

## Stack

- **Python** 3.10+
- **FastAPI**
- **SQLAlchemy** (PostgreSQL dialect)
- **Pydantic v2**
- **PostgreSQL 14+**

---

## Setup

### 1. Clone & install dependency

```bash
cp .env.example .env
# Edit .env sesuai konfigurasi

pip install -r requirements.txt
```

### 2. Konfigurasi `.env`

```env
DATABASE_URL=postgresql+psycopg2://user:password@host:5432/dbname
LOG_LEVEL=INFO
```

> `API_KEY` tidak lagi disimpan di `.env` — key dikelola per outlet langsung di database.

### 3. Jalankan migrasi database

```bash
psql -U postgres -d nama_database -f migrations/001_initial_schema.sql
```

### 4. Generate API key untuk setiap outlet

```bash
python manage_keys.py generate --outlet OUTLET_001
```

Output:
```
[+] API key berhasil dibuat untuk outlet 'OUTLET_001'
    Key: xK9mP2vQnR8sL4wT7uY1eA6hJ3bN0cF5dGpIqZmEs
    Simpan key ini — tidak bisa dilihat lagi!
```

> Simpan key ini baik-baik dan berikan ke outlet yang bersangkutan.

### 5. Jalankan server

```bash
uvicorn app.main:app --reload
```

---

## Manage API Key

API key dikelola via script `manage_keys.py` dari terminal.

### Generate key untuk outlet baru

```bash
python manage_keys.py generate --outlet OUTLET_001
```

### Lihat semua key yang terdaftar

```bash
python manage_keys.py list
```

Output:
```
Outlet               Status     Created At                Key
------------------------------------------------------------------------------------------
OUTLET_001           aktif      2024-01-15 08:00:00       xK9mP2vQnR8sL4wT...
OUTLET_002           aktif      2024-01-16 09:00:00       pZ3nQ7rYkM2vX5wA...
OUTLET_003           nonaktif   2024-01-10 07:00:00       bJ8cT1uWsN6eL9hD...
```

### Nonaktifkan key outlet

```bash
python manage_keys.py revoke --outlet OUTLET_001
```

> Key yang direvoke tidak bisa digunakan lagi. Untuk mengaktifkan kembali, generate key baru.

---

## Endpoint

### `POST /api/sync/sales`

Sync data transaksi dari outlet.

**Header:**
```
Authorization: Bearer <API_KEY_OUTLET>
```

> `outlet_code` otomatis dikenali dari API key — tidak perlu dikirim di body.

**Request Body:**
```json
{
  "sales": [
    {
      "id": 10001,
      "shop_id": 1,
      "sale_date": "2024-01-15",
      "paid_time": "2024-01-15T10:30:00",
      "receipt_total_amount": 150000.00,
      "receipt_pay_price": 150000.00,
      "vat_percent": 11.00,
      "transaction_vat": 14850.00,
      "items": [
        {
          "id": 1,
          "product_id": 101,
          "qty": 2,
          "price": 75000.00,
          "retail_price": 75000.00,
          "subtotal": 150000.00
        }
      ]
    }
  ]
}
```

**Response sukses:**
```json
{
  "success": true,
  "inserted_sales": 1,
  "inserted_items": 1
}
```

**Response error auth:**
```json
{
  "detail": "Invalid or inactive API key"
}
```

**Response error server:**
```json
{
  "detail": {
    "success": false,
    "message": "Database error"
  }
}
```

---

## Struktur Project

```
sync-api/
├── app/
│   ├── main.py                  # Entry point FastAPI
│   ├── config.py                # Konfigurasi env
│   ├── database.py              # SQLAlchemy engine & session
│   ├── middleware/
│   │   └── api_key_auth.py      # Validasi Bearer token dari DB
│   ├── models/
│   │   ├── api_key.py           # Model tabel api_keys
│   │   ├── sales.py             # Model tabel ordertransaction
│   │   └── sales_items.py       # Model tabel orderdetail
│   ├── routes/
│   │   └── sync_routes.py       # Route POST /api/sync/sales
│   ├── schemas/
│   │   ├── sales_schema.py      # Pydantic request schema
│   │   ├── ordertransaction.sql # DDL referensi tabel transaksi
│   │   └── orderdetail.sql      # DDL referensi tabel detail
│   ├── services/
│   │   └── sales_service.py     # Business logic upsert
│   └── utils/
│       └── logger.py            # File logger
├── migrations/
│   └── 001_initial_schema.sql   # DDL PostgreSQL (ordertransaction, orderdetail, api_keys)
├── manage_keys.py               # CLI manage API key per outlet
├── requirements.txt
├── .env
└── .gitignore
```

---

## Catatan Penting

- API key disimpan di tabel `api_keys` dalam database, bukan di `.env`
- Setiap outlet memiliki key unik — jika satu key bocor, hanya outlet tersebut yang terdampak
- `outlet_code` diambil otomatis dari key saat request masuk, tidak perlu dikirim ulang di body
- Service menggunakan `on_conflict_do_update` (PostgreSQL upsert)
- Log disimpan di folder `logs/api.log`, level dikontrol via `LOG_LEVEL` di `.env`

---

## Docker

### Persiapan

```bash
cp .env.example .env
# Edit .env sesuai konfigurasi database kamu
```

Isi `.env`:
```env
DATABASE_URL=postgresql+psycopg2://user:password@host:5432/dbname
LOG_LEVEL=INFO
```

> Pastikan migrasi sudah dijalankan terlebih dahulu ke PostgreSQL kamu:
> ```bash
> psql -U postgres -d nama_database -f migrations/001_initial_schema.sql
> ```

### Jalankan

```bash
docker compose up -d
```

Docker akan otomatis:
1. Build image FastAPI
2. Menjalankan API di port `8000`

### Generate API key setelah container jalan

```bash
docker compose exec api python manage_keys.py generate --outlet OUTLET_001
```

### Lihat semua key

```bash
docker compose exec api python manage_keys.py list
```

### Nonaktifkan key

```bash
docker compose exec api python manage_keys.py revoke --outlet OUTLET_001
```

### Lihat log

```bash
# Log container
docker compose logs -f api

# Log file
tail -f logs/api.log
```

### Stop

```bash
docker compose down

# Stop + hapus data database
docker compose down -v
```