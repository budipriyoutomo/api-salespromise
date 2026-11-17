# Perubahan agen POS untuk `payments`

Untuk: pengembang agen POS (`POSClosing/v3/internal_tool`) dan sync-api
Tanggal: 17 November 2026

Kontrak kirim rekap closing revisi 3 meminta `payments` di setiap elemen
`sales`. Sekarang kita mengirim `payments: []`, karena data pembayaran tidak
pernah ditarik dari POS. Dokumen ini menjelaskan apa yang harus berubah supaya
data itu tersedia.

---

## 1. Yang dikirim ke ERP

Satu baris per metode bayar, di dalam elemen `sales` (satu tujuan kunjungan):

```json
{
  "paymentMethod": "Cash",
  "paymentAmount": 224250,
  "fullPaymentAmount": 224250,
  "notes": ""
}
```

`coaNo` dan `merchantDiscountRate` **tidak kami kirim**. Keduanya diatur di
ERP Gateway berdasarkan `paymentMethod`. Dari POS hanya dikirim detail
transaksi, termasuk pembayarannya.

Pembagian tugasnya begini:

| Data | Sumber | Dikerjakan di |
|---|---|---|
| Baris pembayaran per transaksi (jenis bayar + nominal) | MySQL POS, tabel `orderpaydetail` | **Agen POS** (dokumen ini) |
| Nama jenis bayar (`paymentMethod`) | Master jenis bayar di POS | **Agen POS** |
| Penjumlahan per tujuan kunjungan + metode | Data yang sudah tersimpan | **sync-api** |
| Akun (COA) dan MDR per metode | Pengaturan di ERP | **ERP Gateway** |

Agen hanya mengirim data mentah pembayaran.

---

## 2. Langkah 0: pastikan struktur tabel di POS

Nama kolom `orderpaydetail` belum pernah dipakai oleh kode yang ada. Query lama
di `POSClosing/vtecQuery.sql` hanya memakai `TransactionID`, `ComputerID`,
`TranKey`, dan `PayTypeID`. Sebelum menulis kode, jalankan ini di MySQL POS
**satu outlet ST dan satu outlet TS** (semuanya hanya membaca):

```sql
SHOW COLUMNS FROM orderpaydetail;
SHOW TABLES LIKE '%pay%';                 -- cari tabel master jenis bayar
SHOW CREATE VIEW vw_ordertransaction;     -- lihat filter yang dipakai view header

-- Contoh isi satu hari
SELECT * FROM orderpaydetail WHERE TransactionID IN (
  SELECT TransactionID FROM vw_ordertransaction WHERE SaleDate = '2026-11-10'
) LIMIT 20;
```

Dari hasil itu, tetapkan:

1. **Kolom nominal.** Pastikan kolom mana yang berisi nominal yang benar-benar
   dibayarkan, tanpa uang kembalian. Untuk pembayaran tunai, nominal yang
   diserahkan tamu biasanya lebih besar dari tagihan.
2. **Kunci baris.** Tentukan ID baris pembayaran yang unik dalam satu
   transaksi. Ini dibutuhkan untuk upsert di sync-api.
3. **Tabel master jenis bayar** dan kolom namanya.
4. **`ComputerID`.** Query lama selalu join dengan `ComputerID` juga. Kalau
   `vw_ordertransaction` hanya mengambil satu `ComputerID`, pembayaran harus
   difilter dengan cara yang sama.
5. **Kecocokan nominal.** Per transaksi, Σ nominal bayar harus = `ReceiptPayPrice`.
   Di outlet TS ini sekaligus menjawab berapa yang benar-benar dibayar tamu. Ini
   bisa membuktikan rumus `grandTotal` = subtotal − diskon + SC + PPN.

---

## 3. Perubahan di agen POS

Semua perubahan mengikuti aturan `AGENTS.md` agen. Query parameterized,
hasilnya list of dict, dan agen tetap hanya membaca MySQL.

### 3.1 Query baru: `core/database.py`

Tambahkan `TransactionData.get_sales_payment(transaction_ids, date_str)`.
Bentuknya sama dengan `get_sales_detail`: placeholder `IN (...)` dihitung dari
`len()`, nilainya lewat params.

Ada dua pilihan sumber data:

- **View baru `vw_orderpaydetail`** (disarankan). Polanya sama dengan
  `vw_ordertransaction` dan `vw_orderdetail`, dan filter `ComputerID` cukup
  ditulis sekali di view. Kekurangannya, view ini harus dibuat di MySQL POS
  setiap outlet, oleh orang yang dulu membuat view `vw_*`.
- **Langsung ke tabel**: `orderpaydetail` join master jenis bayar. Tidak perlu
  mengubah apa pun di POS, tetapi filter `ComputerID` harus ditulis di query agen.

