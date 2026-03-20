# Sales Sync API

FastAPI service untuk menerima dan menyimpan data transaksi penjualan dari outlet ke database MySQL.

---

## Stack

- **Python** 3.10+
- **FastAPI**
- **SQLAlchemy** (MySQL dialect)
- **Pydantic v2**
- **MySQL 5.x / 8.x**

---

## Setup

```bash
cp .env.example .env
# Edit .env sesuai konfigurasi

pip install -r requirements.txt
uvicorn app.main:app --reload
```

### `.env` yang dibutuhkan

```env
DATABASE_URL=mysql+pymysql://user:password@host:3306/dbname
API_KEY=your-secret-api-key
LOG_LEVEL=INFO
```

---

## Endpoint

### `POST /api/sync/sales`

Sync data transaksi dari outlet.

**Header:**
```
Authorization: Bearer <API_KEY>
```

**Request Body:**
```json
{
  "outlet": "OUTLET_001",
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

**Response:**
```json
{
  "success": true,
  "inserted_sales": 1,
  "inserted_items": 1
}
```

---

## Struktur Project

```
app/
├── main.py                  # Entry point FastAPI
├── config.py                # Konfigurasi env
├── database.py              # SQLAlchemy engine & session
├── middleware/
│   └── api_key_auth.py      # Bearer token auth
├── models/
│   ├── sales.py             # Model ordertransaction
│   └── sales_items.py       # Model orderdetail
├── routes/
│   └── sync_routes.py       # Route POST /api/sync/sales
├── schemas/
│   ├── sales_schema.py      # Pydantic schema
│   ├── ordertransaction.sql # DDL tabel transaksi
│   └── orderdetail.sql      # DDL tabel detail
├── services/
│   └── sales_service.py     # Business logic upsert
└── utils/
    └── logger.py            # File logger
```

---

## Catatan Penting

- `sales_service.py` menggunakan `on_duplicate_key_update` (MySQL syntax) — **bukan** `on_conflict_do_update` (PostgreSQL)
- `inserted` di response sebelumnya hanya menghitung items; sekarang sudah dipisah menjadi `inserted_sales` dan `inserted_items`
- `LOG_LEVEL` di `.env` sekarang benar-benar dipakai oleh logger