# Usulan kontrak: rekap closing harian dari sync-api Maharasa

Halo tim, kami (sync-api Maharasa) akan mengirim rekap closing harian per
outlet ke API Anda. Belum ada kontrak, jadi di bawah ini usulan kami. Mohon
dikoreksi bagian yang tidak cocok dengan sistem Anda, lalu jawab pertanyaan di
bagian 6.

## 1. Gambaran

- Satu request = **satu outlet pada satu tanggal produksi**, berisi semua menu
  hari itu.
- Dikirim **manual** oleh admin kami, biasanya setelah closing outlet masuk.
- Data yang sama bisa dikirim lagi kalau closing di outlet itu direvisi.
  Kiriman yang lebih baru **menggantikan seluruh isi** kiriman sebelumnya untuk
  outlet dan tanggal itu (bukan ditambahkan).

## 2. Request

```
POST {BASE_URL}/closing-totals
Authorization: Bearer <token dari Anda>
Content-Type: application/json
Idempotency-Key: <sama dengan messageId>
```

```json
{
  "messageId": "6f1c2a7e-3b4d-4e8f-9a10-2b3c4d5e6f70",
  "sentAt": "2026-10-13T03:00:00Z",
  "sequence": 2,
  "outlet": { "code": "STTSM" },
  "productionDate": "2026-10-12",
  "items": [
    {
      "source": "closing",
      "menuId": "0b6f2c1e-8a2d-4c3b-9e7f-1a2b3c4d5e6f",
      "menuCode": "SU-001",
      "menuName": "Sushi Roll Salmon",
      "productId": null,
      "productName": null,
      "colorplateSold": 10,
      "posQty": 3,
      "totalSold": 13,
      "waste": 1,
      "adjustment": -1,
      "compensation": 0
    },
    {
      "source": "pos_only",
      "menuId": null,
      "menuCode": null,
      "menuName": null,
      "productId": 456,
      "productName": "Ocha Dingin",
      "colorplateSold": 0,
      "posQty": 2,
      "totalSold": 2,
      "waste": 0,
      "adjustment": 0,
      "compensation": 0
    }
  ]
}
```

| Field | Arti |
|---|---|
| `messageId` | Unik per kiriman. **Sama** kalau kami mengulang kiriman yang sama karena timeout/5xx — mohon diperlakukan sebagai duplikat. |
| `sentAt` | Waktu kirim, UTC. |
| `sequence` | Naik 1 setiap kali outlet + tanggal yang sama dikirim lagi dengan isi baru. Kiriman dengan `sequence` lebih kecil dari yang sudah Anda terima sebaiknya ditolak (409). |
| `outlet.code` | Kode outlet POS, mis. `STTSM`. |
| `productionDate` | Tanggal produksi (bukan tanggal kirim), `YYYY-MM-DD`. |
| `items[].source` | `closing` = menu dari laporan closing; `pos_only` = produk yang terjual di POS tetapi tidak ada menunya di laporan closing. |
| `menuId` / `menuCode` / `menuName` | Identitas menu closing. `menuId` (UUID) adalah kunci yang stabil; `menuCode` bisa berubah atau kosong. Kosong untuk `pos_only`. |
| `productId` / `productName` | Produk POS. Hanya diisi untuk `pos_only`. |
| `colorplateSold` | Jumlah terjual menurut laporan closing. |
| `posQty` | Jumlah terjual menurut POS untuk outlet & tanggal yang sama. Transaksi void tidak dihitung. |
| `totalSold` | `colorplateSold + posQty`. |
| `waste` / `adjustment` / `compensation` | Dari laporan closing. `adjustment` bisa negatif; untuk `pos_only` selalu 0. |

## 3. Response yang kami harapkan

| Status | Arti | Yang kami lakukan |
|---|---|---|
| `200` / `201` | Diterima. Body bebas; kalau ada ID dari sisi Anda, kami simpan. | Tandai terkirim. |
| `409` | `messageId` sudah pernah diterima, atau `sequence` lebih lama. | Tandai terkirim (duplikat) / tampilkan ke admin. |
| `400` / `422` | Payload tidak valid. Mohon sertakan field yang salah di body. | Tandai gagal, tidak diulang otomatis. |
| `401` / `403` | Token salah atau tidak berhak. | Tandai gagal, tidak diulang. |
| `429` / `5xx` / timeout | Sementara. Kalau ada `Retry-After`, kami ikuti. | Diulang otomatis beberapa kali dengan `messageId` yang sama. |

## 4. Volume

Satu request per outlet per hari, sesekali lebih kalau ada revisi. Jumlah item
per request mengikuti jumlah menu outlet ditambah produk `pos_only` —
perkiraan puluhan, jarang lebih dari 200.

## 5. Keamanan

Kami simpan token di environment server, tidak di kode. Kalau Anda lebih memilih
API key di header lain, HMAC, atau daftar IP yang diizinkan, mohon sebutkan.

## 6. Pertanyaan

1. **URL** staging dan produksi, serta cara kami mendapatkan token.
2. **Ganti penuh per outlet + tanggal** (bagian 1) — cocok dengan sistem Anda?
   Atau Anda butuh per menu?
3. **`posQty` bisa desimal** kalau POS mencatat qty pecahan. Apakah API Anda
   menerima desimal, atau harus bilangan bulat?
4. **Kode outlet** — apakah sistem Anda memakai kode outlet POS yang sama
   (mis. `STTSM`, termasuk huruf besar/kecil)?
5. **Item `pos_only`** — apakah perlu, atau Anda hanya butuh menu dari laporan
   closing?
6. **Batas** ukuran body, rate limit, dan timeout di sisi Anda.
7. Apakah ada **endpoint untuk mengecek** apa yang sudah Anda terima untuk
   outlet + tanggal tertentu? Berguna untuk rekonsiliasi.
