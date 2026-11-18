# Serah terima: data `payments` dari agen POS ke sync-api

Untuk: tim sync-api
Dari: tim agen POS (`pos-internal-tool`, branch `feature/sales-payments`)
Tanggal: 18 November 2026

Agen POS sekarang bisa mengirim **baris pembayaran mentah per transaksi**
di setiap elemen `sales`. Field ini dibutuhkan kontrak kirim rekap closing
ke ERP (revisi 3), yang meminta `payments` per tujuan kunjungan.

Agen hanya mengirim data mentah. Penyimpanan, penjumlahan, dan validasi
dilakukan di **sync-api**. Pemetaan COA dan MDR dilakukan di
**ERP Gateway**.

| Pekerjaan | Siapa |
|---|---|
| Ambil baris pembayaran dari MySQL POS (view `vw_orderpaydetail`) dan kirim di payload | Agen POS (**selesai**) |
| Terima, simpan, upsert baris pembayaran | **sync-api** |
| Jumlahkan per tujuan kunjungan + metode, di dalam satu sistem POS | **sync-api** |
| Validasi Σ pembayaran terhadap total transaksi | **sync-api** |
| Pemetaan jenis bayar ke COA dan MDR, per sistem POS | ERP Gateway |

---

## 1. Aturan utama: jenis bayar tidak pernah digabung antar sistem POS

Agen dipakai di dua software POS yang berbeda: **Promise** dan **Vtec**.
Jenis bayarnya dipisah per sistem POS, **walaupun namanya sama**.
Contohnya "QRIS BNI" adalah `pay_type_id` 864 di Promise dan 10152 di Vtec.
"Cash" Promise dan "Cash" Vtec juga dua jenis bayar yang berbeda.

Konsekuensinya untuk sync-api:

- Kunci jenis bayar selalu **(sistem POS, `pay_type_id`)**, tidak pernah
  nama saja.
- Penjumlahan per metode bayar dilakukan **di dalam satu sistem POS**.
- **Sistem POS dan outlet diambil dari `API_KEY`**, yang sudah diolah
  sync-api sekarang. Payload **tidak** membawa field sistem POS atau outlet,
  dan memang tidak perlu. Jangan menebak sistem POS dari nama jenis bayar.

---

## 2. Payload

Endpoint dan header tidak berubah: `POST {BASE_URL}/sync/sales` dengan
`Authorization: Bearer {API_KEY}`. Hanya ada satu key baru, `payments`,
di setiap elemen `sales`, sejajar dengan `items`.

```json
{
  "sales": [
    {
      "transaction_id": 120354,
      "invoice_number": "793120354",
      "sale_date": "2026-11-17",
      "transaction_status_id": 2,
      "deleted": 0,
      "receipt_id": 170067,
      "receipt_pay_price": 924715.0,
      "...": "field header lain tidak berubah",
      "items": [ "... tidak berubah ..." ],
      "payments": [
        {
          "pay_detail_id": 1,
          "computer_id": 793,
          "pay_type_id": 149,
          "pay_type_code": "149",
          "pay_type_name": "REEDEM POINT",
          "pay_type_display_name": "REEDEM POINT",
          "amount": 26030.0,
          "cash_change": 0.0,
          "is_from_edc": 0,
          "is_sale": 1,
          "is_other_receipt": 0
        },
        {
          "pay_detail_id": 2,
          "computer_id": 793,
          "pay_type_id": 1,
          "pay_type_code": "1",
          "pay_type_name": "Cash",
          "pay_type_display_name": "Cash",
          "amount": 898685.0,
          "cash_change": 0.0,
          "is_from_edc": 0,
          "is_sale": 1,
          "is_other_receipt": 0
        }
      ]
    }
  ]
}
```

Contoh di atas adalah data asli Promise (17 November 2026): satu
transaksi dibayar dengan dua metode, 26.030 + 898.685 = 924.715 =
`receipt_pay_price`.

### 2.1 Arti field

