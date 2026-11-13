# Jawaban: balasan kontrak kirim rekap closing

Untuk: tim ERP Gateway
Dari: tim sync-api Maharasa
Tanggal: 12 November 2026

Terima kasih atas balasannya tanggal 10 November. Permintaan Anda sudah kami
tuangkan ke **revisi 3** di dokumen usulan kontrak. Di bawah ini jawaban
pertanyaan balik Anda dan beberapa penyesuaian yang perlu Anda setujui.

---

## 1. Jawaban pertanyaan balik

| # | Pertanyaan | Jawaban |
|---|---|---|
| 1 | Penjualan dobel | **Tidak.** POS outlet-outlet ini tidak mengirim penjualan ke ERP lewat jalur lain. Penjualan hanya lewat sistem ini. |
| 2 | Harga colorplate | **Harga piring**, bukan harga menu. Pendapatannya dikirim sebagai item baru `source: "colorplate"`, satu item per warna piring (penjelasan di bagian 2.2). |
| 3 | Mengosongkan rekap | ⚠ *Usulan, belum final:* kami kirim kiriman dengan `sequence` baru, `items: []`, dan `sales: []`, yang berarti rekap outlet + tanggal itu kosong. Mohon izinkan `items` kosong untuk kasus ini. |
| 4 | Zona waktu | ⚠ *Belum final:* `productionDate` adalah tanggal bisnis outlet seperti yang dicatat POS dan laporan closing, bukan hasil konversi dari UTC. Untuk outlet di zona WIB, ini sama dengan tanggal Asia/Jakarta. |
| 5 | Presisi | Qty dan nominal paling banyak **2 digit desimal**. |

---

## 2. Penyesuaian atas permintaan revisi 3

### 2.1 `sales` menjadi array, dipecah per tujuan kunjungan

Dalam satu hari, satu outlet melayani beberapa tujuan kunjungan (makan di
tempat, bawa pulang, ojek online, dll.). Karena itu `sales` kami kirim sebagai
**array**, satu elemen per `visitPurposeName`. Satu elemen = satu transaksi
penjualan di ERP. Jadi satu rekap bisa menjadi beberapa transaksi, bukan satu.

Field dalam tiap elemen sama dengan usulan Anda. Tiap elemen `prices` juga
menyebut `visitPurposeName`-nya, supaya rincian item bisa dicocokkan ke
transaksinya.

### 2.2 Colorplate sebagai item tersendiri

Laporan closing mencatat colorplate per **menu** (mis. sushi salmon terjual 10
piring), sedangkan harga ada per **warna piring** di POS. Kedua angka itu tidak
bisa dipasangkan. Karena itu:

- Pendapatan colorplate dikirim sebagai item `source: "colorplate"`, satu per
  warna, dengan `productCode` sebagai kuncinya.
- Untuk item `closing`, jumlah `prices[].qty` sama dengan **`posQty`**, bukan
  `totalSold`. Porsi `colorplateSold` tidak punya harga sendiri, karena harganya
  sudah ada di item `colorplate`.
- **Untuk Push Sales, mohon pakai `prices`, bukan `totalSold`.** `totalSold`
  menu closing tetap kami kirim untuk item journal.

Ini mengubah aturan Anda "jumlah `prices[].qty` harus sama dengan `totalSold`".
Aturan lengkapnya ada di bagian 2.4 usulan kontrak revisi 3.

### 2.3 `payments` sementara kosong

Data pembayaran ada di tabel POS yang belum kami tarik. Kami akan
menambahkannya, tetapi butuh perubahan di agen POS. Sementara itu mohon terima
**`payments: []`**, dengan `paymentTotal` tetap diisi sama dengan `grandTotal`.
Begitu datanya tersedia, kami kirim ulang tanggal-tanggal yang terdampak dengan
`sequence` baru.

`payments` kami letakkan di dalam tiap elemen `sales`, karena pembayaran milik
transaksi masing-masing.

### 2.4 Pajak dan diskon per item

POS kami mencatat PPN, service charge, dan diskon per transaksi, bukan per
baris. Nilai per item kami bagi secara proporsional dari nilai transaksi.
Selisih pembulatan ditaruh di baris dengan nilai terbesar, sehingga per
`visitPurposeName` jumlah `prices` selalu sama persis dengan angka di `sales`
(di luar `orderFee`, lihat pertanyaan 1 di bawah).

Harga di POS kami belum termasuk service charge dan PPN, jadi `flagInclusive`
selalu `0` dan `grandTotal` = subtotal − diskon + service charge + PPN.

### 2.5 `409` dan hal kecil (bagian 2.2 dan 2.3 Anda)

- **Sudah kami terapkan.** `stale_sequence` tampil sebagai "ditolak" di layar
  admin dan tidak diulang. Kiriman berikutnya untuk outlet + tanggal itu
  memakai `sequence` di atas `currentSequence` dari body Anda.
  `duplicate_message`, atau `409` tanpa `reason`, tetap dianggap sudah sampai.
- `422` untuk `Idempotency-Key` ≠ `messageId` dan untuk body yang berbeda:
  **setuju.** Kiriman ulang dari kami selalu memakai body yang sama persis.
- `sentAt` tidak berubah saat diulang, dan `sequence` boleh loncat: **setuju**,
  sudah seperti itu di sisi kami.

---

## 3. Pertanyaan dari kami

1. **Pendapatan lain.** POS mencatat `OtherIncome` per transaksi (mis. Rp
   300.000 di satu outlet dalam sehari). Sementara kami isikan ke `orderFee`.
   Apakah itu tepat, atau sebaiknya `deliveryFee` atau field lain?
2. **`sales` kosong.** Apakah `sales: []` bisa diterima untuk outlet + tanggal
   yang hanya punya waste/adjustment tanpa penjualan?
3. **Nama tujuan kunjungan.** Apakah `visitPurposeName` harus persis sama
   dengan daftar di ERP? Kalau ya, mohon kirimkan daftarnya.
