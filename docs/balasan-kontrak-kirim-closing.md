# Balasan: kontrak kirim rekap closing (usulan revisi 2)

Untuk: tim sync-api Maharasa
Dari: tim ERP Gateway
Tanggal: 10 November 2026

Terima kasih atas usulan kontrak (revisi 2) dan spesifikasi penerimanya. Secara umum
kami setuju dengan bentuknya. Di bawah ini ada jawaban pertanyaan di bagian 7, beberapa
perubahan yang kami minta (sebaiknya dijadikan **revisi 3**), dan beberapa pertanyaan
balik.

Data closing akan kami teruskan ke ERP: **penjualan** ke Push Sales, sedangkan
**waste, adjustment, dan kompensasi** ke item journal. Karena itu kami butuh data harga,
pajak, dan pembayaran yang belum ada di payload saat ini (bagian 2.1).

---

## 1. Jawaban pertanyaan bagian 7

| # | Pertanyaan | Jawaban |
|---|---|---|
| 1 | URL & token | `POST {BASE_URL}/api/v1/closing-totals`. `BASE_URL` staging dan produksi menyusul. Token Bearer kami buat per lingkungan dan kami kirim lewat jalur terpisah. |
| 2 | Ganti penuh per outlet + tanggal | **Setuju.** Kiriman dengan `sequence` lebih besar menggantikan seluruh isi rekap. |
| 3 | `posQty` desimal | **Diterima.** Disimpan sebagai `NUMERIC` tanpa pembulatan. Mohon sebutkan jumlah digit desimal maksimal. |
| 4 | Kode outlet | Kami cocokkan setelah `UPPER(TRIM(...))` dan memetakannya sendiri ke cabang ERP. Kode outlet POS bisa dikirim apa adanya. |
| 5 | Kunci produk `pos_only` | **`productCode`**. Kiriman yang hanya berisi item `pos_only` **diterima**. |
| 6 | Batas | Body maksimal 512 KB. Rate limit per token akan kami informasikan bersama token. Kami membalas jauh di bawah 10 detik, karena data hanya disimpan dan tidak diproses saat itu. |
| 7 | Endpoint cek | Belum kami sediakan. Bisa ditambahkan nanti kalau dibutuhkan. |

---

## 2. Perubahan yang kami minta (revisi 3)

### 2.1 Harga, pajak, dan pembayaran

Satu rekap (outlet + tanggal) akan kami kirim ke ERP sebagai **satu transaksi
penjualan**. Untuk itu kami butuh angka penjualan dari sisi Anda. **Kami tidak
menghitung ulang harga maupun pajak**, angka yang Anda kirim kami teruskan apa adanya.

Usulan bentuknya (nama field mengikuti format penjualan ERP):

```json
{
  "messageId": "...",
  "sentAt": "...",
  "sequence": 3,
  "outlet": { "code": "STTSM" },
  "productionDate": "2026-10-12",
  "sales": {
    "visitPurposeName": "DINE IN",
    "paxTotal": 0,
    "flagInclusive": 0,
    "subtotal": 195000,
    "discountTotal": 0,
    "menuDiscountTotal": 0,
    "promotionDiscount": 0,
    "otherTaxTotal": 9750,
    "vatTotal": 19500,
    "otherVatTotal": 0,
    "deliveryFee": 0,
    "orderFee": 0,
    "voucherTotal": 0,
    "roundingTotal": 0,
    "grandTotal": 224250,
    "paymentTotal": 224250
  },
  "payments": [
    {
      "paymentMethod": "Cash",
      "coaNo": "1 1 01 01",
      "paymentAmount": 224250,
      "fullPaymentAmount": 224250,
      "merchantDiscountRate": 0,
      "notes": ""
    }
  ],
  "items": [
    {
      "source": "closing",
      "menuId": "0b6f2c1e-8a2d-4c3b-9e7f-1a2b3c4d5e6f",
      "...": "field revisi 2 tetap sama",
      "totalSold": 13,
      "prices": [
        {
          "qty": 13,
          "originalPrice": 15000,
          "price": 15000,
          "discount": 0,
          "discountValue": 0,
          "otherTax": 5,
          "otherTaxValue": 9750,
          "vat": 10,
          "vatValue": 19500,
          "otherVat": 0,
          "otherVatValue": 0,
          "otherTaxOnVat": 0,
          "total": 224250
        }
      ]
    }
  ]
}
```

Aturan yang kami usulkan:

- **`sales`** dan **`payments`** wajib ada, termasuk kalau kiriman hanya berisi
  `pos_only`. Nominal mengikuti satuan yang dipakai POS (rupiah).
- **`items[].prices`** adalah rincian harga per item. Bentuknya array, supaya satu menu
  yang terjual dengan lebih dari satu harga (mis. sebagian kena promo) tetap menjadi
  **satu item**. `menuId` dan `productId` tetap unik per kiriman, sama seperti
  revisi 2.
- Jumlah `prices[].qty` harus sama dengan `totalSold`. Kalau `totalSold = 0`,
  `prices` berisi array kosong `[]`.
- Field yang tidak relevan diisi `0` atau `""`, jangan dihilangkan.

### 2.2 Dua alasan `409` dibedakan

Kami akan membalas `409` dengan body yang menyebutkan alasannya:

```json
{ "reason": "duplicate_message", "message": "messageId sudah diterima", "id": "..." }
{ "reason": "stale_sequence", "message": "sequence lebih lama", "currentSequence": 4 }
```

`duplicate_message` artinya data **memang sudah ada** di kami. `stale_sequence` artinya
data **tidak kami simpan**, karena kami sudah memegang versi yang lebih baru.

Kami minta pengirim **membedakan keduanya di layar admin**. Kalau `stale_sequence`
ditandai "terkirim", admin tidak akan tahu ada data yang ditolak. Ini bisa terjadi
misalnya kalau `sequence` di sisi Anda mundur setelah database di-restore.

### 2.3 Hal kecil

- `422` juga akan kami balas kalau header `Idempotency-Key` tidak sama dengan
  `messageId`, atau kalau `messageId` yang sudah dikenal datang dengan body yang
  berbeda.
- Mohon gunakan definisi `sentAt` dan `sequence` dari dokumen spesifikasi:
  `sentAt` tidak berubah saat diulang, dan `sequence` boleh loncat. Usulan revisi 2
  menulisnya sedikit berbeda.

---

## 3. Pertanyaan balik

1. **Penjualan dobel.** Apakah POS outlet-outlet ini **juga** mengirim penjualannya
   langsung ke ERP (ESB) lewat jalur lain? Kalau ya, penjualan di `totalSold` akan
   terhitung dua kali di ERP.
2. **Harga colorplate.** Untuk penjualan colorplate (`colorplateSold`), harga apa yang
   dipakai di `prices`: harga piring, atau harga menu?
3. **Mengosongkan rekap.** `items` minimal 1 elemen. Kalau sebuah revisi seharusnya
   menghapus seluruh rekap (mis. closing salah outlet), bagaimana Anda akan
   mengirimnya?
4. **Zona waktu.** Apakah `productionDate` memakai tanggal Asia/Jakarta?
5. **Presisi.** Berapa digit desimal maksimal untuk qty dan nominal?

---

## 4. Yang terjadi di sisi kami setelah data diterima

Supaya ekspektasinya sama: begitu kami membalas `201`, data **baru tersimpan di
gateway** dan belum masuk ERP. Operator kami meninjaunya lalu mengirimnya ke ERP secara
manual. Revisi (`sequence` baru) tetap bisa dikirim kapan saja. Operator kami akan
melihat bahwa rekap tersebut punya versi baru.
