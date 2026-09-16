# Test Suite — Sync API

## Menjalankan

```bash
pip install -r requirements.txt -r requirements-dev.txt

pytest                      # semua test unit (integrasi otomatis dilewati)
pytest -v                   # dengan nama tiap test
pytest --cov=app --cov=manage_keys --cov-report=term-missing
pytest tests/unit/test_sales_service_sync.py::TestKlausaUpsertSales
```

### Test integrasi (PostgreSQL sungguhan)

```bash
TEST_DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/sync_test pytest tests/integration -v
```

Tanpa `TEST_DATABASE_URL`, seluruh test integrasi dilewati — jadi `pytest`
polos tetap hijau di mesin mana pun.

> Jangan arahkan ke database produksi. Fixture-nya menjalankan `drop_all()`
> dan `TRUNCATE`.

## Struktur

| File | Cakupan |
|---|---|
| `conftest.py` | Env test, SQLite in-memory, factory data, client + identitas |
| `unit/test_config.py` | `DATABASE_URL`, URL-encoding password, `validate()`, CORS_ORIGINS |
| `unit/test_database.py` | Dependency `get_db`, konfigurasi pool |
| `unit/test_security.py` | Hash API key, hash password, JWT |
| `unit/test_schemas.py` | Kontrak payload Pydantic |
| `unit/test_auth_dependencies.py` | Dua jalur auth + outlet scoping + RBAC |
| `unit/test_routes_auth.py` | `login`, `refresh`, `me`, `logout` |
| `unit/test_app_wiring.py` | CORS, endpoint publik, penjaga auth, OpenAPI |
| `unit/test_sales_service_sync.py` | `sync_sales` — pemetaan kolom & klausa upsert |
| `unit/test_sales_service_queries.py` | `get_sales`, `count_sales`, rekap per product group, `get_sales_colorplate`, pagination |
| `unit/test_product_group_service.py` | Mapping product group — normalisasi nama, tanpa penghapusan |
| `unit/test_routes_product_groups.py` | `/api/product-groups` (admin), `/api/sales/by-group`, `/api/sales/product-groups` |
| `unit/test_routes_sync.py` | `POST /api/sync/sales` |
| `unit/test_routes_sales.py` | `GET /api/sales`, `/colorplate`, `POST /publish` |
| `unit/test_rabbitmq.py` | `RabbitMQClient` (pika di-mock) |
| `unit/test_manage_keys.py` | CLI API key outlet |
| `unit/test_manage_users.py` | CLI user dashboard |
| `unit/test_routes_api_keys.py` | `/api/api-keys` — buat, rotate, revoke |
| `unit/test_routes_users.py` | `/api/users` + ganti password sendiri |
| `unit/test_routes_reports.py` | Endpoint laporan dashboard |
| `unit/test_sales_service_reports.py` | Query agregat laporan |
| `unit/test_rate_limit.py` | Penahan penebakan password |
| `unit/test_structured_logging.py` | Log JSON/teks, `request_id`, middleware `X-Request-ID`, access log |
| `unit/test_infrastructure.py` | utcnow, koneksi broker, batas payload, health |
| `integration/test_sync_postgres.py` | Upsert sungguhan, transaksi, performa |

## Kenapa SQLite untuk sebagian, mock untuk sebagian

`sync_sales` memakai `on_conflict_do_update` — konstruksi khusus PostgreSQL
yang tidak dikenal SQLite. Karena itu pengujiannya dibagi tiga lapis:

1. **Statement-level** (`test_sales_service_sync.py`) — session di-mock, statement
   yang dikirim ke `db.execute()` di-compile ke dialek PostgreSQL lalu diperiksa
   nilai bind dan klausa `ON CONFLICT`-nya. Cepat, tidak butuh database.
2. **SQLite in-memory** (`test_sales_service_queries.py`) — untuk query baca yang
   hanya memakai SQL standar. Assertion-nya pada data sungguhan, bukan mock.
3. **PostgreSQL sungguhan** (`integration/`) — satu-satunya tempat upsert benar-benar
   dieksekusi.

## Dua fixture identitas

Setelah auth dipisah (item 1.2), test route memilih salah satu:

```python
def test_sesuatu(client, api_key_headers):   # mesin POS  → /api/sync/*, /api/sales/publish
def test_sesuatu(client, admin_headers):     # dashboard  → endpoint baca
```

Untuk role selain admin, rakit sendiri:

```python
user = make_user(email="kasir@maharasa.id", role="outlet", outlet_code="OUTLET_001")
client.get("/api/sales/", headers=bearer(token_for(user)))
```

`client` memakai `app_db` — SQLite in-memory dengan StaticPool — sehingga baris
yang di-seed test benar-benar terlihat oleh request yang dilayani aplikasi.

## Penjaga auth

`unit/test_app_wiring.py::test_semua_endpoint_api_punya_autentikasi` menelusuri
seluruh route `/api` dan menuntut setiap route punya `require_api_key`,
`get_current_user`, atau `require_roles`. Endpoint baru yang lupa diberi auth
akan langsung membuat test ini gagal.

Kalau memang sengaja publik, daftarkan di `PUBLIC_PATHS` pada file itu —
keputusannya jadi eksplisit dan terlihat saat review.

## Test yang sengaja ditandai `xfail`

Tinggal satu, dan itu bukan bug melainkan keputusan yang belum diambil:

```
XFAIL test_transaksi_terhapus_tidak_ikut_dihitung   → TODO 4.5
```

Marker-nya `strict=True`: begitu perilakunya diputuskan dan dikerjakan, test
berubah jadi XPASS dan **gagal** — sinyal untuk menghapus markernya.

## Alur TDD untuk fitur baru

1. Tulis test yang gagal lebih dulu, di file sesuai lapisannya.
2. Jalankan `pytest` — pastikan gagal karena alasan yang benar.
3. Tulis kode secukupnya sampai hijau.
4. Rapikan, jalankan `pytest` sekali lagi.

Konvensi yang dipakai di sini:

- Nama test memakai bahasa Indonesia dan menjelaskan perilaku, bukan nama
  fungsinya — `test_outlet_diambil_dari_api_key_bukan_body`, bukan `test_sync_1`.
- Satu perilaku satu test.
- Docstring dipakai untuk menjelaskan *kenapa* perilaku itu penting, terutama
  untuk hal yang tidak terlihat jelas dari kodenya.
- Data uji dibuat lewat factory di `conftest.py` / `build_sale()` dan
  `build_item()`, bukan dict panjang yang disalin berulang.
