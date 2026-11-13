# Usulan kontrak: rekap closing harian dari sync-api Maharasa

Halo tim, kami (sync-api Maharasa) akan mengirim rekap closing harian per
outlet ke API Anda. Di bawah ini kontraknya. Mohon dikoreksi bagian yang tidak
cocok dengan sistem Anda.

**Revisi 3 (12 November 2026).** Menindaklanjuti balasan tim ERP Gateway
tanggal 10 November 2026. Ada tambahan data penjualan (`sales`, `prices`), item
colorplate per warna, dan pembedaan dua alasan `409`. Perubahannya dirangkum di
bagian 6.

## 1. Gambaran

- Satu request = **satu outlet pada satu tanggal produksi**.
- Dikirim **manual** oleh admin kami, biasanya setelah closing outlet masuk.
- Data yang sama bisa dikirim lagi kalau closing di outlet itu direvisi.
  Kiriman dengan `sequence` lebih besar **menggantikan seluruh isi** kiriman
  sebelumnya untuk outlet dan tanggal itu (bukan ditambahkan).
- Sebagian brand tidak memakai laporan closing. Untuk outlet brand itu, satu
  kiriman bisa berisi **tanpa item `closing`**.
- Penjualan outlet-outlet ini **hanya** dikirim ke ERP lewat jalur ini. POS
  tidak mengirim penjualan langsung ke ERP (ESB).

## 2. Request

```
POST {BASE_URL}/api/v1/closing-totals
Authorization: Bearer <token dari Anda>
Content-Type: application/json
Idempotency-Key: <sama dengan messageId>
```

```json
{
  "messageId": "6f1c2a7e-3b4d-4e8f-9a10-2b3c4d5e6f70",
  "sentAt": "2026-10-13T03:00:00Z",
  "sequence": 3,
  "outlet": { "code": "STTSM" },
  "productionDate": "2026-10-12",
  "sales": [
    {
      "visitPurposeName": "DINE IN",
      "paxTotal": 4,
      "flagInclusive": 0,
      "subtotal": 125000,
      "discountTotal": 0,
      "menuDiscountTotal": 0,
      "promotionDiscount": 0,
      "otherTaxTotal": 9375,
      "vatTotal": 13437.5,
      "otherVatTotal": 0,
      "deliveryFee": 0,
      "orderFee": 0,
      "voucherTotal": 0,
      "roundingTotal": 0,
      "grandTotal": 147812.5,
      "paymentTotal": 147812.5,
      "payments": []
    }
  ],
  "items": [
    {
      "source": "closing",
      "menuId": "0b6f2c1e-8a2d-4c3b-9e7f-1a2b3c4d5e6f",
      "menuCode": "SU-001",
      "menuName": "Sushi Roll Salmon",
      "productId": null,
      "productCode": null,
      "productName": null,
      "colorplateSold": 10,
      "posQty": 3,
      "totalSold": 13,
      "waste": 1,
      "adjustment": -1,
      "compensation": 0,
      "prices": [
        {
          "visitPurposeName": "DINE IN",
          "qty": 3,
          "originalPrice": 15000,
          "price": 15000,
          "discount": 0,
          "discountValue": 0,
          "otherTax": 7.5,
          "otherTaxValue": 3375,
          "vat": 10,
          "vatValue": 4837.5,
          "otherVat": 0,
          "otherVatValue": 0,
          "otherTaxOnVat": 0,
          "total": 53212.5
        }
      ]
    },
    {
      "source": "colorplate",
      "menuId": null,
      "menuCode": null,
      "menuName": null,
      "productId": "789",
      "productCode": "CP-YELLOW",
      "productName": "Colorplate Yellow",
      "colorplateSold": 0,
      "posQty": 4,
      "totalSold": 4,
      "waste": 0,
      "adjustment": 0,
      "compensation": 0,
      "prices": [
        {
          "visitPurposeName": "DINE IN",
          "qty": 4,
          "originalPrice": 20000,
          "price": 20000,
          "discount": 0,
          "discountValue": 0,
          "otherTax": 7.5,
          "otherTaxValue": 6000,
          "vat": 10,
          "vatValue": 8600,
          "otherVat": 0,
          "otherVatValue": 0,
          "otherTaxOnVat": 0,
          "total": 94600
        }
      ]
    }
  ]
}
```

### 2.1 Field tingkat kiriman

