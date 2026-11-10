# Spesifikasi penerima: rekap closing dari sync-api Maharasa

Dokumen ini untuk tim yang membangun **aplikasi penerima** rekap closing harian
dari sync-api Maharasa. Isinya: endpoint yang perlu disediakan, bentuk data
yang akan datang, cara menangani kiriman ulang, dan response yang diharapkan
pengirim.

Semua perilaku pengirim di sini diambil dari implementasi sync-api
(`app/services/closing_export_service.py` dan
`app/services/closing_export_client.py`). Latar belakang dan pertanyaan
terbuka ada di `docs/usulan-kontrak-kirim-closing.md`.

---

## 1. Ringkasan

| | |
|---|---|
| Arah | sync-api Maharasa → aplikasi Anda (HTTP push) |
| Pemicu | Manual. Admin Maharasa menekan **Kirim** di halaman Closing |
| Satuan kiriman | **Satu outlet × satu tanggal produksi** per request |
| Semantik | Kiriman baru **menggantikan seluruh isi** kiriman sebelumnya untuk outlet + tanggal yang sama |
| Jaminan | At-least-once. Duplikat mungkin terjadi, dengan `messageId` yang sama |
| Volume | Kira-kira 1 request per outlet per hari, lebih kalau ada revisi. Puluhan item per request, jarang lebih dari 200 |

---

## 2. Endpoint yang perlu disediakan

```
POST <URL yang Anda tentukan>          # usulan: {BASE_URL}/closing-totals
Authorization: Bearer <token>
Content-Type: application/json
Idempotency-Key: <sama dengan messageId di body>
```

- URL lengkap dan token disimpan di sisi pengirim sebagai `CLOSING_EXPORT_URL`
  dan `CLOSING_EXPORT_TOKEN`. Kirimkan keduanya lewat jalur terpisah, bukan
  lewat dokumen atau chat.
- Body dikirim sebagai JSON UTF-8. Karakter non-ASCII (mis. nama menu) tidak
  di-escape.
- **Body identik byte per byte** di setiap percobaan ulang dengan
  `messageId` yang sama.

### Batas waktu

Pengirim memakai **timeout 10 detik** per percobaan (bisa diatur dari sisi
pengirim). Admin menunggu di depan layar selama proses berjalan, jadi:

- Balas secepat mungkin. Simpan dulu, proses berat jalankan di belakang.
- Kalau melewati timeout, pengirim menganggap gagal sementara dan mengirim
  ulang. Jadi request yang sebenarnya sudah tersimpan bisa datang lagi.
  Idempotensi (bagian 5) wajib ada.

---

## 3. Payload

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
      "productCode": null,
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
      "productId": "456",
      "productCode": "DRK-OCHA-01",
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

### 3.1 Field tingkat atas

| Field | Tipe | Wajib | Keterangan |
|---|---|---|---|
| `messageId` | string (UUID v4) | ya | Unik per kiriman. **Sama** saat pengirim mengulang kiriman yang sama, baik otomatis maupun lewat tombol *Ulangi*. Sama dengan header `Idempotency-Key`. |
| `sentAt` | string, ISO-8601 UTC, format `YYYY-MM-DDTHH:MM:SSZ` | ya | Waktu payload disusun. **Tidak berubah** saat diulang. Jangan dipakai untuk menentukan hari laporan; pakai `productionDate`. |
| `sequence` | integer ≥ 1 | ya | Naik 1 setiap kali outlet + tanggal yang sama dikirim dengan kiriman baru. Untuk satu `(outlet.code, productionDate)`, nilai yang lebih besar = data yang lebih baru. |
| `outlet.code` | string | ya | Kode outlet POS, mis. `STTSM`. Sebaiknya dicocokkan setelah `UPPER(TRIM(...))`. |
| `productionDate` | string `YYYY-MM-DD` | ya | Tanggal produksi (bukan tanggal kirim). |
| `items` | array, minimal 1 elemen | ya | Seluruh isi rekap outlet + tanggal itu. |

### 3.2 Field item

Semua field selalu ada di setiap item. Yang tidak relevan bernilai `null`
(untuk identitas) atau `0` (untuk angka).

