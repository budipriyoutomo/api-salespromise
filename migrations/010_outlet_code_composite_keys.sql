-- ============================================================
-- Migration 010: outlet_code masuk ke primary key (TODO 0.5)
-- ============================================================
--
-- MASALAH
-- -------
-- POS tiap outlet menomori TransactionID sendiri. Tapi PK `ordertransaction`
-- hanya ("TransactionID"), jadi outlet yang mengirim nomor yang sudah dipakai
-- outlet lain ditolak:
--
--   UniqueViolation: duplicate key value violates unique constraint
--   "ordertransaction_pkey"  DETAIL: Key ("TransactionID")=(138605) already exists.
--
-- Seluruh batch di-rollback dan worker POS mengulang tanpa akhir. Index unik
-- (TransactionID, outlet_code) dari migrasi 002 tidak menolong: ON CONFLICT
-- hanya menangkap index itu, PK yang lebih sempit tetap berlaku.
--
-- PERUBAHAN
-- ---------
--   ordertransaction  PK ("TransactionID")                  -> ("TransactionID", outlet_code)
--   orderdetail       + kolom outlet_code (diisi dari transaksi induknya)
--                     PK ("OrderDetailID", "TransactionID") -> (+ outlet_code)
--                     FK ("TransactionID")                  -> ("TransactionID", outlet_code)
--                     index upsert (OrderDetailID, TransactionID, ProductID) -> (+ outlet_code)
--
-- TIDAK ADA baris yang dihapus. Yang di-drop hanya constraint / index, lalu
-- langsung diganti versi yang memuat outlet_code — dalam satu transaksi
-- (migrate.py), jadi gagal di tengah = semuanya kembali seperti semula.
--
-- PRASYARAT — migrasi BERHENTI (RAISE EXCEPTION) kalau tidak terpenuhi:
--   1. Tidak ada ordertransaction.outlet_code yang NULL.
--   2. Tidak ada item yatim (orderdetail tanpa transaksi induk).
--   3. Tidak ada tabel lain yang punya FK ke ordertransaction selain orderdetail.
-- Periksa dulu di produksi dengan migrations/checks/orderdetail_outlet_collision.sql
-- (query 0 dan 4). Kalau migrasi berhenti, container tidak start (lihat migrate.py).
--
-- DURASI: backfill orderdetail meng-UPDATE setiap baris item sekali, dan
-- membangun dua index baru. Tabel terkunci selama itu — jalankan saat sepi.
--
-- Idempoten: setiap langkah memeriksa kondisi sekarang, aman dijalankan ulang.
-- ============================================================

DO $$
DECLARE
    v_jumlah     BIGINT;
    v_nama       TEXT;
    v_index      TEXT;
