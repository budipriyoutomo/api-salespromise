# Usulan Perubahan Payload `closingreport.submitted`: Harga Satuan dan Nilai Rupiah (v3)

| | |
|---|---|
| Untuk | Tim BI / Data Warehouse (sync-api, penerima `closingreport.submitted`) |
| Dari | Tim Maharasa Colorplate |
| Tanggal | 20 November 2026 |
| Status | **Usulan**, menunggu jawaban BI. Belum di-deploy |
| Dasar | Permintaan BI: harga satuan per piring dan nilai rupiah untuk sold, waste, adjustment, dan compensation |
| Kontrak sebelumnya | v1 (dokumen BI "jawaban pengirim closing") dan v2 ([usulan v2](bi-closing-report-v2-waste-category.md), [jawaban BI v2](jawaban-bi-closing-report-v2.md)) |

## Ringkasan

Setiap item menu di `data.items[]` mendapat lima field baru: harga satuan piring dan nilai rupiah untuk keempat angka yang sudah dikirim (`sold`, `waste`, `adjustment`, `compensation`). Field lain tidak berubah. Exchange, routing key, `messageId`, aturan dedup, dan jaminan at-least-once juga tetap sama.

Kami mengusulkan perubahan ini sebagai **versi 3**. Isinya v2 (termasuk `wasteByCategory`) ditambah harga. Kontrak v2 yang sudah disepakati tidak diubah sama sekali.