| Field | Tipe | `source = closing` | `source = pos_only` |
|---|---|---|---|
| `source` | `"closing"` \| `"pos_only"` | `closing` | `pos_only` |
| `menuId` | string (UUID) \| null | **terisi**, kunci stabil menu | `null` |
| `menuCode` | string \| null | bisa `null` atau berubah | `null` |
| `menuName` | string \| null | terisi | `null` |
| `productId` | string \| null | `null` | **terisi**, kode master produk Maharasa, stabil dan unik di semua outlet |
| `productCode` | string \| null | `null` | **selalu terisi** (SKU dari master produk) |
| `productName` | string \| null | `null` | nama dari master produk (bukan nama di POS) |
| `colorplateSold` | number | jumlah terjual menurut laporan closing | `0` |
| `posQty` | number | qty POS untuk menu itu; `0` kalau menu memang tidak dijual di POS | qty POS |
| `totalSold` | number | `colorplateSold + posQty` | sama dengan `posQty` |
| `waste` | number | dari laporan closing | `0` |
| `adjustment` | number, **bisa negatif** | dari laporan closing | `0` |
| `compensation` | number | dari laporan closing | `0` |

**Tentang angka.** Nilai bulat dikirim sebagai integer (`3`), nilai pecahan
sebagai desimal (`2.5`). `posQty` bisa pecahan kalau POS mencatat qty pecahan.
Simpan sebagai `NUMERIC`/`DECIMAL`, jangan `INTEGER`.

**Kunci unik item** dalam satu kiriman:
- `closing` → `menuId`
- `pos_only` → `productId`

### 3.3 Yang dijamin pengirim

- **Tidak ada penjualan terhitung dua kali.** Penjualan colorplate sudah masuk
  `colorplateSold`; produk colorplate di POS tidak dikirim lagi sebagai
  `pos_only`.
- Satu produk master muncul **paling banyak sekali** per kiriman (qty beberapa
  ProductID POS ke master yang sama sudah dijumlah).
- Transaksi void tidak dihitung.
- Rekap yang belum lengkap (menu belum dipetakan, produk tanpa master, mapping
  dobel) **tidak akan dikirim**. Ditahan di sisi pengirim sampai diperbaiki.
- Untuk brand yang tidak memakai laporan closing, kiriman bisa berisi
  **hanya item `pos_only`**.

---

## 4. Validasi yang disarankan

Tolak dengan **`422`** (atau `400`) dan sebutkan field yang salah di body
kalau:

- field tingkat atas wajib hilang, atau tipe/formatnya salah;
- `items` kosong;
- `source` bukan `closing` / `pos_only`;
- item `closing` tanpa `menuId`, atau item `pos_only` tanpa `productId` /
  `productCode`;
- ada `menuId` atau `productId` yang muncul dua kali dalam satu kiriman;
- `outlet.code` tidak dikenal di sistem Anda (kalau memang perlu divalidasi).

Opsional: cek `totalSold == colorplateSold + posQty`. Pengirim selalu
memenuhinya, jadi selisih berarti ada yang salah di jalan.

Penolakan `4xx` (selain `409` dan `429`) **tidak diulang otomatis** oleh
pengirim. Admin akan melihat kode HTTP dan body response Anda di riwayat
kiriman, jadi tulis pesan yang bisa dibaca manusia.

---

## 5. Idempotensi & urutan

Ada dua kunci yang perlu dicek, urutannya penting.

### 5.1 `messageId` — kiriman yang sama datang lagi

Terjadi kalau response Anda tidak sampai ke pengirim (timeout, koneksi putus)
atau admin menekan *Ulangi*. Isinya identik.

- Kalau `messageId` sudah pernah **berhasil disimpan** → jangan simpan lagi.
  Balas **`409`**, atau `200` dengan hasil yang sama seperti sebelumnya.
  Pengirim menganggap keduanya sukses.

### 5.2 `sequence` — kiriman baru untuk outlet + tanggal yang sama

Untuk `(outlet.code, productionDate)` yang sama:

