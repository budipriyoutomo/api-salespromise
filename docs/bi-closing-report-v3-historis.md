# Permintaan: Kirim Ulang Closing Report sejak 1 Oktober 2026 dalam Format v3

| | |
|---|---|
| Untuk | Tim BI / Data Warehouse (sync-api, penerima `closingreport.submitted`) |
| Dari | Tim Maharasa Colorplate |
| Tanggal | 23 November 2026 |
| Status | **Draf**, belum dikirim |
| Terkait | [Usulan v3: harga satuan dan nilai rupiah](bi-closing-report-v3-harga.md), terutama pertanyaan no. 5 (data historis) |

## Ringkasan

Kami ingin mengirim ulang semua closing report **sejak 1 Oktober 2026** dalam format v3, supaya data di BI untuk periode itu juga punya harga satuan dan nilai rupiah.

Kiriman ulang memakai **`messageId` baru**, sehingga BI tidak perlu mengubah aturan dedup. Kami belum mengirim apa pun dan menunggu konfirmasi BI soal jadwal.

## Cara kiriman ulang menggantikan data lama

Pesan kiriman ulang membawa:

| Field | Isi |
|---|---|
| `messageId` | **`<closingReportId>.v3`**, misalnya `6f1c2a9e-3b4d-4e5f-8a7b-9c0d1e2f3a4b.v3` |
| `data.closingReportId` | Sama dengan kiriman pertama |
| `version` | `3` |
| `sentAt` | Waktu pengiriman ulang |

Menurut aturan penyimpanan BI yang berlaku sekarang ([jawaban BI v2, bagian 2](jawaban-bi-closing-report-v2.md#2-dedup-v2-dengan-messageid-yang-sama-dianggap-duplikat)), hasilnya:

| Pesan | Perlakuan BI |
|---|---|
| `messageId` baru, `closingReportId` sudah ada, `sentAt` lebih baru | Disimpan sebagai **revisi baru** yang menjadi aktif. Seluruh item revisi lama digantikan, dan revisi lama tetap tersimpan sebagai riwayat. |
| Pesan yang sama terkirim lagi (retry at-least-once) | `messageId`-nya sama dengan kiriman ulang sebelumnya, jadi dianggap duplikat dan dibuang |
| Pesan v1/v2 lama yang masih antre dan tiba belakangan | `sentAt`-nya lebih tua dari revisi v3, jadi disimpan sebagai riwayat dan **tidak** menimpa v3 |

Angka tidak tercatat dua kali, karena BI mengunci laporan pada `closingReportId`, bukan `messageId`. Kalau daftar menu di pesan baru berbeda dari pesan pertama, menu lama yang tidak ada lagi juga tidak ikut terhitung.

`messageId` sengaja dibuat **tetap** (bukan berisi waktu). Kalau skrip kiriman ulang dijalankan dua kali, kiriman kedua dibuang sebagai duplikat dan tidak membuat revisi lagi.

## Yang perlu diketahui BI tentang isi kiriman ulang

1. **Harga memakai master saat pengiriman ulang.** Master kami tidak menyimpan riwayat harga. Kalau harga warna piring berubah antara 1 Oktober dan hari pengiriman, nilai rupiah laporan lama memakai harga baru. Ini berbeda dari pesan v3 normal, yang memakai harga hari submit.
2. **Angka disusun ulang dari data laporan saat ini.** Isinya mengikuti data yang sama dengan layar Closing Report di Colorplate. Jumlah `sold` / `waste` / `adjustment` / `compensation` sama dengan kiriman pertama, kecuali laporannya diubah setelah submit.
3. **Laporan yang dulu terkirim tanpa menu.** Laporan yang dulu terkirim dengan `items: []` (builder lama) ditolak BI dan tidak pernah tersimpan. Kiriman ulangnya sekarang berisi menu, jadi di BI tercatat sebagai laporan **baru**, bukan revisi.
4. **Laporan tanpa menu tidak dikirim**, sama seperti aturan sekarang.
5. **Volume.** Perkiraan kami ±[jumlah] laporan dari [jumlah] outlet. Pesan bisa dikirim bertahap, misalnya per outlet atau per minggu, kalau BI butuh jeda.

## Yang perlu dijawab BI

1. **Kesiapan v3.** Apakah consumer BI yang menyimpan harga v3 sudah berjalan di produksi? Kiriman ulang baru dimulai setelah BI mengonfirmasi. Pertanyaan no. 1–4 di [usulan v3](bi-closing-report-v3-harga.md#yang-perlu-dijawab-bi) juga perlu dijawab kalau belum.
2. **Harga historis.** Apakah harga master saat pengiriman ulang (poin 1 di atas) bisa diterima untuk periode Oktober–November? Kalau BI butuh harga asli per tanggal, mohon beri tahu sumbernya. Kami tidak punya data itu.
3. **Jadwal dan laju.** Kapan kiriman ulang boleh dimulai, dan apakah perlu bertahap?

## Rencana pelaksanaan

1. BI menjawab tiga pertanyaan di atas.
2. Kami mengirim **satu** laporan lama sebagai contoh. BI mengonfirmasi pesannya tercatat sebagai revisi dan item yang aktif adalah item v3.
3. Kami mengirim sisanya sejak 1 Oktober 2026, sesuai laju yang disepakati.
4. Kami mengirim daftar laporan yang terkirim beserta jumlah item per laporan, supaya BI bisa mencocokkan.
