# Checklist deploy — migrasi 010, Fase 7 (closing report), perubahan void

Disusun 2026-10-05, diperbarui setelah jawaban pengirim
([jawaban-pengirim-closing.md](jawaban-pengirim-closing.md)). Berlaku untuk
perubahan yang belum di-deploy per tanggal itu:

| Perubahan | Efek di produksi |
|---|---|
| Migrasi `010_outlet_code_composite_keys.sql` | PK/FK `ordertransaction` & `orderdetail` jadi komposit dengan `outlet_code`. Memperbaiki outlet yang ditolak sync karena TransactionID bentrok. **Mengunci tabel selama backfill.** |
| Migrasi `011_closing_reports.sql` | 5 tabel baru `closing_*`, kosong. Tidak menyentuh tabel lama. |
| Migrasi `012_closing_menu_id.sql` | ALTER tabel `closing_*` saja (kunci menu `menu_id`, dedup per `message_id`, kolom boleh NULL). Pada deploy pertama tabelnya masih kosong. |
| Transaksi void dibuang dari rekap | `/by-group`, `/colorplate`, dan **publish RabbitMQ** tidak lagi menghitung `Deleted=1`. Angka event colorplate bisa lebih kecil dari event lama untuk tanggal yang sama. |
| Consumer closing report | Container baru `maharasa-closing-consumer`. Topologi sudah diketahui; tinggal host/port/vhost/kredensial broker dari pengirim. |
| Frontend | Halaman `/closing` dan `/closing-menu`, perbaikan waktu UTC (status sync tidak lagi salah 7 jam). Tidak ada env baru. |

Migrasi dijalankan **otomatis** oleh `migrate.py` saat container API start. Kalau
satu migrasi gagal, container berhenti dan API tidak melayani request sampai
masalahnya dibereskan. Karena itu langkah pra-deploy di bawah wajib.

---

## A. Sebelum deploy (produksi, read-only)

- [ ] **A1. Backup.** `pg_dump` database produksi. 010 tidak punya migrasi
      balik — kalau perlu mundur, jalannya restore dari backup ini.
- [ ] **A2. Lihat migrasi mana yang belum jalan.** Di container API yang sedang
      berjalan (versi lama), perintah ini hanya membaca:

      docker compose exec maharasa-apisales python migrate.py --status

      Catat semua yang belum bertanda `[x]`. Kalau 006–009 juga belum, mereka
      ikut jalan di deploy ini.
- [ ] **A3. Jalankan query 0 dan 4** dari
      `migrations/checks/orderdetail_outlet_collision.sql` di dalam transaksi
      read-only:

      BEGIN TRANSACTION READ ONLY;
      -- tempel query 0 dan query 4 dari file di atas
      ROLLBACK;

      - Query 0: kalau `ordertransaction_pkey` sudah `PRIMARY KEY ("TransactionID", outlet_code)`,
        010 sudah pernah jalan — tidak ada yang berubah.
      - Query 4: **`transaksi_tanpa_outlet` dan `item_yatim` harus 0.** Kalau
        tidak, 010 berhenti dan container tidak start. Jangan deploy; isi
        `outlet_code` / tangani item yatim dulu (keputusan manual — jangan hapus data).
- [ ] **A4. Ukuran tabel** untuk memperkirakan lama kunci 010:

      SELECT COUNT(*) FROM orderdetail;

      010 meng-UPDATE setiap baris item sekali dan membangun dua index. Pilih
      jam sepi; selama itu sync POS tertahan (POS akan mengirim ulang).
- [ ] **A5. Kabari pemilik consumer event colorplate** bahwa mulai deploy ini
      transaksi void tidak dihitung, jadi angka per warna bisa turun.

## B. Deploy backend (sync-api)

Consumer closing report **jangan** dinyalakan dulu kalau `CLOSING_*` belum
diisi — tanpa itu container keluar dan di-restart terus. Nyalakan API saja:

- [ ] **B1.** `git pull` di server, lalu:

      docker compose up -d --build maharasa-apisales

- [ ] **B2. Pantau migrasi:**

      docker compose logs -f maharasa-apisales

      Harus terlihat `Menjalankan 010_...`, `011_...`, `012_...`, lalu
      `Selesai: N migrasi dijalankan`, lalu gunicorn start. Kalau ada
      `GAGAL di ...`, file itu sudah di-rollback utuh — baca pesannya, jangan
      jalankan ulang sebelum penyebabnya jelas.