| Field | Tipe | Arti |
|---|---|---|
| `pay_detail_id` | int | Nomor urut baris pembayaran di dalam transaksi (1, 2, …) |
| `computer_id` | int | Komputer kasir. **Bagian dari kunci**, lihat 3.2 |
| `pay_type_id` | int | ID jenis bayar **milik sistem POS outlet** |
| `pay_type_code` | string | Kode jenis bayar. **Tidak seragam** (`cc`, `1`, `JKT0066`, `STBDG082`) dan dibuat per outlet, jadi jangan dipakai sebagai kunci |
| `pay_type_name` | string \| null | Nama jenis bayar. `null` kalau jenis bayar tidak ada di master POS (belum pernah terjadi di data uji) |
| `pay_type_display_name` | string \| null | Nama tampilan di POS |
| `amount` | float | **Nominal bersih** yang dibayar dengan metode ini, tanpa kembalian. Inilah yang dijumlahkan |
| `cash_change` | float | Kembalian. Hanya terisi di Vtec, dan **tidak** termasuk dalam `amount`. Selalu 0 di Promise. Informasi saja |
| `is_from_edc` | int 0/1 | Informasi dari POS |
| `is_sale` | int 0/1 | Informasi saja. **Jangan dipakai untuk filter** (lihat 4) |
| `is_other_receipt` | int 0/1 | Informasi saja. **Jangan dipakai untuk filter** (lihat 4) |

Nomor kartu, nama pemegang kartu, dan kode approval sengaja tidak dikirim.

### 2.2 Tiga kondisi `payments`

| Kondisi | Isi payload | Arti untuk sync-api |
|---|---|---|
| Agen lama, **atau** view `vw_orderpaydetail` belum dipasang di outlet | Key `payments` **tidak ada** | **Tidak diketahui.** Jangan dianggap nol atau "tanpa pembayaran" |
| View ada, transaksi tanpa pembayaran | `"payments": []` | Memang tidak ada pembayaran |
| View ada, ada pembayaran | `"payments": [ ... ]` | Satu elemen per baris pembayaran |

Ketiga kondisi ini akan bercampur selama rollout, karena outlet dipasang
bertahap. Satu payload hanya berisi satu kondisi, karena view ada atau
tidak ada per outlet, tetapi outlet yang berbeda bisa berada di kondisi
yang berbeda.

---

## 3. Yang perlu dikerjakan di sync-api

### 3.1 Skema

```python
class SalesPaymentSchema(BaseModel):
    pay_detail_id: int
    computer_id: int
    pay_type_id: int
    pay_type_code: Optional[str] = None
    pay_type_name: Optional[str] = None
    pay_type_display_name: Optional[str] = None
    amount: Decimal
    cash_change: Decimal = Decimal(0)
    is_from_edc: int = 0
    is_sale: int = 0
    is_other_receipt: int = 0

class SalesSchema(BaseModel):
    ...
    payments: Optional[list[SalesPaymentSchema]] = None   # None = tidak diketahui
```

`payments` **harus** `Optional` dengan default `None`, bukan `[]`. Tanpa
itu, payload dari agen lama tidak bisa dibedakan dari transaksi tanpa
pembayaran.

Saat ini skema sync-api mengabaikan field yang tidak dikenal, jadi agen
baru tidak menimbulkan error walaupun sync-api belum diubah. Datanya hanya
belum disimpan.

### 3.2 Tabel baris pembayaran (butuh migrasi)

Usulan kunci unik:

```
(outlet_code, transaction_id, computer_id, pay_detail_id)
```

Kunci ini sesuai dengan PK tabel pembayaran di kedua sistem POS
(`PayDetailID, TransactionID, ComputerID`). Sistem POS mengikuti outlet,
dari `API_KEY`.

Kolom yang disarankan: semua field di 2.1, ditambah `outlet_code`,
`pos_system` (dari `API_KEY`), `sale_date` (dari header transaksi), dan
waktu terima.

Untuk `amount`, gunakan tipe `DECIMAL`, bukan float. Nilai dari POS
adalah rupiah bulat.

### 3.3 Upsert per transaksi

Baris pembayaran bisa berubah antar kiriman, misalnya karena metode bayar
diganti sebelum closing, atau karena jumlah barisnya berkurang. Upsert per
baris saja tidak cukup, karena baris yang sudah hilang di POS akan tetap
tersisa di sync-api.

