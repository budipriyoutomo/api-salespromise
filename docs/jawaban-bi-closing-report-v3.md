# Jawaban untuk tim Colorplate: harga v3 dan kiriman ulang sejak 1 Oktober 2026

| | |
|---|---|
| Untuk | Tim Maharasa Colorplate |
| Dari | Tim sync-api (penerima `closingreport.submitted`) |
| Tanggal | 23 November 2026 |
| Menjawab | [Usulan v3: harga satuan dan nilai rupiah](bi-closing-report-v3-harga.md) dan [Permintaan kirim ulang sejak 1 Oktober 2026](bi-closing-report-v3-historis.md) |

Halo tim Colorplate, terima kasih atas kedua usulannya. Jawaban di bawah sudah kami cocokkan dengan perilaku consumer kami, bukan asumsi. Sisi penerima untuk v3 sudah selesai dan lolos test di tempat kami. Tinggal menunggu deploy.

## Ringkasan jawaban

| Pertanyaan | Jawaban |
|---|---|
| Versi | **Setuju `version: 3`.** Consumer menerima v1, v2, dan v3 sekaligus, jadi Anda boleh langsung beralih dari v1 ke v3 |
| Format angka | `number` JSON dengan **maksimal 2 desimal** diterima. String desimal dan bilangan bulat juga diterima |
| Nilai negatif | `adjustmentAmount` dan `compensationAmount` **boleh negatif**. `unitPrice` tidak boleh negatif |
| Sumber harga | **Harga warna piring sudah tepat** |
| Data historis | **Ya, kirim ulang sejak 1 Oktober 2026**, dengan `messageId` baru **`<closingReportId>.v3`**. Aturan dedup kami tidak berubah |
| Harga historis | Harga master saat pengiriman ulang **bisa kami terima** |
| Jadwal dan laju | Mulai setelah kami konfirmasi deploy. **Tidak wajib bertahap**, tapi kirim satu contoh dulu |

## 1. Versi dan urutan deploy

Kami setuju harga dikirim sebagai `version: 3`. Consumer kami menerima `version` 1, 2, dan 3. Karena v3 sudah memuat semua isi v2, Anda boleh langsung beralih dari v1 ke v3 tanpa melewati v2.

Urutan deploy tetap sama seperti v2: pesan v3 yang tiba sebelum consumer baru berjalan akan ditolak dan masuk DLQ kami, bukan menumpuk di outbox Anda.

1. Kami deploy consumer v3. Consumer ini tetap menerima v1 dan v2, jadi aman di-deploy kapan saja sebelum Anda.
2. Kami kabari Anda bahwa consumer v3 sudah jalan di produksi.
3. Anda kirim contoh pesan v3 dari lingkungan uji, lalu kami konfirmasi pesannya lolos.
4. Anda aktifkan v3.

## 2. Format angka, nilai negatif, dan sumber harga

- **Format.** `number` JSON dengan paling banyak 2 desimal sudah cukup. Kami membaca angkanya sebagai desimal, bukan floating point, jadi `12500.5` tersimpan persis `12500.50`. String desimal seperti `"12500.50"` dan bilangan bulat juga diterima. Anda tidak perlu mengubah format.
- **Batas.** Setiap nilai paling banyak 12 digit sebelum koma (sampai `999999999999.99`).
- **Negatif.** `adjustmentAmount` dan `compensationAmount` boleh negatif. `unitPrice` harus `0` atau lebih.
- **Sumber harga.** Harga warna piring sudah sesuai kebutuhan kami. Rekonsiliasi dan rekap kami juga menghitung pendapatan piring per warna. Kolom harga per menu tidak perlu dikirim.

## 3. Kiriman ulang sejak 1 Oktober 2026: pakai `messageId` baru

Kami **tidak** mengubah aturan dedup. Pesan dengan `messageId` yang sudah tersimpan tetap dianggap duplikat, apa pun `version`-nya. Gantinya, mohon kirim ulang dengan `messageId` baru:

| Field | Isi |
|---|---|
| `messageId` | **`<closingReportId>.v3`**, misalnya `6f1c2a9e-3b4d-4e5f-8a7b-9c0d1e2f3a4b.v3` |
| `data.closingReportId` | Sama dengan kiriman pertama |
| `version` | `3` |
| `sentAt` | Waktu pengiriman ulang, dengan offset zona waktu |

Ini sudah cukup karena kami mengunci laporan pada **`closingReportId`**, bukan pada `messageId`. Setiap pesan yang kami terima disimpan sebagai satu *revisi* laporan, dan yang kami pakai hanya revisi yang aktif. Kekhawatiran di usulan Anda bahwa `messageId` baru membuat angka dobel tidak berlaku di sisi kami.

