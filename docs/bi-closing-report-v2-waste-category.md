# Usulan Perubahan Payload `closingreport.submitted`: Rincian Waste per Kategori

| | |
|---|---|
| Untuk | Tim BI / Data Warehouse |
| Dari | Tim Maharasa Colorplate |
| Tanggal | 13 Oktober 2026 |
| Status | **Usulan — menunggu konfirmasi BI** |
| Kontrak saat ini | `closingreport.submitted` v1 — [api-reference.md § Keluar: closing report ke BI](api-reference.md#keluar-closing-report-ke-bi) |

## Ringkasan

Colorplate akan mengelompokkan setiap alasan waste ke dalam **kategori waste**. Kami ingin BI menerima, untuk setiap menu, rincian waste per kategori. Angka `waste` per menu yang dikirim sekarang tetap ada. Yang ditambahkan hanya pecahannya.

Kami butuh tiga jawaban dari BI (lihat [Yang perlu dijawab BI](#yang-perlu-dijawab-bi)). Pertanyaan utamanya: perubahan ini dikirim sebagai **versi 2**, atau sebagai **field tambahan di versi 1**?

## Yang berubah

Setiap elemen `data.items[]` mendapat satu field baru, `wasteByCategory`. Bagian lain payload tidak berubah: exchange, routing key, `messageId`, aturan dedup, dan jaminan at-least-once tetap sama.

### Contoh payload (usulan v2)

```json
{
  "event": "closingreport.submitted",
  "version": 2,
  "messageId": "<closing_report_id>",
  "sentAt": "2026-10-20T15:15:00+00:00",
  "data": {
    "closingReportId": "<uuid>",
    "date": "2026-10-20",
    "outlet": { "code": "MHR-01", "name": "Maharasa PIK" },
    "brand":  { "code": "MHR", "name": "Maharasa" },
    "items": [
      {
        "menuId": "<uuid>",
        "menuCode": "SU-001",
        "menuName": "Salmon Nigiri",
        "productionDate": "2026-10-20",
        "sold": 42,
        "waste": 7,
        "adjustment": 1,
        "compensation": 0,
        "wasteByCategory": [
          { "categoryCode": "DEFAULT_WASTE", "categoryName": "Default Waste", "quantity": 6 },
          { "categoryCode": "UNCATEGORIZED", "categoryName": "Belum dikategorikan", "quantity": 1 }
        ]
      },
      {
        "menuId": "<uuid>",
        "menuCode": "SU-002",
        "menuName": "Tamago",
        "productionDate": "2026-10-20",
        "sold": 30,
        "waste": 0,
        "adjustment": 0,
        "compensation": 0,
        "wasteByCategory": []
      }
    ]
  }
}
```

### Field baru

| Field | Tipe | Keterangan |
|-------|------|------------|
| `items[].wasteByCategory` | array | Selalu ada. Kosong (`[]`) kalau `waste` = 0. Diurutkan `quantity` menurun |
| `items[].wasteByCategory[].categoryCode` | string | **Kunci stabil.** Tidak berubah setelah kategori dipakai. Pakai ini untuk join dan agregasi |
| `items[].wasteByCategory[].categoryName` | string | Nama tampilan saat pesan disusun. Bisa berubah dari waktu ke waktu, jadi jangan dipakai sebagai kunci |
| `items[].wasteByCategory[].quantity` | integer | Jumlah piring, selalu > 0 |

## Aturan yang dijamin Colorplate

1. **Jumlahnya selalu cocok.** Untuk setiap item, total `wasteByCategory[].quantity` sama dengan `waste`. BI boleh memvalidasi ini dan menolak pesan yang tidak memenuhinya.
2. **Selisih tidak disembunyikan.** Waste yang tidak bisa dipastikan kategorinya, terutama data sebelum fitur ini hidup, masuk ke kategori khusus `UNCATEGORIZED`. Kode ini dicadangkan dan tidak akan dipakai untuk kategori lain.
3. **Kategori dibekukan saat waste dicatat.** Kalau admin nanti memindahkan sebuah alasan ke kategori lain, waste yang sudah tercatat tetap di kategori lamanya. Laporan hari kemarin tidak berubah karena aktivitas hari ini, dan pesan yang disusun ulang (`--rebuild`) menghasilkan rincian yang sama.
4. **Daftar kategori tidak tetap.** Saat peluncuran hanya ada satu kategori, `DEFAULT_WASTE` (Default Waste), dan semua alasan waste yang ada dipetakan ke sana. Admin restoran bisa menambah kategori kapan saja. **Mohon BI tidak meng-hardcode daftar kategori.** Perlakukan `categoryCode` yang baru sebagai dimensi baru.

### Daftar kategori saat peluncuran

| `categoryCode` | `categoryName` | Alasan waste yang dipetakan |
|----------------|----------------|-----------------------------|
| `DEFAULT_WASTE` | Default Waste | Expired, Tabrakan Belt, Berkurang Qty, Serangga, Lainnya, Auto-waste, Import backdate |
| `UNCATEGORIZED` | Belum dikategorikan | (cadangan sistem, untuk waste tanpa kategori) |

Catatan: "Auto-waste" adalah piring yang tidak ditutup sampai akhir hari dan otomatis dicatat sebagai waste pada hari produksinya. "Import backdate" adalah data produksi hari lalu yang diimpor admin.

## Pilihan versi

| | **A. Versi 2** (usulan kami) | **B. Field tambahan di v1** |
|---|---|---|
| `version` | `2` | tetap `1` |
| Syarat di sisi BI | Konsumen mengenali `version: 2` sebelum kami deploy | Konsumen v1 **mengabaikan field yang tidak dikenal** (tidak memakai skema ketat) |
| Risiko | Kalau BI belum siap, pesan v2 ditolak dan menumpuk di outbox kami (tidak hilang, akan dikirim ulang) | Kalau ternyata konsumen memakai validasi skema ketat, pesan ditolak tanpa sinyal jelas bahwa bentuknya berubah |
| Kelebihan | Perubahan kontrak terlihat jelas. BI bisa memproses v1 dan v2 berdampingan | Tidak perlu koordinasi waktu deploy |

Kami merekomendasikan **A (versi 2)**, sesuai aturan kontrak bahwa perubahan bentuk payload menaikkan `version`.

### Pesan lama dan kiriman ulang

- Pesan yang sudah dikirim atau sudah antre di outbox sebelum deploy **tetap v1**. Payload dibekukan saat closing report disubmit.
- Kiriman ulang dengan "susun ulang" (`--rebuild`) setelah deploy akan menghasilkan **v2 dengan `messageId` yang sama** seperti pesan v1-nya. Kalau BI melakukan dedup berdasarkan `messageId`, mohon pertimbangkan apakah v2 boleh menimpa v1 untuk id yang sama.
- Kami tidak berencana mengirim ulang data historis secara massal. Kalau BI membutuhkan rincian kategori untuk tanggal sebelum peluncuran, kabari kami. Hasilnya akan seluruhnya `UNCATEGORIZED` atau `DEFAULT_WASTE`, tergantung data yang bisa dicocokkan.

## Yang perlu dijawab BI

1. **Versi:** pilih A (v2) atau B (field tambahan di v1)? Kalau A, kapan konsumen BI siap menerima `version: 2`?
2. **Dedup:** pesan v2 dengan `messageId` yang sama seperti pesan v1 sebelumnya diperlakukan sebagai pembaruan (menimpa) atau duplikat (dibuang)?
3. **Bentuk:** apakah array `wasteByCategory` per menu sudah sesuai kebutuhan? Atau BI juga butuh total per kategori di level laporan (`data.wasteByCategory`), atau `categoryCode` per alasan waste (lebih rinci dari kategori)?

## Rencana peluncuran

1. BI menjawab tiga pertanyaan di atas.
2. Colorplate menyelesaikan fitur dan mengirim contoh pesan v2 dari lingkungan uji.
3. BI mengonfirmasi konsumen siap.
4. Deploy. Mulai saat itu, closing report yang disubmit dikirim dalam bentuk baru.