BEGIN
    -- --------------------------------------------------------
    -- 0. Prasyarat
    -- --------------------------------------------------------
    SELECT COUNT(*) INTO v_jumlah FROM ordertransaction WHERE outlet_code IS NULL;
    IF v_jumlah > 0 THEN
        RAISE EXCEPTION 'Migrasi 010 dibatalkan: % transaksi tanpa outlet_code. '
            'Isi outlet_code-nya dulu (keputusan manual), lalu jalankan ulang.', v_jumlah;
    END IF;

    SELECT COUNT(*) INTO v_jumlah
    FROM orderdetail d
    WHERE NOT EXISTS (
        SELECT 1 FROM ordertransaction t WHERE t."TransactionID" = d."TransactionID"
    );
    IF v_jumlah > 0 THEN
        RAISE EXCEPTION 'Migrasi 010 dibatalkan: % item orderdetail tanpa transaksi induk.', v_jumlah;
    END IF;

    SELECT string_agg(conrelid::regclass::text, ', ') INTO v_nama
    FROM pg_constraint
    WHERE contype = 'f'
      AND confrelid = 'ordertransaction'::regclass
      AND conrelid <> 'orderdetail'::regclass;
    IF v_nama IS NOT NULL THEN
        RAISE EXCEPTION 'Migrasi 010 dibatalkan: tabel % punya FK ke ordertransaction '
            'dan belum ditangani migrasi ini.', v_nama;
    END IF;

    -- --------------------------------------------------------
    -- 1. orderdetail.outlet_code + backfill dari transaksi induk
    -- --------------------------------------------------------
    ALTER TABLE orderdetail ADD COLUMN IF NOT EXISTS outlet_code VARCHAR(20);

    -- Backfill lewat TransactionID saja hanya sah kalau nomor itu belum dipakai
    -- dua outlet. Selama PK lama berlaku itu dijamin; pada eksekusi ulang
    -- (PK sudah komposit) baris NULL seharusnya tidak ada — tetap dijaga.
    SELECT COUNT(*) INTO v_jumlah
    FROM orderdetail d
    WHERE d.outlet_code IS NULL
      AND (SELECT COUNT(*) FROM ordertransaction t WHERE t."TransactionID" = d."TransactionID") > 1;
    IF v_jumlah > 0 THEN
        RAISE EXCEPTION 'Migrasi 010 dibatalkan: % item tanpa outlet_code yang TransactionID-nya '
            'dipakai lebih dari satu outlet — induknya tidak bisa ditentukan otomatis.', v_jumlah;
    END IF;

    UPDATE orderdetail d
    SET outlet_code = t.outlet_code
    FROM ordertransaction t
    WHERE t."TransactionID" = d."TransactionID"
      AND d.outlet_code IS NULL;
    GET DIAGNOSTICS v_jumlah = ROW_COUNT;
    RAISE NOTICE 'orderdetail.outlet_code diisi untuk % baris.', v_jumlah;

    ALTER TABLE ordertransaction ALTER COLUMN outlet_code SET NOT NULL;
    ALTER TABLE orderdetail ALTER COLUMN outlet_code SET NOT NULL;

    -- --------------------------------------------------------
    -- 2. Lepas FK lama orderdetail("TransactionID") -> ordertransaction
    --    (harus sebelum PK ordertransaction diganti; FK bergantung padanya)
    -- --------------------------------------------------------
    FOR v_nama IN
        SELECT conname
        FROM pg_constraint
        WHERE contype = 'f'
          AND conrelid = 'orderdetail'::regclass
          AND confrelid = 'ordertransaction'::regclass
          AND array_length(conkey, 1) = 1
    LOOP
        EXECUTE format('ALTER TABLE orderdetail DROP CONSTRAINT %I', v_nama);
        RAISE NOTICE 'FK lama % di-drop.', v_nama;
    END LOOP;

    -- --------------------------------------------------------
    -- 3. PK ordertransaction -> ("TransactionID", outlet_code)
    -- --------------------------------------------------------
    IF (
        SELECT array_agg(a.attname::text ORDER BY k.ord)
        FROM pg_constraint c
        CROSS JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord)
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
        WHERE c.conrelid = 'ordertransaction'::regclass AND c.contype = 'p'
    ) IS DISTINCT FROM ARRAY['TransactionID', 'outlet_code'] THEN

        SELECT conname INTO v_nama
        FROM pg_constraint
        WHERE conrelid = 'ordertransaction'::regclass AND contype = 'p';
        IF v_nama IS NOT NULL THEN
            EXECUTE format('ALTER TABLE ordertransaction DROP CONSTRAINT %I', v_nama);
        END IF;

        -- Pakai ulang index unik dari migrasi 002 kalau ada (nama apa pun),
        -- supaya tidak ada dua index identik yang memperlambat setiap INSERT.
        SELECT ci.relname INTO v_index
        FROM pg_index i
        JOIN pg_class ci ON ci.oid = i.indexrelid
        WHERE i.indrelid = 'ordertransaction'::regclass
          AND i.indisunique
          AND i.indpred IS NULL
          AND i.indexprs IS NULL
          AND NOT EXISTS (SELECT 1 FROM pg_constraint c WHERE c.conindid = i.indexrelid)
          AND (
              SELECT array_agg(a.attname::text ORDER BY k.ord)
              FROM unnest(i.indkey) WITH ORDINALITY AS k(attnum, ord)
              JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum
          ) = ARRAY['TransactionID', 'outlet_code']
        LIMIT 1;

        IF v_index IS NOT NULL THEN
            EXECUTE format(
                'ALTER TABLE ordertransaction ADD CONSTRAINT ordertransaction_pkey PRIMARY KEY USING INDEX %I',
                v_index
            );
            RAISE NOTICE 'PK ordertransaction dibuat dari index % yang sudah ada.', v_index;
        ELSE
            ALTER TABLE ordertransaction
                ADD CONSTRAINT ordertransaction_pkey PRIMARY KEY ("TransactionID", outlet_code);
            RAISE NOTICE 'PK ordertransaction dibuat baru.';
        END IF;
    ELSE
        RAISE NOTICE 'PK ordertransaction sudah ("TransactionID", outlet_code) — dilewati.';
    END IF;

    -- Index unik lain yang persis sama dengan PK sekarang mubazir.
    FOR v_index IN
        SELECT ci.relname
        FROM pg_index i
        JOIN pg_class ci ON ci.oid = i.indexrelid
        WHERE i.indrelid = 'ordertransaction'::regclass
          AND i.indisunique
          AND NOT i.indisprimary
          AND i.indpred IS NULL
          AND i.indexprs IS NULL
          AND NOT EXISTS (SELECT 1 FROM pg_constraint c WHERE c.conindid = i.indexrelid)
          AND (
              SELECT array_agg(a.attname::text ORDER BY k.ord)
              FROM unnest(i.indkey) WITH ORDINALITY AS k(attnum, ord)
              JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum
          ) = ARRAY['TransactionID', 'outlet_code']
    LOOP
        EXECUTE format('DROP INDEX %I', v_index);
        RAISE NOTICE 'Index % di-drop — sudah diwakili PK.', v_index;
    END LOOP;

    -- --------------------------------------------------------
    -- 4. PK orderdetail -> ("OrderDetailID", "TransactionID", outlet_code)
    -- --------------------------------------------------------
    IF (
        SELECT array_agg(a.attname::text ORDER BY k.ord)
        FROM pg_constraint c
        CROSS JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord)
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
        WHERE c.conrelid = 'orderdetail'::regclass AND c.contype = 'p'
    ) IS DISTINCT FROM ARRAY['OrderDetailID', 'TransactionID', 'outlet_code'] THEN

        SELECT conname INTO v_nama
        FROM pg_constraint
        WHERE conrelid = 'orderdetail'::regclass AND contype = 'p';
        IF v_nama IS NOT NULL THEN
            EXECUTE format('ALTER TABLE orderdetail DROP CONSTRAINT %I', v_nama);
        END IF;

        ALTER TABLE orderdetail
            ADD CONSTRAINT orderdetail_pkey PRIMARY KEY ("OrderDetailID", "TransactionID", outlet_code);
        RAISE NOTICE 'PK orderdetail dibuat ("OrderDetailID", "TransactionID", outlet_code).';
    ELSE
        RAISE NOTICE 'PK orderdetail sudah memuat outlet_code — dilewati.';
    END IF;

    -- --------------------------------------------------------
    -- 5. FK komposit orderdetail -> ordertransaction
    -- --------------------------------------------------------
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'orderdetail'::regclass
          AND conname = 'orderdetail_transaction_outlet_fkey'
    ) THEN
        ALTER TABLE orderdetail
            ADD CONSTRAINT orderdetail_transaction_outlet_fkey
            FOREIGN KEY ("TransactionID", outlet_code)
            REFERENCES ordertransaction ("TransactionID", outlet_code);
        RAISE NOTICE 'FK komposit orderdetail -> ordertransaction dibuat.';
    END IF;

    -- --------------------------------------------------------
    -- 6. Index upsert item (ON CONFLICT di sync_sales) + outlet_code
    -- --------------------------------------------------------
    IF NOT EXISTS (
        SELECT 1
        FROM pg_index i
        WHERE i.indrelid = 'orderdetail'::regclass
          AND i.indisunique
          AND i.indpred IS NULL
          AND (
              SELECT array_agg(a.attname::text ORDER BY a.attname::text)
              FROM unnest(i.indkey) AS k(attnum)
              JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum
          ) = ARRAY['OrderDetailID', 'ProductID', 'TransactionID', 'outlet_code']
    ) THEN
        CREATE UNIQUE INDEX uq_orderdetail_detail_txn_product_outlet
            ON orderdetail ("OrderDetailID", "TransactionID", "ProductID", outlet_code);
        RAISE NOTICE 'Index unik upsert item + outlet_code dibuat.';
    END IF;

    -- Index lama tanpa outlet_code akan menolak dua outlet dengan nomor sama.
    FOR v_index, v_nama IN
        SELECT ci.relname, c.conname
        FROM pg_index i
        JOIN pg_class ci ON ci.oid = i.indexrelid
        LEFT JOIN pg_constraint c ON c.conindid = i.indexrelid AND c.conrelid = i.indrelid
        WHERE i.indrelid = 'orderdetail'::regclass
          AND i.indisunique
          AND NOT i.indisprimary
          AND (
              SELECT array_agg(a.attname::text ORDER BY a.attname::text)
              FROM unnest(i.indkey) AS k(attnum)
              JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum
          ) = ARRAY['OrderDetailID', 'ProductID', 'TransactionID']
    LOOP
        IF v_nama IS NOT NULL THEN
            EXECUTE format('ALTER TABLE orderdetail DROP CONSTRAINT %I', v_nama);
        ELSE
            EXECUTE format('DROP INDEX %I', v_index);
        END IF;
        RAISE NOTICE 'Index unik lama % (tanpa outlet_code) di-drop.', v_index;
    END LOOP;
END $$;