Ada lima pertanyaan untuk BI di bagian [Yang perlu dijawab BI](#yang-perlu-dijawab-bi).

## Contoh payload v3 lengkap

Karena tautan kontrak kami tidak bisa dibuka dari sisi BI, berikut payload lengkapnya. Bagian ini cukup dibaca tanpa dokumen lain.

```json
{
  "event": "closingreport.submitted",
  "version": 3,
  "messageId": "<closing_report_id>",
  "sentAt": "2026-12-01T15:15:00+00:00",
  "data": {
    "closingReportId": "<uuid>",
    "date": "2026-12-01",
    "outlet": { "code": "MHR-01", "name": "Maharasa PIK" },
    "brand":  { "code": "MHR", "name": "Maharasa" },
    "items": [
      {
        "menuId": "<uuid>",
        "menuCode": "SU-001",
        "menuName": "Salmon Nigiri",
        "productionDate": "2026-12-01",
        "sold": 42,
        "waste": 3,
        "adjustment": 1,
        "compensation": 2,
        "wasteByCategory": [
          { "categoryCode": "DEFAULT_WASTE", "categoryName": "Default Waste", "quantity": 3 }
        ],
        "unitPrice": 15000,
        "soldAmount": 630000,
        "wasteAmount": 45000,
        "adjustmentAmount": 15000,
        "compensationAmount": 30000
      },
      {
        "menuId": "<uuid>",
        "menuCode": "SU-002",
        "menuName": "Tamago",
        "productionDate": "2026-12-01",
        "sold": 30,
        "waste": 0,
        "adjustment": -1,
        "compensation": 0,
        "wasteByCategory": [],
        "unitPrice": 12500.5,
        "soldAmount": 375015,
        "wasteAmount": 0,
        "adjustmentAmount": -12500.5,
        "compensationAmount": 0
      }
    ]
  }
}
```

## Field baru

| Field | Tipe | Keterangan |
|-------|------|------------|
| `items[].unitPrice` | number | Harga satuan satu piring, dalam rupiah, paling banyak 2 desimal. Selalu ada, selalu ≥ 0 |
| `items[].soldAmount` | number | `sold × unitPrice` |
| `items[].wasteAmount` | number | `waste × unitPrice` |
| `items[].adjustmentAmount` | number | `adjustment × unitPrice`. **Bisa negatif**, karena `adjustment` boleh negatif |
| `items[].compensationAmount` | number | `compensation × unitPrice`. Bisa negatif dengan alasan yang sama |

Semua nilai rupiah dibulatkan ke 2 desimal. Saat ini harga di master kami berupa bilangan bulat rupiah, tapi kolomnya menyimpan 2 desimal, jadi mohon jangan mengasumsikan bilangan bulat.

## Aturan yang dijamin Colorplate

1. **Harga = harga warna piring, bukan harga menu.** Di restoran kaiten, kasir menjual per warna piring, dan satu warna punya satu harga. Angka POS yang kami rekonsiliasi juga per warna. Warna piring diambil dari piring yang benar-benar dibuat dapur hari itu. Kalau menu tidak punya data produksi di hari itu, warnanya diambil dari master menu.
2. **Nilai rupiah selalu cocok dengan angkanya.** Untuk setiap item, `xxxAmount = xxx × unitPrice` (dibulatkan 2 desimal). BI boleh memvalidasi ini.
3. **Sama dengan layar Closing Report.** Angka yang dikirim dihitung oleh kode yang sama dengan tampilan layar Closing Report di Colorplate. Harga, jumlah piring, dan nilai kompensasi di layar sama persis dengan isi pesan.
4. **Harga dibekukan saat submit.** Master kami tidak menyimpan riwayat harga. Pesan disusun dan disimpan saat closing report disubmit, jadi harga yang dikirim adalah harga pada hari itu, meskipun pesannya baru terkirim belakangan karena broker sempat mati.
5. **Harga selalu ada.** Setiap menu wajib punya warna piring. Warna yang sudah dihapus dari master tetap terbaca harganya, jadi `unitPrice` tidak pernah `null`.

## Pesan lama dan kiriman ulang

- Pesan yang sudah terkirim atau sudah antre sebelum deploy **tetap dengan versinya semula** (v1 atau v2). Pesan tidak disusun ulang otomatis.
- Kiriman ulang dengan "susun ulang" (`--rebuild`) menyusun pesan dengan **harga master saat itu**, bukan harga pada hari laporan. Kalau harga warna sudah berubah, nilai rupiahnya ikut berubah.
- Mengikuti aturan dedup BI, pesan v3 dengan `messageId` yang sudah pernah diterima akan dibuang sebagai duplikat. Laporan sebelum peluncuran hanya mendapat harga lewat kiriman ulang dengan `messageId` baru (`<closingReportId>.v3`), yang di BI menjadi revisi baru. Rencananya untuk laporan sejak 1 Oktober 2026 ada di [dokumen kiriman ulang historis](bi-closing-report-v3-historis.md).

## Yang perlu dijawab BI

1. **Versi dan jadwal.** Setuju dikirim sebagai `version: 3`? Consumer v2 belum kami aktifkan. Kalau consumer BI menerima v1, v2, dan v3 sekaligus, kami bisa langsung beralih dari v1 ke v3 tanpa melewati v2. Apakah itu bisa?
2. **Format angka.** Apakah `number` JSON dengan maksimal 2 desimal cocok? Atau BI lebih suka bilangan bulat rupiah, atau string desimal (mis. `"12500.50"`) untuk menghindari pembulatan floating point?
3. **Nilai negatif.** `adjustmentAmount` dan `compensationAmount` bisa negatif. Apakah consumer BI menerimanya?
4. **Sumber harga.** Kami mengirim harga warna piring (unit harga POS). Apakah itu harga yang BI butuhkan? Master kami juga punya kolom harga per menu, tapi kolom itu tidak dipakai di rekonsiliasi.
5. **Data historis.** Apakah BI butuh harga untuk laporan sebelum peluncuran? Kalau ya, aturan dedup di sisi BI harus diubah dulu, dan harganya akan memakai harga master saat pengiriman ulang, bukan harga asli hari itu.

## Rencana peluncuran

1. BI menjawab lima pertanyaan di atas.
2. Kami menyesuaikan payload kalau ada perubahan, lalu mengirim contoh pesan v3 dari lingkungan uji.
3. BI deploy consumer yang menerima v3 (selain v1/v2) dan mengonfirmasi pesan contoh lolos.
4. Kami mengaktifkan v3. Mulai saat itu, closing report yang disubmit dikirim dalam bentuk baru.