- [ ] **B3. Verifikasi:**

      docker compose exec maharasa-apisales python migrate.py --status   # 010, 011, 012 [x]
      curl -s http://localhost:8001/health/ready                         # 200

- [ ] **B4. Sync POS.** Pantau `logs/api.log` beberapa menit: tidak boleh ada
      lagi `ordertransaction_pkey` / `UniqueViolation`. Outlet yang dulu
      ditolak (mis. batch 2026-09-07) seharusnya masuk saat POS mengirim ulang.
- [ ] **B5. Ulangi query 0** (read-only): PK sekarang komposit.

## C. Deploy frontend (sync-frontend)

- [ ] **C1.** Build & jalankan image seperti biasa (Dockerfile standalone).
      Tidak ada env baru. Deploy **setelah** backend — halaman closing memanggil
      endpoint baru.
- [ ] **C2. Cek cepat:** login admin → menu *Closing* dan *Mapping Closing*
      tampil (kosong sampai consumer jalan); *Status Sync* tidak lagi menandai
      outlet yang baru sync sebagai "Perlu dicek".

## D. Menyalakan consumer closing report

Pengirim memakai `mandatory` + publisher confirms + retry otomatis ±25 jam:
selama queue kita belum terikat, pesan menunggu di outbox mereka, tidak hilang.
Jadi D boleh dikerjakan kapan saja setelah B — makin cepat, makin cepat data masuk.

- [ ] **D1.** Isi di `.env` server:

      CLOSING_EXCHANGE=closingreport_exchange
      CLOSING_ROUTING_KEY=closingreport.submitted
      CLOSING_QUEUE=syncapi.closingreport

      Broker sama dengan POS. Host, port, vhost, dan kredensial dikirim pengirim
      lewat jalur terpisah — isi `RABBITMQ_*` (termasuk `RABBITMQ_PORT` /
      `RABBITMQ_VHOST` kalau bukan default) sesuai itu.
- [ ] **D2.**

      docker compose up -d --build maharasa-closing-consumer
      docker compose logs -f maharasa-closing-consumer

      Harus muncul `CLOSING CONSUMER SIAP` — pada saat itu queue terikat dan
      pesan yang tertahan di outbox pengirim mulai masuk. `MENUNGGU: tabel
      closing report belum ada` berarti 011 belum jalan (kembali ke B). `TERPUTUS` + 404
      berarti nama exchange salah atau exchange belum dibuat pengirim.
- [ ] **D3.** Minta pengirim mengirim satu closing report uji. Di log harus ada
      `CLOSING REPORT BARU`; di dashboard laporan muncul di *Closing → Daftar laporan*.
- [ ] **D4.** Cek DLQ `syncapi.closingreport.dlq` di RabbitMQ Management — harus kosong.
      Pesan di sana = ditolak validasi; alasannya ada di
      `logs/closing-consumer.log` (`CLOSING REPORT DITOLAK`).
- [ ] **D5.** Cek log untuk `outlet belum terdaftar di api_keys` (kode outlet
      pengirim tidak cocok dengan POS walau sudah dinormalisasi) dan
      `compensation negatif` (angka janggal dari pengirim — laporan tetap masuk).
- [ ] **D6.** Admin memetakan menu di *Mapping Closing* ke produk POS-nya (untuk
      sushi: produk warna piring), lalu cek *Closing → Perbandingan POS*.
      Sebelum angka perbandingan dipakai, konfirmasi ke tim operation cara kasir
      mencatat piring kompensasi di POS (saran pengirim).

## Rollback

| Bagian | Cara mundur |
|---|---|
| Kode API / frontend | Deploy image/commit sebelumnya. |
| Consumer | `docker compose stop maharasa-closing-consumer`. Pesan menumpuk di queue, tidak hilang. |
| 011, 012 | Tabel terpisah, aman dibiarkan walau kode dimundurkan. Kode lama (sebelum 012) tidak cocok dengan skema 012 — jangan jalankan consumer versi lama. |
| 010 | **Tidak ada migrasi balik.** Kode lama tidak cocok dengan PK komposit — mundur = restore backup A1 (data sync setelah deploy ikut hilang; POS perlu mengirim ulang). |