| Field | Arti |
|---|---|
| `messageId` | Unik per kiriman. **Sama** kalau kami mengulang kiriman yang sama karena timeout/5xx. |
| `sentAt` | Waktu kiriman dibuat, UTC. **Tidak berubah** saat kiriman yang sama diulang. |
| `sequence` | Naik setiap kali outlet + tanggal yang sama dikirim lagi dengan isi baru. **Boleh loncat** (mis. 3 lalu 5). Yang dijamin hanya: kiriman yang lebih baru punya `sequence` lebih besar. |
| `outlet.code` | Kode outlet POS, mis. `STTSM`. |
| `productionDate` | Tanggal produksi (bukan tanggal kirim), `YYYY-MM-DD`. Tanggal bisnis outlet seperti yang dicatat POS dan laporan closing, bukan hasil konversi dari UTC. |

### 2.2 `sales`: penjualan per tujuan kunjungan

Penjualan POS satu outlet + tanggal **dipecah per tujuan kunjungan**
(`visitPurposeName`). Satu elemen `sales` = satu transaksi penjualan di ERP.

- Satu `visitPurposeName` muncul paling banyak sekali.
- Field mengikuti usulan Anda. Field yang tidak relevan diisi `0` atau `""`,
  tidak dihilangkan.
- `otherTaxTotal` adalah service charge, `vatTotal` adalah PPN.
- `orderFee` sementara berisi pendapatan lain dari POS (`OtherIncome`), sampai
  ada kesepakatan field yang tepat.
- `grandTotal` = `subtotal − discountTotal + otherTaxTotal + vatTotal +
  orderFee`. Harga POS kami belum termasuk service charge dan PPN, jadi
  `flagInclusive` selalu `0`.
- `payments` ada di dalam tiap elemen `sales`. **Untuk sementara selalu `[]`**,
  karena data pembayaran belum ditarik dari POS (lihat bagian 6). `paymentTotal`
  tetap diisi sama dengan `grandTotal`.
- `sales` boleh `[]` kalau tidak ada penjualan POS sama sekali pada outlet +
  tanggal itu (mis. hanya ada waste).

Pemetaan tujuan kunjungan dari POS:

| Kode POS (`SaleMode`) | `visitPurposeName` |
|---|---|
| 1 | ⚠ *menyusul* |
| 2 | ⚠ *menyusul* |
| 6 | ⚠ *menyusul* |
| 8 | ⚠ *menyusul* |

### 2.3 `items`

| Field | Arti |
|---|---|
| `source` | `closing` = menu dari laporan closing. `colorplate` = penjualan piring warna di POS, satu item per warna. `pos_only` = produk lain yang terjual di POS (minuman, side dish, dll.). |
| `menuId` / `menuCode` / `menuName` | Identitas menu closing. `menuId` (UUID) adalah kunci yang stabil. Kosong selain untuk `closing`. |
| `productId` | **String.** Kode produk di master produk Maharasa. Diisi untuk `colorplate` dan `pos_only`. |
| `productCode` | Kode produk (SKU) dari master produk. Diisi untuk `colorplate` dan `pos_only`, dan menjadi kuncinya. |
| `productName` | Nama produk dari master produk, bukan nama di POS. |
| `colorplateSold` | Jumlah menu terjual lewat colorplate menurut laporan closing. Hanya untuk `closing`, selain itu `0`. |
| `posQty` | Jumlah terjual menurut POS. Transaksi void tidak dihitung. |
| `totalSold` | `colorplateSold + posQty`. |
| `waste` / `adjustment` / `compensation` | Dari laporan closing. `adjustment` bisa negatif. Untuk `colorplate` dan `pos_only` selalu `0`. |
| `prices` | Rincian harga penjualan (bagian 2.4). |

`menuId` unik per kiriman. `productCode` juga unik per kiriman: kalau beberapa
produk POS mengarah ke produk master yang sama, qty-nya dijumlah.

### 2.4 `prices` dan cara menghindari penjualan dobel

Penjualan colorplate dicatat dua kali di sumber kami: sebagai **jumlah menu**
di laporan closing (`colorplateSold`), dan sebagai **piring per warna** di POS.
Harga yang berlaku adalah **harga piring**, jadi pendapatannya dikirim lewat
item `colorplate`. Akibatnya:

- **`prices` hanya menghitung qty yang benar-benar dibayar di POS**, bukan
  `totalSold`:

  | `source` | Jumlah `prices[].qty` sama dengan |
  |---|---|
  | `closing` | `posQty` (porsi `colorplateSold` tidak punya harga sendiri) |
  | `colorplate` | `totalSold` |
  | `pos_only` | `totalSold` |

  Kalau jumlahnya `0`, `prices` berisi `[]`.
