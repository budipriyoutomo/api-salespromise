# Jawaban untuk tim sync-api — event `closingreport.submitted`

Halo tim sync-api, terima kasih atas pertanyaannya. Jawaban di bawah diambil
langsung dari implementasi pengirim (colorplate backend), bukan dari asumsi.

## 1. Koneksi RabbitMQ

| | |
|---|---|
| Exchange | `closingreport_exchange` |
| Tipe exchange | `direct` |
| Durable | Ya (durable, bukan auto-delete) |
| Routing key | `closingreport.submitted` |
| Properti pesan | `content_type: application/json`, `delivery_mode: 2` (persistent), `message_id` = id closing report |

- **Broker**: sama dengan broker yang sekarang dipakai Maharasa untuk POS
  (`posdata_exchange`). Host, port, vhost, dan kredensial akan kami kirim
  lewat jalur terpisah, tidak lewat dokumen ini.
- **Queue**: rencana Anda sudah benar — **queue milik Anda**. Silakan buat
  `syncapi.closingreport` (durable) dan bind ke `closingreport_exchange`
  dengan routing key `closingreport.submitted`. Kami tidak membuat queue.
- Exchange kami deklarasikan ulang di setiap publish dengan parameter yang
  sama (direct, durable). Kalau Anda ikut mendeklarasikannya, **parameternya
  harus persis sama**, atau broker akan menolak dengan `PRECONDITION_FAILED`.
  Cek pasif (`passive = true`) seperti rencana Anda adalah pilihan paling aman.

**Penting — queue harus di-bind sebelum go-live.** Kami mem-publish dengan
flag `mandatory` dan publisher confirms. Selama belum ada queue yang terikat,
broker mengembalikan pesannya dan kami menganggapnya gagal. Pesan tidak hilang:
ia menunggu di outbox kami dan dicoba ulang otomatis (jeda 1, 2, 4, … menit,
maksimal 60 menit, hingga ±25 jam). Setelah itu bisa dikirim ulang manual
dari sisi kami. Jadi tidak perlu ada urutan deploy yang ketat, tapi semakin
cepat binding dibuat, semakin cepat data mengalir.

**Jaminan pengiriman: at-least-once.** Duplikat tetap mungkin (lihat poin 3).

## 2. Kode outlet

`MHR-01` di contoh hanya ilustrasi. `outlet.code` yang dikirim adalah
`outlets.code` di sistem kami — kolom yang sama yang dipakai untuk mencocokkan
data POS yang masuk (`posdata_exchange`, field `outlet`). Jadi nilainya
**adalah kode POS** (mis. `STTSM`).

Satu catatan: saat menerima data POS, kami mencocokkan kode **setelah
normalisasi** (huruf kecil, buang karakter non-alfanumerik, rapatkan spasi).
Artinya kode di master kami dijamin sama *setelah dinormalisasi*, tapi tidak
dijamin sama persis huruf besar/kecilnya dengan POS. Saran kami: lakukan
normalisasi yang sama di sisi Anda saat join (minimal `UPPER(TRIM(...))`).

## 3. Pengiriman ulang / revisi

- **Satu outlet + satu tanggal = satu closing report** (dijaga unique index).
  Closing report yang sudah `submitted` **tidak bisa diedit, disubmit ulang,
  atau dihapus**. Saat ini tidak ada alur revisi.
- **`messageId` selalu sama dengan `closingReportId`**, di setiap pengiriman.
- **`sentAt` berubah di setiap percobaan kirim** — diisi saat publish, bukan
  saat submit. Retry setelah broker mati bisa membawa `sentAt` di hari
  berikutnya. Jangan pakai `sentAt` untuk menentukan hari laporan; pakai
  `data.date`.
- Isi `data` **dibekukan saat submit** dan identik di setiap pengiriman ulang.
  Yang berbeda antar-kiriman hanya `sentAt`.