| Kondisi | Tindakan |
|---|---|
| Belum ada data | Simpan. Balas `201`. |
| `sequence` baru **>** yang tersimpan | **Ganti seluruh item** dengan isi kiriman baru (hapus/nonaktifkan item lama yang tidak ada lagi). Balas `200`/`201`. |
| `sequence` baru **≤** yang tersimpan, `messageId` berbeda | Data lebih lama atau bentrok. Jangan timpa. Balas `409`. |

**Penting:** semantiknya **ganti penuh**, bukan tambah atau merge per item.
Kalau suatu menu/produk ada di kiriman lama tetapi tidak ada di kiriman baru,
artinya item itu sudah tidak berlaku.

`sequence` tidak selalu berurutan rapat di sisi Anda. Kiriman yang gagal di
tengah jalan tetap memakai nomornya, jadi Anda bisa menerima `1` lalu langsung
`3`.

### 5.3 Pseudo-code

```text
terima(request):
    cek token                                   → 401 kalau salah
    validasi payload                            → 422 kalau tidak valid

    BEGIN TRANSACTION
    kalau ada kiriman dengan messageId ini:
        ROLLBACK; balas 409 { "message": "sudah diterima", "id": <id lama> }

    kunci baris rekap (outlet, productionDate)   -- SELECT ... FOR UPDATE
    kalau ada dan sequence_tersimpan >= sequence:
        ROLLBACK; balas 409 { "message": "sequence lebih lama", "current": sequence_tersimpan }

    simpan kiriman (messageId, sequence, payload mentah, diterima_pada)
    ganti semua item rekap (outlet, productionDate) dengan items baru
    set sequence_tersimpan = sequence
    COMMIT
    balas 201 { "id": <id kiriman> }
```

Gunakan constraint `UNIQUE(message_id)` di database sebagai pengaman terakhir
kalau dua request yang sama tiba bersamaan.

---

## 6. Response

| Status | Kapan | Yang dilakukan pengirim |
|---|---|---|
| `200` / `201` / `2xx` lain | Diterima & disimpan | Tandai **terkirim** |
| `409` | `messageId` sudah ada, atau `sequence` lebih lama | Tandai **duplikat** (dianggap sudah sampai, tidak diulang) |
| `400` / `422` | Payload tidak valid | Tandai **gagal**, tidak diulang |
| `401` / `403` | Token salah / tidak berhak | Tandai **gagal**, tidak diulang |
| `404` / `4xx` lain | — | Tandai **gagal**, tidak diulang |
| `429` | Rate limit | **Diulang** otomatis |
| `5xx`, timeout, koneksi gagal | Gangguan sementara | **Diulang** otomatis |

- **Body response** bebas, sebaiknya JSON. Pengirim menyimpan maksimal 2000
  karakter pertama untuk ditampilkan ke admin. Kalau ada ID dari sisi Anda,
  sertakan (mis. `{"id": "..."}`); berguna untuk penelusuran.
- **Jangan pakai `409` untuk kesalahan lain.** Pengirim menganggap `409` =
  "data sudah ada di tujuan", sehingga kiriman itu tidak akan dicoba lagi.

### Perilaku retry pengirim

- Default: **2 kali ulang** setelah percobaan pertama (total 3 percobaan).
- Jeda: 1 detik, lalu 2 detik (eksponensial, maksimal 30 detik).
- Kalau Anda mengirim header **`Retry-After: <detik>`** (bilangan bulat) di
  response `429`/`5xx`, jeda itu yang dipakai, dibatasi maksimal 30 detik.
- Setiap percobaan ulang memakai `messageId`, `Idempotency-Key`, dan body yang
  sama persis.
- Setelah semua percobaan gagal, admin bisa menekan **Ulangi** kapan saja,
  juga dengan `messageId` yang sama.

---

## 7. Skema penyimpanan yang disarankan

Hanya contoh. Sesuaikan dengan sistem Anda.