- **Untuk penjualan ERP, mohon pakai `prices`, bukan `totalSold`.** `totalSold`
  menu closing tetap dikirim untuk item journal (pemakaian bahan), dan sudah
  termasuk porsi yang pendapatannya ada di item `colorplate`.
- Tiap elemen `prices` menyebut `visitPurposeName`-nya. Satu item bisa punya
  beberapa elemen kalau terjual di beberapa tujuan kunjungan atau dengan
  beberapa harga.

Yang kami jamin, per `visitPurposeName`:

- Jumlah `prices[].total` dari semua item = `sales[].grandTotal −
  sales[].orderFee`.
- Jumlah `prices[].qty × prices[].price` = `subtotal`.
- Jumlah `prices[].vatValue` = `vatTotal`, jumlah `otherTaxValue` =
  `otherTaxTotal`, jumlah `discountValue` = `discountTotal`.

POS kami mencatat pajak dan diskon per transaksi, bukan per baris. Nilai per
item (`discountValue`, `otherTaxValue`, `vatValue`) kami bagi secara
proporsional dari nilai transaksi. Selisih pembulatan ditaruh di baris dengan
nilai terbesar, supaya jumlahnya tetap sama persis dengan `sales`.

### 2.5 Angka

- Nominal dalam rupiah, sesuai POS.
- Qty dan nominal **paling banyak 2 digit desimal**.

### 2.6 Jaminan lain

- Kami tidak mengirim rekap yang belum lengkap. Kalau ada produk yang belum
  punya master atau mapping yang belum beres, kiriman ditahan di sisi kami
  sampai admin memperbaikinya.

## 3. Response yang kami harapkan

| Status | Arti | Yang kami lakukan |
|---|---|---|
| `200` / `201` | Diterima. Kalau ada ID dari sisi Anda di body, kami simpan. | Tandai terkirim. |
| `409` `duplicate_message` | `messageId` sudah pernah diterima. | Tandai terkirim (duplikat). |
| `409` `stale_sequence` | Anda sudah memegang versi yang lebih baru, kiriman tidak disimpan. | Tandai **ditolak** di layar admin, tidak diulang. Kiriman berikutnya untuk outlet + tanggal itu memakai `sequence` di atas `currentSequence` dari body Anda. |
| `400` / `422` | Payload tidak valid, `Idempotency-Key` ≠ `messageId`, atau `messageId` yang sudah dikenal datang dengan body berbeda. Mohon sertakan alasannya di body. | Tandai gagal, tidak diulang otomatis. |
| `401` / `403` | Token salah atau tidak berhak. | Tandai gagal, tidak diulang. |
| `429` / `5xx` / timeout | Sementara. Kalau ada `Retry-After`, kami ikuti. | Diulang otomatis beberapa kali dengan `messageId` dan body yang sama. |

`409` tanpa `reason` kami perlakukan sebagai `duplicate_message`.

## 4. Volume

Satu request per outlet per hari, sesekali lebih kalau ada revisi. Item per
request perkiraan puluhan, jarang lebih dari 200. Dengan `prices`, body
diperkirakan tetap jauh di bawah 512 KB.

## 5. Keamanan

Token kami simpan di environment server, tidak di kode.

## 6. Perubahan dari revisi 2

| Bagian | Revisi 2 | Revisi 3 |
|---|---|---|
| URL | `{BASE_URL}/closing-totals` | `{BASE_URL}/api/v1/closing-totals` |
| `sales` | Tidak ada | **Baru.** Array, satu elemen per `visitPurposeName` |
| `payments` | Tidak ada | **Baru**, di dalam tiap elemen `sales`. Sementara selalu `[]` |
| `items[].prices` | Tidak ada | **Baru.** Jumlah qty mengikuti `posQty`/`totalSold` (bagian 2.4) |
| Penjualan colorplate | Hanya `colorplateSold` di menu closing | Ditambah item `source: "colorplate"` per warna, membawa harga piring |
| `409` | Satu arti | Dibedakan `duplicate_message` dan `stale_sequence` |
| `sentAt` | "Waktu kirim" | Waktu kiriman dibuat, tidak berubah saat diulang |
| `sequence` | "Naik 1" | Naik, boleh loncat |

**Pembayaran.** Data pembayaran (metode bayar, nominal per metode) tersimpan di
tabel POS yang belum ditarik oleh agen sinkronisasi kami. Kami akan
menambahkannya. Sampai saat itu `payments` dikirim `[]`; begitu tersedia,
kiriman ulang dengan `sequence` baru akan membawa `payments` yang terisi.
