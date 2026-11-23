# Selesaikan dokumen — Sales Consolidate Service

Dibuat: 2026-11-20 · Basis: `api-salespromise@28676ef`, `frontendsales@2c7ae72`

Checklist untuk dikerjakan di VS Code. Kerjakan berurutan; tiap tugas berisi
file, lokasi, dan teks pengganti siap tempel. Bisa juga diberikan ke Claude Code
/ Copilot sebagai instruksi: _"Kerjakan semua tugas di file ini, satu commit per repo."_

Ringkasan:

| # | Repo | File | Jenis |
|---|---|---|---|
| 1 | api-salespromise | `tests/integration/test_closing_export_postgres.py` | Perbaikan test (CI) |
| 2 | api-salespromise | `TODO.md` — status atas, 8.14, 8.15, 8.16 | Dokumen |
| 3 | api-salespromise | `docs/status-pekerjaan-kirim-closing.md` | Surat ke ERP |
| 4 | api-salespromise | `todo_perbaikan.md` — header | Dokumen |
| 5 | frontendsales | `TODO.md` — item 12.9, 13.9 | Dokumen |
| 6 | keduanya | verifikasi + commit | — |

---

## 1. Perbaiki 4 test integrasi yang gagal (api-salespromise)

**Masalah:** `TestKirimDiPostgres` (4 test) gagal `Diblokir` sejak 8.14 —
`siapkan()` memakai `kirim_closing` lama yang tidak memberi warna piring,
sehingga kena blokir `menu_tanpa_warna`. CI kemungkinan merah sejak `7e3028c`.

Pilih salah satu:

- **a.** Terapkan patch: `git apply fix-integrasi-closing-export.patch`
- **b.** Manual — di `tests/integration/test_closing_export_postgres.py` baris ±28, ganti:

  ```python
  from tests.unit.test_routes_closing import HARI_INI, item, jual, kirim_closing, petakan
  ```

  menjadi:

  ```python
  from tests.unit.test_closing_export_service import kirim_closing_siap as kirim_closing
  from tests.unit.test_routes_closing import HARI_INI, item, jual, petakan
  ```

Verifikasi:

```bash
ruff check .
TEST_DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5433/sync_test pytest tests/integration -q
# harapan: 101 passed
```

- [ ] Selesai

---

## 2. Perbarui `TODO.md` (api-salespromise)

### 2a. Blok "Sisa" di bagian atas file

Cari baris:

```markdown
  Sisa: deploy (migrasi 016, 018, 019 belum dijalankan) dan jawaban pemilik API.
```

Ganti menjadi:

```markdown
  Sisa: deploy (migrasi 016–022 belum dijalankan di produksi) dan jawaban
  ERP Gateway (8.16). 8.15 `payments` selesai di kode 2026-11-18.
```

- [ ] Selesai

### 2b. Item 8.14 — catatan migrasi 020

Cari:

```markdown
      `tests/integration/test_migrasi_020_postgres.py` (**belum dijalankan**,
      `TEST_DATABASE_URL` tidak diset). Migrasi 020 belum dijalankan ke
      database mana pun. Surat ke ERP:
```

Ganti menjadi:

```markdown
      `tests/integration/test_migrasi_020_postgres.py` (lulus 2026-11-20 di
      `sync_test`, bersama seluruh suite integrasi 101/101). Migrasi 020 belum
      dijalankan di produksi. Surat ke ERP:
```

- [ ] Selesai

### 2c. Item 8.15 — centang dan isi rinciannya

Ganti seluruh item `- [ ] **8.15 `payments`** — menunggu agen POS ...` (4 baris) dengan:

```markdown
- [x] **8.15 `payments`** (2026-11-18, `54941e6`; laporan 2026-11-19, `dae80b5`) —
      agen POS mengirim key `payments` per transaksi
      ([docs/handoff-sync-api-payments.md](docs/handoff-sync-api-payments.md)).
      - Migrasi **021** `021_orderpaydetail.sql` (CREATE TABLE + ADD COLUMN saja):
        tabel `orderpaydetail`, kunci `(outlet_code, TransactionID, ComputerID,
        PayDetailID)`; kolom `ordertransaction.payments_received_at`
        (NULL = pembayaran belum diketahui).
      - Sync: key `payments` ada → baris pembayaran transaksi itu diganti utuh;
        key tidak ada → tidak disentuh. Selisih terhadap `ReceiptPayPrice`
        hanya dicatat di log (`SYNC PAYMENTS MISMATCH`), data tetap disimpan.
        Respons ke agen tidak berubah.
      - Rekap closing: `payments` per `visitPurposeName` + `PayTypeID` outlet;
        `paymentAmount` = `fullPaymentAmount` sampai ERP menjawab artinya;
        jenis bayar bertotal 0 tidak dikirim; `paymentTotal` = Σ pembayaran.
        `coaNo` / MDR tidak dikirim.
      - Blokir baru: `transaksi_tanpa_pembayaran`, `pembayaran_tidak_sama`
        (toleransi `TOLERANSI_PEMBAYARAN` 0,5, menunggu jawaban ERP soal
        pembulatan).
      - Laporan: `GET /api/sales/payments` (ringkasan per jenis bayar,
        ikut cache 9.12) dan `payments` di `GET /api/sales/{transaction_id}`.
      - Jenis sistem POS (Promise/Vtec) tidak disimpan — `outlet_code` dari
        API key dianggap cukup, karena satu outlet = satu sistem POS.
        **Pastikan asumsi ini benar** (handoff bagian 1: jenis bayar tidak
        boleh digabung antar sistem POS).
      Penjaga: `test_closing_export_pembayaran.py`, `test_routes_sales_payments.py`,
      `test_sales_service_sync.py`, `test_schemas.py`,
      `tests/integration/test_migrasi_021_postgres.py`. Frontend: sync-frontend
      12.9 & 13.9. Migrasi 021 belum dijalankan di produksi.
```

- [ ] Selesai

### 2d. Item 8.16 — tambahkan butir payments

Di akhir item 8.16 (`... endpoint + token uji.`) tambahkan:

```markdown
      Khusus `payments`: persetujuan `coaNo`/MDR diatur di ERP per
      `paymentMethod`, arti `paymentAmount` vs `fullPaymentAmount`, dan
      apakah selisih pembulatan kasir dikirim sebagai `roundingTotal`
      (penentu nilai `TOLERANSI_PEMBAYARAN`).
```

- [ ] Selesai

---

## 3. Perbarui surat ke ERP — `docs/status-pekerjaan-kirim-closing.md`

### 3a. Header

Ganti `Tanggal: 17 November 2026` → `Tanggal: 20 November 2026`, dan judul
`(revisi 3)` boleh tetap. Tambah satu kalimat di paragraf pembuka:

```markdown
Pembaruan 20 November: data pembayaran dari POS sudah tersedia, sehingga
`payments` kini terisi (lihat bagian 1).
```

- [ ] Selesai

### 3b. Bagian 1 "Yang sudah selesai" — tambahkan butir

```markdown
- **`payments`**: diisi dari data pembayaran POS, dijumlah per
  `visitPurposeName` + jenis bayar. Isinya `paymentMethod` (nama jenis bayar
  di POS), `paymentAmount`, `fullPaymentAmount` (sementara bernilai sama),
  dan `notes` (kosong). `paymentTotal` = jumlah `payments`. Rekap yang
  pembayarannya belum lengkap, atau totalnya tidak sama dengan `grandTotal`,
  kami tahan di sisi kami dan tidak dikirim.
```

- [ ] Selesai

### 3c. Bagian 2 tabel — baris nomor 3 (`payments`)

Hapus baris 3 dari tabel (sudah selesai), lalu nomori ulang baris 4–5 menjadi 3–4.
Perbarui juga rujukan "Butir 1, 2, dan 4" di bagian 3 bila nomornya ikut bergeser
(bagian 3 punya penomoran sendiri, jadi cukup dicek).

- [ ] Selesai

### 3d. Bagian 3 — paragraf penutup

Ganti:

```markdown
Butir 6–8 kami perlukan sebelum `payments` mulai diisi. Mohon dijawab lebih
dulu kalau memungkinkan.
```