| Pesan masuk | Perlakuan kami |
|---|---|
| `messageId` baru, `closingReportId` sudah ada, `sentAt` lebih baru | **Revisi baru, menjadi aktif.** Seluruh item revisi lama digantikan. Menu yang tidak ada lagi di pesan baru tidak ikut terhitung. Revisi lama tetap kami simpan sebagai riwayat |
| `messageId` yang sama terkirim lagi (retry, atau skrip dijalankan dua kali) | Duplikat, di-ack lalu dibuang |
| Pesan v1/v2 lama yang masih antre dan tiba setelah v3 | `sentAt`-nya lebih tua, jadi disimpan sebagai riwayat dan **tidak** menimpa v3 |
| `closingReportId` yang belum pernah kami simpan | Laporan baru |

Beberapa catatan:

- **Pakai titik, bukan titik dua.** Kami memakai `messageId` sebagai id korelasi log, dan id itu hanya boleh berisi huruf, angka, `.`, `_`, dan `-`. Dengan `:`, pesannya tetap tersimpan, tetapi lognya tidak bisa dikaitkan ke pesan Anda.
- **Mohon `messageId` tetap, jangan berisi waktu.** Dengan begitu kiriman ulang yang sama tidak pernah menjadi dua revisi.
- **`sentAt` harus lebih baru dari kiriman pertama.** Kalau jam pengirim salah dan `sentAt` lebih tua, pesannya tersimpan sebagai riwayat dan diam-diam tidak aktif. Langkah contoh di bagian 5 akan menangkap hal ini.
- **Laporan yang dulu terkirim dengan `items: []`.** Laporan itu kami tolak waktu itu dan tidak pernah tersimpan. Kiriman ulangnya akan tercatat sebagai laporan **baru**, bukan revisi.

## 4. Harga historis

Harga master saat pengiriman ulang **bisa kami terima** untuk periode Oktober–November. Kami tidak butuh sumber harga lain. Kiriman ulang tetap bisa kami bedakan dari pesan v3 normal lewat akhiran `.v3` di `messageId` dan waktu kirimnya.

## 5. Jadwal dan laju

- Kiriman ulang dimulai **setelah kami mengonfirmasi consumer v3 berjalan di produksi** (bagian 1, langkah 2).
- Kirim **satu** laporan lama dulu sebagai contoh. Kami akan cek bahwa pesannya tercatat sebagai revisi aktif dengan item dan harga v3, lalu mengabari Anda.
- Setelah itu sisanya boleh dikirim sekaligus. Consumer kami memproses pesan satu per satu dari antrean, jadi kami tidak butuh jeda. Kalau Anda lebih nyaman mengirim per outlet atau per minggu, itu juga tidak masalah.
- Setelah selesai, mohon kirim daftar laporan yang terkirim beserta jumlah item per laporan. Kami akan mencocokkannya dengan revisi aktif di tempat kami.

## Cara consumer kami memvalidasi v3

Supaya Anda tahu pesan seperti apa yang kami tolak:

| Kondisi | Perlakuan kami |
|---|---|
| `version: 3` tapi ada item tanpa `unitPrice`, `soldAmount`, `wasteAmount`, `adjustmentAmount`, atau `compensationAmount` (atau `null`) | **Ditolak** → DLQ |
| `version: 3` tapi ada item tanpa `wasteByCategory` | **Ditolak** → DLQ (aturan v2 tetap berlaku) |
| Lebih dari 2 desimal, atau lebih dari 12 digit sebelum koma | **Ditolak** → DLQ |
| `unitPrice` negatif | **Ditolak** → DLQ |
| `NaN` / `Infinity` | **Ditolak** → DLQ (bukan JSON standar) |
| `adjustmentAmount` / `compensationAmount` negatif | Diterima |
| `xxxAmount` ≠ `xxx × unitPrice` (dibulatkan 2 desimal) | **Diterima dengan peringatan.** Laporan tetap kami simpan, dan selisihnya kami catat untuk ditindaklanjuti bersama Anda |
| `version: 1` atau `2` tanpa harga | Diterima seperti sekarang |
| Versi selain 1, 2, dan 3 | **Ditolak** → DLQ |

Untuk nilai rupiah yang tidak cocok, kami sengaja tidak menolak pesannya. Angka `sold` / `waste` / `adjustment` / `compensation` tetap benar dan tetap dipakai, jadi satu nilai rupiah yang janggal tidak perlu membuang laporan satu hari. Aturan "nilai rupiah selalu cocok" di usulan Anda tetap kami anggap jaminan. Kalau peringatan ini muncul, kami akan mengabari Anda.