**Saran untuk aturan dedup Anda:** karena `sentAt` berubah di setiap retry,
aturan "`messageId` + `sentAt` sama = duplikat" tidak akan menangkap duplikat
dari retry — pesan itu akan diperlakukan sebagai "versi lebih baru". Hasilnya
tidak salah (isinya identik), tapi riwayat Anda akan berisi versi kembar.
Lebih tepat dedup cukup berdasarkan **`messageId`** saja. Kalau ke depan ada
alur revisi, kami akan menaikkan `version` dan memberi tahu lebih dulu.

## 4. Kode menu

- **`menuCode` unik per brand, tidak lintas brand.** Dua brand boleh punya
  kode yang sama (begitu juga nama menu).
- **`menuCode` bisa diubah** lewat master data menu oleh admin.
- `menuCode` juga bisa `null` untuk menu lama yang belum diberi kode.

Kesimpulannya: **pakai `menuId` sebagai kunci** — UUID, selalu terisi, tidak
pernah berubah. Kalau tetap butuh kode, pasangkan `(brand.code, menuCode)`,
dan perlakukan sebagai atribut, bukan kunci.

Satu hal yang perlu Anda ketahui: **POS di sistem kami tidak mengenal menu.**
Sushi dijual ke kasir per warna piring, jadi data POS yang masuk ke kami hanya
berisi "N piring warna X terjual" per outlet per hari. Kalau sistem POS Anda
punya data per produk, pemetaan `menuCode` → produk POS perlu dipastikan dulu
ke tim POS; dari sisi kami, perbandingan POS hanya mungkin per warna piring.

## 5. Arti angka

- **`sold`** = jumlah piring menu itu yang ditandai **terjual oleh dapur**
  (data produksi), **bukan** angka POS. Bilangan bulat ≥ 0.
- **`waste`** = jumlah piring yang dibuang. Bilangan bulat ≥ 0.
- **`adjustment` bisa negatif.** Ini koreksi kesalahan pencatatan; validasi
  kami hanya mewajibkan bilangan bulat, tanpa batas bawah.
- **`compensation`** = piring yang diberikan gratis / sebagai kompensasi.
  Seharusnya ≥ 0, tapi validasi kami di level per menu belum memaksakannya —
  mohon tangani nilai negatif secara defensif (tolak ke DLQ atau catat).
- **Hubungan dengan POS**, rumus rekonsiliasi yang kami pakai (per warna piring):

  ```
  selisih = pos_sold - (sold + adjustment + compensation)
  ```

  Artinya dalam keadaan seimbang `pos_sold = sold + adjustment + compensation`
  — compensation dihitung di sisi yang dibandingkan dengan POS. Jadi untuk
  perbandingan, gunakan **`sold + adjustment + compensation`**, bukan `sold`
  saja. Bagaimana tepatnya kasir mencatat piring kompensasi di POS (mis.
  transaksi harga 0) adalah praktik operasional outlet; kami sarankan
  dikonfirmasi ke tim operation sebelum laporan perbandingan dipakai.
- **`productionDate` vs `date`**: di implementasi saat ini, `productionDate`
  **selalu sama dengan `date`, atau `null`** (kalau menu itu tidak punya baris
  produksi di hari tersebut). Stok kemarin tidak pernah masuk laporan hari ini:
  piring yang belum difinalisasi otomatis dicatat sebagai waste di **hari
  produksinya**. Field ini disediakan agar kontraknya tidak perlu berubah kalau
  aturan itu berubah. Catatan: tanggal dihitung dalam zona waktu UTC.

## 6. Lain-lain

- **Frekuensi**: satu pesan per outlet per hari operasional (saat closing
  report disubmit, biasanya malam hari setelah tutup). Retry hanya terjadi
  kalau broker bermasalah.
- **Jumlah item**: satu baris per menu yang tercatat di sales hari itu, jadi
  sebanding dengan jumlah menu brand outlet tersebut — dalam orde puluhan,
  bukan ribuan. Ukuran pesan kecil (beberapa KB).
- **Versi**: dicatat. Setiap perubahan bentuk payload akan menaikkan `version`
  dan kami kabari sebelum dirilis. DLQ untuk versi yang belum didukung adalah
  penanganan yang tepat.
- **Contoh payload nyata**: akan kami kirimkan terpisah dari outlet yang sudah
  berjalan, setelah fitur ini aktif di produksi.

Terima kasih!
