# Pertanyaan untuk tim pengirim `closingreport.submitted`

Halo tim, kami (sync-api Maharasa) sudah menyiapkan consumer untuk event
`closingreport.submitted` sesuai contoh payload yang dikirim. Sebelum
dinyalakan di produksi, ada beberapa hal yang perlu kami pastikan.

## 1. Koneksi RabbitMQ (wajib — tanpa ini consumer belum bisa jalan)

- **Nama exchange** tempat event ini dipublish.
- **Tipe exchange**: direct / topic / fanout?
- **Routing key** yang dipakai.
- **Host, port, dan vhost** broker. Apakah sama dengan broker yang sekarang
  dipakai Maharasa?
- **Siapa yang membuat queue?** Rencana kami: kami membuat queue sendiri
  (`syncapi.closingreport`) dan mengikatnya ke exchange Anda. Exchange-nya
  hanya kami cek keberadaannya, tidak kami buat ulang. Apakah exchange Anda
  durable, dan apakah pesannya dikirim persistent (`delivery_mode = 2`)?

## 2. Kode outlet

Contoh payload memakai `"outlet": { "code": "MHR-01" }`, sedangkan di POS kode
outletnya berbentuk seperti `STTSM`. Kami membandingkan closing dengan
penjualan POS berdasarkan kode ini. **Apakah `outlet.code` yang dikirim akan
sama persis (termasuk huruf besar/kecil) dengan kode outlet di POS?** Kalau
tidak, laporan perbandingannya akan selalu kosong.

## 3. Pengiriman ulang / revisi

- Kalau closing report yang sama dikirim ulang (misalnya setelah diedit),
  apakah `closingReportId` tetap sama?
- Apakah `messageId` selalu sama dengan `closingReportId`, atau berbeda di
  setiap pengiriman?
- Apakah `sentAt` selalu berubah di setiap pengiriman ulang?

Cara kami memproses: pesan dengan `messageId` dan `sentAt` yang sama dianggap
duplikat dan diabaikan. `closingReportId` yang sama dengan `sentAt` lebih baru
menggantikan versi sebelumnya; versi lama tetap kami simpan sebagai riwayat.

## 4. Kode menu

- Apakah `menuCode` (mis. `SU-001`) **unik lintas brand**?
- Apakah `menuCode` **bisa berubah** untuk menu yang sama?

Kami memetakan `menuCode` ke produk POS. Kalau kodenya bisa berubah atau
dipakai ulang oleh brand lain, kami akan memakai `menuId` sebagai kunci.

## 5. Arti angka

- Apakah `adjustment` bisa **negatif**? `sold`, `waste`, dan `compensation`
  kami anggap bilangan bulat ≥ 0. Benar?
- Apakah item yang **dikompensasi** juga tercatat di POS (misalnya sebagai
  transaksi harga 0)? Ini menentukan apakah `sold` dibandingkan dengan qty POS
  saja, atau `sold + compensation`.
- `productionDate` vs `date`: apakah item bisa memiliki tanggal produksi yang
  berbeda dari tanggal closing (misalnya waste stok kemarin)? Kami
  membandingkan dengan penjualan POS per `productionDate`.

## 6. Lain-lain

- Kira-kira berapa jumlah item per pesan, dan berapa kali sehari dikirim per outlet?
- Kalau ke depan ada `version: 2`, pesan versi yang belum kami dukung akan
  masuk dead-letter queue dan tidak hilang. Mohon kabari sebelum versinya naik.
- Kalau memungkinkan, **mohon kirimkan satu contoh payload nyata** dari
  outlet yang sudah berjalan.

Terima kasih!
