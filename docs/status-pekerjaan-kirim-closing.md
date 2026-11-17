# Status pekerjaan kirim rekap closing (revisi 3)

Untuk: tim ERP Gateway
Dari: tim sync-api Maharasa
Tanggal: 17 November 2026

Menyusul surat kami tanggal 12 November (jawaban atas balasan kontrak), berikut
status pekerjaan di sisi kami. Sebagian besar revisi 3 sudah selesai dibuat.
Beberapa hal **sengaja belum kami kerjakan**. Di bawah ini alasannya dan apa
yang kami tunggu.

---

## 1. Yang sudah selesai

- **Payload revisi 3**:
  - `sales` per `visitPurposeName`;
  - `items[].prices` dengan diskon, service charge, dan PPN yang dibagi per baris;
  - harga piring colorplate di `prices` menu closing (lihat koreksi di bawah).
- **Penanganan `409`**:
  - `stale_sequence` dicatat sebagai ditolak dan tidak diulang;
  - kiriman berikutnya memakai `sequence` di atas `currentSequence` Anda;
  - `duplicate_message` dianggap sudah sampai.
- **Presisi**: qty dan nominal paling banyak 2 digit desimal.
- **Zona waktu** (surat 12 November, bagian 1 nomor 4, kini final): semua
  outlet berada di zona **WIB**. `productionDate` adalah tanggal bisnis outlet
  seperti di POS, sama dengan tanggal Asia/Jakarta.

Belum ada data yang kami kirim ke sistem Anda karena alamat endpoint dan token
belum kami terima (lihat bagian 3).

### Koreksi atas surat 12 November, bagian 2.2 (colorplate)

Item `source: "colorplate"` per warna piring **tidak jadi kami kirim**.
Sebagai gantinya:

- Produk piring per warna di POS tidak dikirim sebagai item, karena qty-nya
  sudah terwakili `colorplateSold` di menu closing.
- Porsi `colorplateSold` setiap menu diberi **harga piring warna menu itu**,
  di dalam `prices` menu closing. Tujuan kunjungannya mengikuti piring warna
  itu di POS.
- Jumlah `prices[].qty` menu closing sekarang sama dengan **`totalSold`**
  (`colorplateSold + posQty`), bukan `posQty` saja. Aturan ini sama untuk
  semua item.

Sistem closing kami memverifikasi piring dapur terhadap POS, jadi total
penjualan yang kami kirim sama dengan uang yang diterima kasir. Rinciannya ada
di dokumen usulan kontrak revisi 3 (pembaruan 17 November), bagian 2.4.

---

## 2. Yang belum dikerjakan dan alasannya

| # | Pekerjaan | Kenapa belum | Yang kami tunggu |
|---|---|---|---|
| 1 | **Mengosongkan rekap** (kiriman dengan `items: []` dan `sales: []`) | Saat ini sistem kami menolak mengirim rekap kosong. Kami baru mau mengubahnya kalau Anda setuju menerima `items` kosong. Tanpa persetujuan itu, kiriman seperti ini akan ditolak validasi di sisi Anda. | Persetujuan Anda atas usulan kami di surat 12 November, bagian 1 nomor 3. |
| 2 | **Nama tujuan kunjungan** (`visitPurposeName`) | POS mencatat tujuan kunjungan sebagai kode angka (1, 2, 6, 8). Kami belum tahu nama yang harus dipakai. Sementara ini kami kirim `"SALEMODE 1"`, `"SALEMODE 2"`, dst. Kalau ERP mencocokkan nama ini dengan daftarnya, nama sementara itu akan gagal dicocokkan. | Daftar resmi `visitPurposeName` dari ERP (surat 12 November, bagian 3 nomor 3). Setelah daftarnya ada, kami pasangkan ke kode POS. |
| 3 | **`payments`** | Data metode pembayaran belum ditarik dari POS ke sistem kami. Untuk menariknya, agen POS di setiap outlet perlu diubah dan sistem kami perlu tempat simpan baru. Sementara ini `payments: []`, dengan `paymentTotal` = `grandTotal`. Nanti isinya hanya `paymentMethod` (nama jenis bayar di POS), `paymentAmount`, `fullPaymentAmount`, dan `notes`. `coaNo` dan `merchantDiscountRate` tidak kami kirim; mohon diatur di ERP Gateway per `paymentMethod`. | Tidak menunggu Anda. Perubahan agen POS sedang kami kerjakan. Begitu selesai, tanggal yang terdampak kami kirim ulang dengan `sequence` baru. |
| 4 | **Pendapatan lain** (`OtherIncome` POS) | Belum jelas field mana yang tepat. Sementara ini kami isikan ke `orderFee`. Kalau ternyata salah, hanya pemetaan yang berubah dan kami kirim ulang tanggal yang terdampak. | Jawaban Anda atas surat 12 November, bagian 3 nomor 1: `orderFee`, `deliveryFee`, atau field lain. |
| 5 | **`sales: []`** untuk outlet + tanggal yang hanya punya waste/adjustment | Sistem kami sudah bisa menyusunnya, tetapi belum kami pastikan validasi Anda menerimanya. | Jawaban Anda atas surat 12 November, bagian 3 nomor 2. |

---

## 3. Yang kami perlukan dari Anda

1. Persetujuan untuk **rekap kosong** (`items: []`, `sales: []`).
2. **Daftar resmi `visitPurposeName`**.
3. **Field untuk `OtherIncome`**.
4. Kepastian bahwa **`sales: []` diterima**.
5. **Alamat endpoint dan token** untuk lingkungan uji. Setelah keduanya kami
   terima, kami bisa mulai uji kirim memakai skenario di dokumen spesifikasi
   penerima.
6. **Persetujuan bahwa `coaNo` dan `merchantDiscountRate` diatur di ERP
   Gateway**, berdasarkan `paymentMethod` yang kami kirim.
7. **Arti `paymentAmount` dan `fullPaymentAmount`.** Apa bedanya? Misalnya,
   apakah salah satunya termasuk uang kembalian pada pembayaran tunai?
8. **Selisih pembulatan kasir.** Kalau total pembayaran berbeda sedikit dari
   `grandTotal` karena pembulatan di kasir, apakah selisihnya dikirim sebagai
   `roundingTotal`?

Butir 1, 2, dan 4 menentukan apakah kiriman pertama kami lolos validasi Anda.
Butir 6–8 kami perlukan sebelum `payments` mulai diisi. Mohon dijawab lebih
dulu kalau memungkinkan.

---

## 4. Catatan

- Rekap outlet + tanggal yang menunya belum diberi warna piring oleh admin
  kami akan ditahan dulu di sisi kami. Rekap tanggal itu menyusul, tanpa
  perubahan di sisi Anda.
- Setiap perubahan di atas mengubah isi rekap. Kami akan mengirimnya sebagai
  kiriman baru dengan `sequence` lebih tinggi untuk outlet + tanggal yang sama,
  sesuai semantik ganti penuh di kontrak.