Usulan: setiap kali menerima transaksi dengan key `payments`, **ganti
seluruh baris pembayaran transaksi itu**. Hapus baris lama untuk (outlet,
`transaction_id`, `computer_id`) lalu insert yang baru, dalam satu
transaksi DB. Kalau key `payments` tidak ada, **jangan sentuh** baris yang
sudah tersimpan.

Pengiriman ulang dari outlet adalah hal biasa: closing bisa diulang untuk
tanggal yang sama. Hasil akhirnya harus sama.

### 3.4 Cek kunci header dan item yang sudah ada (penting)

`transaction_id` **tidak unik** di satu outlet. Di salah satu server
Promise, 11.930 `TransactionID` dipakai oleh lebih dari satu
`ComputerID`, di tanggal yang berbeda. Di tanggal yang sama belum pernah
terjadi bentrok, di Promise maupun Vtec.

- Header transaksi di payload **tidak** membawa `computer_id`. Baris
  pembayaran membawanya.
- **Tolong cek:** kalau header atau item disimpan dengan kunci (outlet,
  `transaction_id`) saja, transaksi dari komputer lain dengan
  `transaction_id` yang sama di tanggal lain bisa **menimpa** data lama
  saat upsert. Kalau `sale_date` termasuk dalam kuncinya, risikonya jauh
  lebih kecil.
- Hubungkan pembayaran ke transaksinya lewat elemen `sales` induknya,
  bukan dengan mencari `transaction_id` saja.

Perbaikan jangka panjang: `ComputerID` ditambahkan ke view header di POS
dan ke kunci penyimpanan di sync-api. Kalau sync-api butuh ini, kabari
kami.

### 3.5 Validasi

Per transaksi yang statusnya lunas (`transaction_status_id = 2`,
`receipt_id > 0`, `deleted = 0`) dan membawa key `payments`:

```
| Σ payments.amount − receipt_pay_price | ≤ 0,5
```

Agen sudah memeriksa hal yang sama dengan toleransi 0,5 dan menulis
peringatan di log outlet. Agen tetap mengirim datanya.

Hasil uji di data asli:

| Sistem | Data uji | Hasil |
|---|---|---|
| Promise | 30 hari (3.342 transaksi) dari tabel, 7 hari dari view yang terpasang | Σ `amount` = `receipt_pay_price` di **semua hari**, 0 transaksi tanpa pembayaran |
| Vtec | 30 hari (6.293 transaksi) dari tabel, 7 hari dari view yang terpasang | Σ `amount` = `receipt_pay_price` di **semua hari**, 0 transaksi tanpa pembayaran |

Kalau validasi gagal di sync-api, kemungkinan besar penyebabnya ada di
penyimpanan atau penjumlahan, bukan di data POS.

### 3.6 Rekap untuk ERP

Kontrak ERP meminta satu baris per metode bayar di setiap tujuan
kunjungan:

```json
{ "paymentMethod": "Cash", "paymentAmount": 224250, "fullPaymentAmount": 224250, "notes": "" }
```

- Jumlahkan `amount` per tujuan kunjungan + **(sistem POS, `pay_type_id`)**.
- `paymentMethod` diisi `pay_type_name` apa adanya dari POS. ERP Gateway
  memetakan nama itu ke COA, **per sistem POS**.
- `coaNo` dan `merchantDiscountRate` tidak diisi oleh sync-api. Ini masih
  menunggu konfirmasi ERP Gateway (pertanyaan C dan D di bagian 6).
- **Blokir rekap** kalau Σ `payments` ≠ `grandTotal` per tujuan kunjungan,
  atau kalau ada transaksi dengan kondisi "tidak diketahui" di tanggal itu.

---

## 4. Sifat data yang perlu diketahui