menjadi:

```markdown
`payments` sudah kami isi dengan asumsi sementara: `paymentAmount` =
`fullPaymentAmount`, dan selisih sampai Rp0,50 terhadap `grandTotal` masih
kami terima. Jawaban butir 6–8 menentukan apakah asumsi itu perlu diubah;
kalau berubah, tanggal yang terdampak kami kirim ulang dengan `sequence` baru.
```

- [ ] Selesai

---

## 4. Header `todo_perbaikan.md` (api-salespromise)

Di tabel paling atas, baris `Status`, ganti:

```markdown
| Status | Backend langkah 1–9 dan frontend selesai di kode (belum commit, belum deploy). Aturan A/B/C disetujui. Kontrak revisi 2 belum dikirim ke pemilik API. |
```

menjadi:

```markdown
| Status | Backend langkah 1–9 dan frontend selesai dan sudah di-commit (`ab6a5d7` / `2f8001d`), belum deploy. Aturan A/B/C disetujui. Kontrak sudah berlanjut ke revisi 3 (TODO 8.13–8.15). |
```

> Cek hash commit dengan `git log --oneline -- todo_perbaikan.md` sebelum menempel.

- [ ] Selesai

---

## 5. Tambah item di `TODO.md` (frontendsales)

### 5a. Fase 12 — setelah item 12.8

```markdown
- [x] **12.9 Alasan blokir pembayaran** (backend 8.15, 2026-11-18, `4a8c8fc`) —
      tipe digenerate ulang dari OpenAPI backend (`transaksi_tanpa_pembayaran`,
      `pembayaran_tidak_sama`, `ClosingExportPaymentMismatch`; ikut memuat
      `/api/products/export` dan filter `same_code`). Tab _Kirim ke API_
      menampilkan jumlah transaksi tanpa data pembayaran dan daftar tujuan
      kunjungan yang Σ pembayarannya ≠ grand total. Test:
      `closing-export-panel.test.tsx`, `closing-view.test.tsx`, `a11y.test.tsx`.
```

- [ ] Selesai

### 5b. Fase 13 — setelah item 13.8

```markdown
- [x] **13.9** (2026-11-19, `3009ede`) Pembayaran di dashboard & transaksi —
      pasangan backend 8.15 / `GET /api/sales/payments`.
      `PaymentSummary` di dashboard (per jenis bayar, total, jumlah transaksi
      tanpa data pembayaran), hook `usePaymentSummary` di `use-sales.ts`;
      `SaleDetailDialog` menampilkan baris pembayaran transaksi
      (`payments: null` = belum diketahui, dibedakan dari daftar kosong).
      Test: `payment-summary.test.tsx`, `transaksi-view.test.tsx`.
```

> Sesuaikan nama komponen/hook bila berbeda — cek `git show --stat 3009ede`.

- [ ] Selesai

---

## 6. Verifikasi & commit

**api-salespromise**

```bash
ruff check .
pytest -q                      # harapan: 1544 passed
TEST_DATABASE_URL=... pytest tests/integration -q   # harapan: 101 passed
git add -A
git commit -m "fix(test): integrasi closing export pakai menu berwarna; docs: payments 8.15"
```

**frontendsales**

```bash
npm run lint && npx next typegen && npm run typecheck && npm test
git add TODO.md
git commit -m "docs: catat item 12.9 dan 13.9 (payments)"
```

- [ ] CI GitHub kedua repo hijau
- [ ] Surat `status-pekerjaan-kirim-closing.md` siap dikirim ke ERP Gateway

---

## Catatan deploy (tidak diubah di tugas ini, hanya pengingat)

- Migrasi 016–022 belum jalan di produksi; 017 & 022 `CONCURRENTLY` → jalankan saat sepi.
- 9.14 breaking change `sync-status` → deploy backend + frontend **bersamaan**.
- Jalankan dulu (read-only): `migrations/checks/orderdetail_outlet_collision.sql` (query 0 & 4)
  dan `migrations/checks/saledate_konsisten.sql`.
- Keputusan terbuka: `Deleted` tidak ter-update saat konflik upsert.