### 3.2 Ambil pembayaran: `controllers/dashboard_controller.py` → `send_to_api()`

Setelah `get_sales_detail(...)`, panggil `get_sales_payment(...)` dengan
`transaction_ids` dan tanggal yang sama, lalu teruskan hasilnya ke
`build_payload(headers, details, payments)`.

### 3.3 Susun payload: `build_payload()`

- Buat `payment_map[trx_id]` dengan cara yang sama seperti `detail_map`.
- Tambahkan ke setiap elemen `sales`:

  ```python
  "payments": payment_map.get(trx_id, []),
  ```

  dengan isi tiap baris, misalnya:

  ```python
  {
      "pay_detail_id": _to_int(p.get("<kolom ID>")),
      "pay_type_id": _to_int(p.get("PayTypeID")),
      "pay_type_name": _text(p.get("<kolom nama jenis bayar>")),
      "amount": _to_float(p.get("<kolom nominal>")),
      # kolom lain yang ditemukan di langkah 0, mis. kembalian atau nomor kartu
      # (jangan kirim nomor kartu lengkap)
  }
  ```

- Tambahkan `PAYMENT_FIELDS` dan panggil
  `warn_missing_columns(payments, PAYMENT_FIELDS, "payment")`, seperti header
  dan detail.

### 3.4 Diagnostik

- Di `warn_incomplete_sales()`: beri peringatan untuk transaksi lunas yang
  tidak punya pembayaran, dan untuk transaksi yang Σ `amount` ≠
  `receipt_pay_price`.
- Di `APIClient._summarize()`: tambahkan jumlah baris pembayaran dan jumlah
  transaksi tanpa pembayaran.

### 3.5 Dokumentasi dan rilis

- Perbarui `docs/database.md` (objek dan kolom baru) dan
  `docs/api-integration.md` (field `payments`) di agen.
- Build ulang `main.exe` dan `worker.exe`, lalu pasang di setiap outlet.

---

## 4. Urutan rilis

1. **Agen boleh dirilis lebih dulu.** Skema Pydantic di sync-api mengabaikan
   field yang tidak dikenal, jadi `payments` dari agen baru tidak menimbulkan
   error, hanya belum disimpan. Agen lama tetap jalan karena tidak mengirim
   field itu.
2. **Data lama tidak ikut terkirim otomatis.** Agen hanya mengirim tanggal
   yang dipilih saat closing. Supaya tanggal yang sudah lewat punya
   pembayaran, closing tanggal itu harus diulang di outlet setelah agen baru
   terpasang. Pengiriman ulang aman karena sync-api memakai upsert.
3. **sync-api harus bisa membedakan "belum ada data" dari "tidak ada
   pembayaran".** Transaksi dari agen lama tidak membawa `payments`, jadi
   simpan `payments` yang tidak dikirim sebagai *tidak diketahui*. Jangan
   dianggap kosong.

---

## 5. Perubahan di sync-api (setelah agen siap)

Ringkasan saja, karena perlu dirancang tersendiri:

- **Skema**: `SalesSchema.payments: Optional[list[SalesPaymentSchema]] = None`.
- **Tabel baru** untuk baris pembayaran, dengan kunci
  `(TransactionID, outlet_code, pay_detail_id)`. Ini butuh **migrasi**, jadi
  perlu persetujuan sebelum dibuat.
- **Upsert per transaksi.** Baris pembayaran bisa berubah, misalnya saat
  metode bayar diganti sebelum closing. Caranya perlu diputuskan: menghapus
  baris lama transaksi itu sebelum insert, atau menandainya tidak aktif.
- **Kirim closing**:
  - `payments` dijumlahkan per tujuan kunjungan + metode;
  - `paymentMethod` diisi nama jenis bayar dari POS apa adanya, karena ERP
    Gateway yang memetakannya ke akun;
  - rekap **diblokir** kalau Σ `payments` ≠ `grandTotal` per tujuan
    kunjungan.

---

## 6. Pertanyaan yang masih terbuka

| # | Pertanyaan | Ditanyakan ke |
|---|---|---|
| 1 | Kolom nominal dan kunci baris di `orderpaydetail` | Cek langsung di POS (langkah 0) |
| 2 | Apakah nama jenis bayar sama di semua outlet? Nama itu yang dipetakan ERP Gateway ke akun, jadi beda ejaan antar outlet harus mereka ketahui. | Cek langsung di POS |
| 3 | Apa beda `paymentAmount` dan `fullPaymentAmount`? (mis. termasuk kembalian atau tidak) | ERP Gateway |
| 4 | Kalau Σ pembayaran ≠ `grandTotal` (mis. pembulatan di kasir), dikirim sebagai `roundingTotal` atau rekap diblokir? | ERP Gateway |