| Hal | Detail | Yang perlu dilakukan |
|---|---|---|
| Transaksi multi-pembayaran | Promise: 24 transaksi dengan 2 baris dan 1 transaksi dengan 4 baris dalam 30 hari. Vtec: 25 transaksi dengan 2 baris | `payments` bisa berisi lebih dari satu baris |
| Nominal negatif | Promise: "Voucher Adjustment" (`pay_type_id` 168) bernilai **−1** per baris, ikut dalam Σ = `receipt_pay_price` | **Jangan dibuang.** Simpan apa adanya |
| Nominal nol | Vtec: ada baris CC BRI (`pay_type_id` 10050) bernilai 0 | Simpan apa adanya. Tidak mengganggu Σ |
| `is_sale` | Vtec: bernilai 0 di hampir semua jenis bayar kecuali Cash | Jangan dipakai untuk filter |
| `is_other_receipt` | Promise: bernilai 1 di BCA DEBIT, Niaga Master, dan Visa BNI, yang jelas pembayaran penjualan | Jangan dipakai untuk filter |
| Voucher diskon Promise | Voucher yang berupa potongan tidak muncul di `payments`, karena sudah mengurangi `receipt_pay_price` | Tidak perlu tindakan |
| `pay_type_code` | Tidak seragam antar outlet | Jangan dipakai sebagai kunci |
| Jenis bayar dihapus dari master POS | Tetap dikirim, karena transaksi lama masih memakainya | Jangan filter |
| Vtec 10008 / 10051 / 10152 | Debit BNI, Debit BRI, QRIS BNI. Dibuang di query lama Vtec, padahal **masih aktif** (±14,3 juta dalam 30 hari di satu outlet) dan **termasuk** dalam `receipt_pay_price` | Agen tetap mengirimnya. **Jangan dibuang** sebelum pertanyaan A terjawab, karena kalau dibuang Σ tidak akan sama dengan `grandTotal` |

---

## 5. Rollout

1. **Agen baru sudah siap** (`main.exe` dan `worker.exe` di-build 18
   November 2026). Agen ini aman dirilis sebelum sync-api diubah.
2. **View `vw_orderpaydetail` dipasang per outlet** oleh admin POS. Sudah
   diuji di satu outlet Promise dan satu outlet Vtec. Sebelum view
   terpasang, key `payments` tidak dikirim.
3. **sync-api sebaiknya sudah siap menyimpan** sebelum outlet pertama
   memasang view, supaya data tidak hilang. Kalau belum, data tetap bisa
   diambil lagi (lihat poin 4).
4. **Data tanggal lama tidak terkirim otomatis.** Agen hanya mengirim
   tanggal yang di-closing. Untuk mengisi tanggal yang sudah lewat, closing
   tanggal itu diulang di outlet. Aman karena upsert.
5. Usulan: mulai dengan satu outlet percontohan per sistem POS, lalu
   cocokkan rekap pembayaran dengan laporan closing POS selama beberapa
   hari sebelum lanjut ke outlet lain.

---

## 6. Pertanyaan yang masih terbuka

| # | Pertanyaan | Dampak ke sync-api | Ditanyakan ke |
|---|---|---|---|
| A | Kenapa query lama Vtec membuang `pay_type_id` 10008/10051/10152? Apakah itu juga berlaku untuk rekap ERP? | Kalau berlaku, aturan blokir Σ = `grandTotal` perlu disesuaikan. Aturannya ditetapkan **per sistem POS**, tidak disalin ke Promise berdasarkan kemiripan nama | Tim keuangan |
| B | Apa beda `paymentAmount` dan `fullPaymentAmount`? | Menentukan isi kedua field di rekap | ERP Gateway |
| C | Apakah COA sepenuhnya diisi ERP Gateway? | Kalau tidak, sync-api butuh tabel pemetaan | ERP Gateway |
| D | Apakah MDR sepenuhnya diisi ERP Gateway? | Sama dengan C | ERP Gateway |
| E | Kalau Σ pembayaran ≠ `grandTotal` (mis. pembulatan), dikirim sebagai `roundingTotal` atau rekap diblokir? Termasuk "Voucher Adjustment" −1 di Promise | Menentukan aturan validasi di 3.5 dan 3.6 | ERP Gateway |
| F | Di dalam satu sistem POS, apakah `pay_type_id` dan namanya sama di semua outlet? | Kalau berbeda, pemetaan perlu per outlet | Cek di POS, lalu ERP Gateway |
| G | Apakah transaksi `deleted = 1` perlu disimpan? Saat ini tetap terkirim, tanpa item dan tanpa pembayaran | Jangan sampai transaksi ini memicu peringatan "tanpa pembayaran" | Tim keuangan |

Kontak untuk pertanyaan soal agen atau isi data POS: tim agen POS.
