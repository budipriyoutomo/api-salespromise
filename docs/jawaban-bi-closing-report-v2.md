# Jawaban untuk tim Colorplate: rincian waste per kategori (`closingreport.submitted` v2)

| | |
|---|---|
| Untuk | Tim Maharasa Colorplate |
| Dari | Tim sync-api (penerima `closingreport.submitted`) |
| Tanggal | 14 Oktober 2026 |
| Menjawab | [Usulan perubahan payload: rincian waste per kategori](bi-closing-report-v2-waste-category.md) |

Halo tim Colorplate, terima kasih atas usulannya. Jawaban di bawah sudah kami
cocokkan dengan perilaku consumer kami, bukan asumsi. Sisi penerima untuk v2
sudah selesai dan sudah lolos test di tempat kami. Tinggal menunggu deploy.

## Ringkasan jawaban

| Pertanyaan | Jawaban |
|---|---|
| 1. Versi | **A, versi 2.** Mohon jangan deploy sebelum kami mengonfirmasi consumer v2 sudah berjalan di produksi |
| 2. Dedup | Pesan v2 dengan `messageId` yang sudah pernah kami terima dianggap **duplikat dan dibuang**. Data v1-nya tetap berlaku |
| 3. Bentuk | Array `wasteByCategory` per menu **sudah cukup**. Kami tidak butuh total di level laporan atau kode per alasan waste |

## 1. Versi: kami pilih A (v2)

Kami setuju perubahan bentuk payload menaikkan `version`.

**Urutan deploy sangat penting.** Consumer kami saat ini di produksi hanya
menerima `version: 1`. Ini koreksi kecil untuk bagian risiko opsi A di usulan
Anda: pesan v2 yang kami tolak **tidak menumpuk di outbox Anda**. Broker sudah
menerima pesannya karena queue kami terikat, jadi publish Anda dianggap
berhasil. Pesan itu lalu masuk ke dead-letter queue (DLQ) kami dan laporan
hari itu tidak tercatat sampai dikirim ulang. Karena itu:

1. Kami deploy consumer yang menerima v1 **dan** v2. Consumer ini tetap
   menerima v1, jadi aman di-deploy kapan saja sebelum Anda.
2. Kami kabari Anda bahwa consumer v2 sudah jalan.
3. Anda kirim contoh pesan v2 dari lingkungan uji (langkah 2 di rencana
   peluncuran Anda).
4. Kami konfirmasi pesannya lolos, lalu Anda deploy.

## 2. Dedup: v2 dengan `messageId` yang sama dianggap duplikat

Aturan kami tidak berubah dari [jawaban sebelumnya](jawaban-pengirim-closing.md):
`messageId` yang sudah tersimpan dianggap duplikat, apa pun isinya. Jadi kalau
closing report lama disusun ulang (`--rebuild`) setelah deploy dan dikirim
sebagai v2 dengan `messageId` yang sama, pesan itu kami terima (ack) tapi
**tidak menimpa** data v1. Pesan itu juga tidak masuk DLQ.

Kami **tidak membutuhkan** rincian kategori untuk tanggal sebelum peluncuran,
jadi tidak perlu ada pengiriman ulang data historis. Kalau nanti berubah, kami
akan menghubungi Anda lebih dulu, karena aturan dedup di sisi kami juga harus
diubah.

## 3. Bentuk: array per menu sudah cukup

- Total per kategori di level laporan (`data.wasteByCategory`) **tidak perlu**.
  Kami bisa menjumlahkannya sendiri dari item.
- `categoryCode` per alasan waste **tidak perlu** untuk saat ini.
- Kami memakai `categoryCode` sebagai kunci dan **tidak meng-hardcode daftar
  kategori**. Kategori baru otomatis kami terima.

## Cara consumer kami memvalidasi v2

Supaya Anda tahu pesan seperti apa yang kami tolak:

| Kondisi | Perlakuan kami |
|---|---|
| `version: 2` tapi ada item tanpa `wasteByCategory` (atau `null`) | **Ditolak** → DLQ |
| `wasteByCategory: []` untuk item dengan `waste` = 0 | Diterima |
| `categoryCode` / `categoryName` kosong atau hanya spasi | **Ditolak** → DLQ |
| `categoryCode` lebih dari 50 karakter, `categoryName` lebih dari 255 karakter | **Ditolak** → DLQ |
| `quantity` 0, negatif, atau pecahan | **Ditolak** → DLQ |
| `categoryCode` yang sama muncul dua kali dalam satu item | **Ditolak** → DLQ |
| Total `quantity` ≠ `waste` | **Diterima dengan peringatan.** Laporan tetap kami simpan dan selisihnya kami catat untuk ditindaklanjuti bersama Anda |
| `version: 1` tanpa `wasteByCategory` | Diterima seperti sekarang |
| Versi selain 1 dan 2 | **Ditolak** → DLQ |

Untuk total yang tidak cocok, kami sengaja tidak menolak pesannya. Angka
`waste` per menu tetap benar dan tetap dipakai, jadi satu rincian yang
janggal tidak perlu membuang laporan satu hari. Aturan "jumlahnya selalu
cocok" di usulan Anda tetap kami anggap jaminan. Kalau peringatan ini muncul,
kami akan mengabari Anda.

Huruf `categoryCode` tidak kami ubah (spasi di ujung saja yang dibuang). Jadi
`DEFAULT_WASTE` dan `default_waste` akan kami anggap kategori berbeda. Mohon
kodenya selalu dikirim dengan huruf yang sama.

## Catatan kecil untuk dokumen usulan

- **Link kontrak v1 tidak bisa dibuka dari sisi kami.** `api-reference.md`
  tidak ikut terkirim bersama usulan. Kalau isinya berbeda dari
  [jawaban sebelumnya](jawaban-pengirim-closing.md), mohon dikirimkan.
- **Urutan dengan `quantity` yang sama.** Usulan menyebut array diurutkan
  `quantity` menurun. Kami tidak bergantung pada urutan, tapi supaya
  `--rebuild` benar-benar menghasilkan isi yang identik, sebaiknya ada aturan
  urutan kedua, misalnya `categoryCode` naik.