```sql
-- Setiap request yang diterima, untuk audit & idempotensi.
CREATE TABLE closing_kiriman (
    id               BIGSERIAL PRIMARY KEY,
    message_id       UUID        NOT NULL UNIQUE,
    outlet_code      VARCHAR(20) NOT NULL,
    production_date  DATE        NOT NULL,
    sequence         INTEGER     NOT NULL,
    sent_at          TIMESTAMPTZ NOT NULL,
    payload          JSONB       NOT NULL,
    diterima_pada    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Status terkini per outlet × tanggal.
CREATE TABLE closing_rekap (
    outlet_code      VARCHAR(20) NOT NULL,
    production_date  DATE        NOT NULL,
    sequence         INTEGER     NOT NULL,
    kiriman_id       BIGINT      NOT NULL REFERENCES closing_kiriman(id),
    PRIMARY KEY (outlet_code, production_date)
);

-- Item rekap terkini; diganti penuh setiap sequence baru.
CREATE TABLE closing_rekap_item (
    outlet_code      VARCHAR(20)   NOT NULL,
    production_date  DATE          NOT NULL,
    source           VARCHAR(10)   NOT NULL,          -- closing | pos_only
    menu_id          UUID,
    menu_code        VARCHAR(50),
    menu_name        TEXT,
    product_id       VARCHAR(50),
    product_code     VARCHAR(50),
    product_name     TEXT,
    colorplate_sold  NUMERIC(14,3) NOT NULL DEFAULT 0,
    pos_qty          NUMERIC(14,3) NOT NULL DEFAULT 0,
    total_sold       NUMERIC(14,3) NOT NULL DEFAULT 0,
    waste            NUMERIC(14,3) NOT NULL DEFAULT 0,
    adjustment       NUMERIC(14,3) NOT NULL DEFAULT 0,  -- bisa negatif
    compensation     NUMERIC(14,3) NOT NULL DEFAULT 0,
    FOREIGN KEY (outlet_code, production_date)
        REFERENCES closing_rekap(outlet_code, production_date)
);

CREATE UNIQUE INDEX ON closing_rekap_item (outlet_code, production_date, menu_id)
    WHERE source = 'closing';
CREATE UNIQUE INDEX ON closing_rekap_item (outlet_code, production_date, product_id)
    WHERE source = 'pos_only';
```

Simpan `payload` mentah di `closing_kiriman`. Kalau ada selisih angka, payload
itu bisa dibandingkan langsung dengan riwayat kiriman di sisi Maharasa
(pengirim juga menyimpan payload yang sama).

---

## 8. Skenario uji

| # | Skenario | Hasil yang diharapkan |
|---|---|---|
| 1 | Kiriman pertama outlet + tanggal | `201`, rekap tersimpan |
| 2 | Request yang sama persis dikirim lagi (messageId sama) | `409` atau `200`, **tidak ada** baris ganda |
| 3 | Dua request sama tiba bersamaan | Satu tersimpan, yang lain `409` |
| 4 | `sequence` 2 dengan item berkurang | Item yang hilang tidak ada lagi di rekap |
| 5 | `sequence` 1 datang setelah `sequence` 2 | `409`, rekap tetap isi `sequence` 2 |
| 6 | `sequence` loncat (1 lalu 3) | `201`, diterima normal |
| 7 | Kiriman hanya berisi item `pos_only` | `201` |
| 8 | `posQty` desimal, `adjustment` negatif | Tersimpan tanpa pembulatan |
| 9 | Token salah | `401` |
| 10 | Item `pos_only` tanpa `productCode` | `422` dengan nama field |
| 11 | Proses lebih dari 10 detik | Pengirim mengulang; pastikan skenario 2 tetap aman |
| 12 | Nama menu dengan karakter non-ASCII | Tersimpan utuh (UTF-8) |

---

## 9. Yang perlu Anda kirim balik ke tim Maharasa

1. **URL** endpoint staging dan produksi.
2. **Token** Bearer untuk masing-masing lingkungan (lewat jalur aman).
3. Batas ukuran body, rate limit, dan timeout di sisi Anda kalau ada.
4. Konfirmasi format kode outlet dan kunci produk (`productId` vs
   `productCode`) yang Anda pakai.
5. (Opsional) Endpoint untuk mengecek rekap yang tersimpan per outlet +
   tanggal, untuk rekonsiliasi.
