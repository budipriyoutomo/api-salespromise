# Rencana Perbaikan: Kirim Rekap Closing ke API Eksternal

| | |
|---|---|
| Repo | `api-salespromise` (`935a62b`), `frontendsales` (`b9ebbc2`) |
| Tanggal | 4 November 2026 |
| Status | Backend langkah 1–9 dan frontend selesai di kode (belum commit, belum deploy). Aturan A/B/C disetujui. Kontrak revisi 2 belum dikirim ke pemilik API. |
| Pembaruan TODO | Backend Fase 8 (usul item 8.12), frontend Fase 12 (usul item 12.8) |

## 1. Ringkasan

Rekap saat ini menghitung penjualan colorplate dua kali, karena produk colorplate di POS ikut terkirim padahal angkanya sudah ada di `sold` closing. Rencana ini memperbaiki hal itu, memakai kode master `products` untuk item non-colorplate, dan menambah config per brand untuk kirim tanpa closing.

**Hasil uji:** kode inti di dokumen ini sudah dicoba di salinan terpisah. 1.335 unit test lulus, termasuk 8 test baru, setelah helper dan payload test lama disesuaikan seperti langkah 8. Yang belum diuji: skema/route API (langkah 6-7), frontend, migrasi 019, dan test integrasi Postgres.

## 2. Keputusan

| # | Keputusan |
|---|---|
| 1 | `totalSold` tetap `colorplateSold + posQty`. `adjustment` dan `compensation` tidak ikut, karena perlakuannya berbeda dan sudah punya field sendiri. |
| 2 | Item non-colorplate memakai identitas master `products`, bukan ProductID POS. |
| 3 | Kirim tanpa closing diatur per brand lewat config. |

Tiga aturan tambahan dari usulan rencana ini perlu Anda konfirmasi:

| # | Aturan yang diusulkan | Alasan |
|---|---|---|
| A | Config disimpan sebagai kolom `brands.requires_closing`, default `TRUE`. | Brand sudah punya tabel dan halaman admin. Perilaku lama tetap berlaku sampai brand diubah. Outlet tanpa brand tetap wajib closing. |
| B | Produk tanpa master aktif atau tanpa `product_code` **memblokir** kiriman. | Kalau dilewati, angkanya hilang tanpa peringatan. |
| C | Brand tanpa syarat closing tetap **diblokir** kalau produk colorplate terjual tanpa closing. | Kalau tidak, penjualan colorplate hilang dari rekap tanpa peringatan. |

## 3. Aturan rekap setelah perbaikan

```text
Baris POS (void dibuang)
├── group COLORPLATE aktif, atau ProductID punya konversi aktif
│     → TIDAK dikirim sebagai item; sudah terwakili oleh `sold` menu closing
├── ProductID dipetakan ke menu closing
│     → masuk `posQty` menu itu
└── sisanya (non-colorplate)
      → item `pos_only` memakai kode master; beberapa ProductID ke satu master dijumlah
```

Contoh: RED 10, Promo 3 (konversi RED), Ocha 2, closing Salmon 6 dan Tuna 4.

| | Sebelum | Sesudah |
|---|---|---|
| Item terkirim | Salmon 6, Tuna 4, Ocha 2, Promo 3, RED 10 | Salmon 6, Tuna 4, Ocha 2 |
| Total | 25 | **12** |

### Kapan kiriman diblokir

| Kondisi | Field | Status |
|---|---|---|
| Menu belum dipetakan dan tidak bertanda `not_in_pos` | `menu_belum_dipetakan` | Sudah ada |
| ProductID dipetakan ke lebih dari satu menu | `produk_dobel` | Sudah ada |
| Produk colorplate atau berkonversi dipetakan ke menu closing | `produk_colorplate_dipetakan` | Baru |
| Produk non-colorplate belum punya master aktif | `produk_belum_master` | Baru |
| Tanpa closing, tetapi produk colorplate terjual | `colorplate_tanpa_closing` | Baru |

## 4. Pemeriksaan sebelum mulai

Jalankan query read-only ini di produksi. Hasilnya menentukan apakah masalah di bagian 7 perlu dikerjakan lebih dulu.

```sql
-- ProductID yang dipakai untuk nama/group berbeda antar-outlet
SELECT "ProductID",
       COUNT(DISTINCT outlet_code) AS jumlah_outlet,
       COUNT(DISTINCT UPPER(TRIM("Name"))) AS jumlah_nama,
       ARRAY_AGG(DISTINCT outlet_code || ': ' || TRIM("Name")) AS contoh
FROM orderdetail
GROUP BY "ProductID"
HAVING COUNT(DISTINCT UPPER(TRIM("Name"))) > 1
ORDER BY jumlah_nama DESC
LIMIT 50;
```

Query ini belum dijalankan ke database mana pun.

## 5. Langkah backend

Kerjakan dengan TDD: tulis test di langkah 8 dulu.

### Langkah 1: Migrasi `migrations/019_brand_requires_closing.sql`

```sql
-- Migration 019: Syarat closing untuk kirim rekap, per brand.
-- TRUE (default): perilaku lama. FALSE: outlet brand ini boleh kirim tanpa closing.
-- Hanya ADD COLUMN. Idempotent: aman dijalankan ulang.
ALTER TABLE brands ADD COLUMN IF NOT EXISTS requires_closing BOOLEAN NOT NULL DEFAULT TRUE;
```

### Langkah 2: Model `app/models/brand.py`

```python
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, text

# di class Brand, setelah is_active
# False = outlet brand ini boleh kirim rekap tanpa closing report (migrasi 019).
requires_closing = Column(Boolean, nullable=False, default=True, server_default=text("true"))
```

### Langkah 3: Aturan colorplate bersama, `app/services/colorplate_publish_service.py`

Pindahkan penentuan colorplate ke satu tempat supaya publish dan export tidak bisa berbeda aturan.

```python
@dataclass(frozen=True)
class AturanColorplate:
    """Satu sumber aturan: baris POS mana yang masuk hitungan colorplate."""

    group_aktif: bool
    konversi: dict

    def termasuk(self, product_id: int, product_group: str | None) -> bool:
        if self.group_aktif and product_group_service.normalize_product_group(product_group) == SalesService.COLORPLATE:
            return True
        return product_id in self.konversi


def aturan_colorplate(db) -> AturanColorplate:
    return AturanColorplate(
        group_aktif=SalesService.COLORPLATE
        in {product_group_service.normalize_product_group(g) for g in product_group_service.get_active_groups(db)},
        konversi=product_menu_service.get_active_conversions(db),
    )
```

Lalu ubah awal `rekap_colorplate`:

```python
def rekap_colorplate(db, outlet=None, start_date=None, end_date=None) -> list[RekapWarna]:
    aturan = aturan_colorplate(db)
    colorplate_aktif, konversi = aturan.group_aktif, aturan.konversi
    # sisanya tidak berubah
```

### Langkah 4: Export, `app/services/closing_export_service.py`

Tambahkan import:

```python
from app.models.brand import Brand, OutletBrandMapping
from app.models.product import Product, ProductPosMapping
from app.models.sales import Sales
from app.models.sales_items import SalesItems
from app.services import closing_export_client, closing_report_service, colorplate_publish_service
from app.services.sales_service import SalesService, item_join
```

Tambahkan exception dan perluas `Blokir`:

```python
class TidakAdaPenjualan(Exception):
    """Brand boleh kirim tanpa closing, tetapi tidak ada penjualan di tanggal itu."""


@dataclass
class ProdukPos:
    product_id: int
    product_name: str | None


@dataclass
class Blokir:
    menu_belum_dipetakan: list[MenuBelumDipetakan] = field(default_factory=list)
    produk_dobel: list[ProdukDobel] = field(default_factory=list)
    # Produk colorplate / berkonversi dipetakan ke menu: qty-nya sudah ada di `sold`.
    produk_colorplate_dipetakan: list[ProdukDobel] = field(default_factory=list)
    # Produk non-colorplate tanpa mapping aktif ke master `products`.
    produk_belum_master: list[ProdukPos] = field(default_factory=list)
    # Kirim tanpa closing, tetapi produk colorplate terjual: `sold`-nya belum ada.
    colorplate_tanpa_closing: list[ProdukPos] = field(default_factory=list)

    def __bool__(self):
        return bool(
            self.menu_belum_dipetakan
            or self.produk_dobel
            or self.produk_colorplate_dipetakan
            or self.produk_belum_master
            or self.colorplate_tanpa_closing
        )
```

Ganti `_item`, `susun_isi`, dan hapus `_baris_pasangan` dengan kode berikut. `periksa_blokir` dan `hash_isi` tidak berubah.

```python
def _item_menu(baris) -> dict:
    colorplate = _angka(baris.sold)
    pos = _angka(baris.pos_qty)
    return {
        "source": "closing",
        "menuId": str(baris.menu_id),
        "menuCode": baris.menu_code,
        "menuName": baris.menu_name,
        "productId": None,
        "productCode": None,
        "productName": None,
        "colorplateSold": colorplate,
        "posQty": pos,
        "totalSold": _angka(colorplate + pos),
        "waste": _angka(baris.waste),
        "adjustment": _angka(baris.adjustment),
        "compensation": _angka(baris.compensation),
    }


def _item_produk(produk: Product, qty) -> dict:
    pos = _angka(qty)
    return {
        "source": "pos_only",
        "menuId": None,
        "menuCode": None,
        "menuName": None,
        "productId": produk.code,
        "productCode": produk.product_code,
        "productName": produk.name,
        "colorplateSold": 0,
        "posQty": pos,
        "totalSold": pos,
        "waste": 0,
        "adjustment": 0,
        "compensation": 0,
    }


@dataclass
class RekapPasangan:
    outlet_code: str
    production_date: date
    baris_menu: list = field(default_factory=list)
    items_produk: list = field(default_factory=list)
    blokir: Blokir = field(default_factory=Blokir)


def _penjualan_per_group(db, pasangan: set) -> list:
    """Qty POS per (outlet, tanggal, ProductID, group). Void tidak dihitung."""
    if not pasangan:
        return []
    tanggal = [d for _, d in pasangan]
    grup = SalesService._normalized_product_group()
    query = (
        db.query(
            Sales.outlet_code,
            Sales.sale_date,
            SalesItems.product_id,
            grup.label("grup"),
            func.sum(SalesItems.qty).label("qty"),
            func.max(func.trim(SalesItems.product_name)).label("nama"),
        )
        .join(Sales, item_join)
        .filter(
            Sales.outlet_code.in_(sorted({o for o, _ in pasangan})),
            Sales.sale_date >= min(tanggal),
            Sales.sale_date <= max(tanggal),
        )
    )
    query = SalesService._active_sales(query, include_deleted=False)
    rows = query.group_by(Sales.outlet_code, Sales.sale_date, SalesItems.product_id, grup).all()
    return [r for r in rows if (r.outlet_code, r.sale_date) in pasangan]


def _master_per_pos(db, outlets) -> dict:
    """(outlet, ProductID POS) → Product, hanya mapping & produk aktif."""
    rows = (
        db.query(ProductPosMapping.outlet_code, ProductPosMapping.pos_product_id, Product)
        .join(Product, Product.id == ProductPosMapping.product_id)
        .filter(
            ProductPosMapping.outlet_code.in_(sorted(set(outlets))),
            ProductPosMapping.is_active.is_(True),
            Product.is_active.is_(True),
        )
        .all()
    )
    return {(o, pid): produk for o, pid, produk in rows}


def _outlet_tanpa_syarat_closing(db, outlets=None) -> set:
    query = (
        db.query(OutletBrandMapping.outlet_code)
        .join(Brand, Brand.id == OutletBrandMapping.brand_id)
        .filter(Brand.requires_closing.is_(False))
    )
    if outlets is not None:
        query = query.filter(OutletBrandMapping.outlet_code.in_(sorted(set(outlets))))
    return {o for (o,) in query.all()}


def _pasangan_pos(db, outlets, start_date, end_date) -> set:
    """Outlet × tanggal yang punya penjualan, untuk brand tanpa syarat closing."""
    if not outlets or start_date is None or end_date is None:
        return set()
    query = (
        db.query(Sales.outlet_code, Sales.sale_date)
        .filter(Sales.outlet_code.in_(sorted(outlets)), Sales.sale_date >= start_date, Sales.sale_date <= end_date)
        .distinct()
    )
    return {(o, d) for o, d in SalesService._active_sales(query, include_deleted=False).all()}


def susun_rekap(db, outlet=None, start_date=None, end_date=None) -> list[RekapPasangan]:
    """Rekap per outlet × tanggal: menu closing + produk non-colorplate di master."""
    menu_per_pasangan: dict = {}
    for b in closing_report_service.compare_with_pos(
        db, outlet=outlet, start_date=start_date, end_date=end_date, include_deleted=False
    ):
        if b.menu_id is not None:
            menu_per_pasangan.setdefault((b.outlet_code, b.production_date), []).append(b)

    bebas = _outlet_tanpa_syarat_closing(db, [outlet] if outlet else None)
    pasangan = set(menu_per_pasangan) | _pasangan_pos(db, bebas, start_date, end_date)
    if not pasangan:
        return []

    aturan = colorplate_publish_service.aturan_colorplate(db)
    master = _master_per_pos(db, {o for o, _ in pasangan})
    rekap = {
        k: RekapPasangan(k[0], k[1], menu_per_pasangan.get(k, []), blokir=periksa_blokir(menu_per_pasangan.get(k, [])))
        for k in pasangan
    }

    tampil = {(k, p.product_id) for k, baris in menu_per_pasangan.items() for b in baris for p in b.products}
    colorplate: dict = {}
    produk: dict = {}
    belum_master: dict = {}
    for r in _penjualan_per_group(db, pasangan):
        k = (r.outlet_code, r.sale_date)
        qty = float(r.qty or 0)
        if aturan.termasuk(r.product_id, r.grup):
            colorplate.setdefault(k, {})[r.product_id] = r.nama
            continue
        if (k, r.product_id) in tampil or not qty:
            continue
        master_produk = master.get((r.outlet_code, r.product_id))
        if master_produk is None or not master_produk.product_code:
            belum_master.setdefault(k, {})[r.product_id] = r.nama
            continue
        # Dua ProductID POS bisa menunjuk satu produk master: qty dijumlah.
        total = produk.setdefault(k, {}).setdefault(master_produk.id, [master_produk, 0.0])
        total[1] += qty

    for k, isi in rekap.items():
        isi.items_produk = sorted(
            (_item_produk(p, qty) for p, qty in produk.get(k, {}).values()),
            key=lambda i: (i["productName"] or "", i["productCode"] or ""),
        )
        isi.blokir.produk_belum_master = [ProdukPos(pid, n) for pid, n in sorted(belum_master.get(k, {}).items())]
        if isi.baris_menu:
            per_produk: dict = {}
            for b in isi.baris_menu:
                for p in b.products:
                    if p.product_id in colorplate.get(k, {}) or p.product_id in aturan.konversi:
                        per_produk.setdefault(p.product_id, (p.product_name, []))[1].append(
                            b.menu_code or b.menu_name or str(b.menu_id)
                        )
            isi.blokir.produk_colorplate_dipetakan = [
                ProdukDobel(pid, nama, sorted(menus)) for pid, (nama, menus) in sorted(per_produk.items())
            ]
        else:
            isi.blokir.colorplate_tanpa_closing = [ProdukPos(pid, n) for pid, n in sorted(colorplate.get(k, {}).items())]

    return sorted(rekap.values(), key=lambda r: (r.production_date, r.outlet_code))


def susun_isi(rekap: RekapPasangan) -> dict:
    """Bagian payload yang di-hash — tanpa messageId / sentAt / sequence."""
    return {
        "outlet": {"code": rekap.outlet_code},
        "productionDate": rekap.production_date.isoformat(),
        "items": [_item_menu(b) for b in rekap.baris_menu] + rekap.items_produk,
    }
```

Ubah `kirim()`:

```python
daftar = susun_rekap(db, outlet=outlet_code, start_date=production_date, end_date=production_date)
if not daftar:
    if _outlet_tanpa_syarat_closing(db, [outlet_code]):
        raise TidakAdaPenjualan()
    raise TidakAdaClosing()
rekap = daftar[0]
if rekap.blokir:
    raise Diblokir(rekap.blokir)

# ... pemeriksaan kiriman berjalan tetap sama ...
isi = susun_isi(rekap)
```

Ubah `status_pasangan()`:

```python
per_pasangan = {
    (r.outlet_code, r.production_date): r
    for r in susun_rekap(db, outlet=outlet, start_date=start_date, end_date=end_date)
}
if not per_pasangan:
    return []

# ... query logs tetap sama, `in_` tetap memakai per_pasangan ...

for (outlet_code, production_date), rekap in per_pasangan.items():
    # ...
    isi = susun_isi(rekap)
    blokir = rekap.blokir
```

Tambahkan juga ke `StatusPasangan` dan isinya:

```python
has_closing=bool(rekap.baris_menu),
produk_colorplate_dipetakan=blokir.produk_colorplate_dipetakan,
produk_belum_master=blokir.produk_belum_master,
colorplate_tanpa_closing=blokir.colorplate_tanpa_closing,
```

Perbarui juga docstring di awal file. `compare_with_pos` **tidak diubah**, karena tampilan perbandingan `/closing` memang perlu melihat data POS apa adanya.

### Langkah 5: Brand service dan API

- `brand_service.update_brand`: tambahkan parameter `requires_closing: bool | None = None`.
- `brand_service.create_brand`: tambahkan parameter `requires_closing: bool = True`.
- `app/schemas/brand_schema.py`:
  - `BrandResponse` dan `CreateBrandRequest`: `requires_closing: bool = True`.
  - `UpdateBrandRequest`: `requires_closing: Optional[bool] = None`, dan sertakan di `minimal_satu_field`.
- `app/routes/brand_routes.py`: teruskan field ini, lalu tambahkan ke log perubahan.

### Langkah 6: Skema `app/schemas/closing_schema.py`

```python
class ClosingExportPosProduct(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: int
    product_name: Optional[str] = None


# tambahkan ke ClosingExportStatus
has_closing: bool
produk_colorplate_dipetakan: List[ClosingExportDuplicateProduct]
produk_belum_master: List[ClosingExportPosProduct]
colorplate_tanpa_closing: List[ClosingExportPosProduct]
```

### Langkah 7: Route `app/routes/closing_routes.py`

Di `send_closing_export`:

- Tangkap `TidakAdaPenjualan` sebagai 404 dengan pesan "Tidak ada penjualan untuk outlet dan tanggal ini."
- Tambahkan tiga daftar blokir baru ke `detail` respons 422, dan ubah `message` agar tidak hanya menyebut mapping menu.
- Perbarui docstring `closing_export_status`, karena daftar kini juga memuat tanggal tanpa closing untuk brand yang diizinkan.

### Langkah 8: Test

Di `tests/unit/test_closing_export_service.py`:

1. Helper `siapkan()` perlu membuat master untuk produk non-colorplate (`300001`).
2. Payload yang diharapkan pada `test_isi_sesuai_kontrak` memakai `productId` string dan `productCode`.
3. Helper `jual()` di `test_routes_closing.py` perlu parameter `product_group`, karena sekarang selalu `FOOD` dan itulah sebabnya masalah ini lolos.

Test baru berikut sudah lulus pada prototipe. Rapikan dan pindahkan ke `test_closing_export_service.py`:

```python
from datetime import date
from app.config import settings
from app.models.brand import Brand, OutletBrandMapping
from app.models.closing_report import ClosingMenu
from app.models.product import Product, ProductPosMapping
from app.models.product_group_mapping import ProductGroupMapping
from app.models.product_menu_mapping import ProductMenuMapping, ProductMenuColorplate
from app.services import closing_export_service as s
from tests.unit.test_routes_closing import HARI_INI, item, kirim_closing, petakan
from tests.conftest import make_sale_row, make_item_row
O="OUTLET_001"
def jual(db,t,pid,q,nama,g,o=O):
    db.add(make_sale_row(transaction_id=t,outlet_code=o,sale_date=HARI_INI,deleted=0))
    db.add(make_item_row(order_detail_id=1,transaction_id=t,outlet_code=o,sale_date=HARI_INI,product_id=pid,product_group=g,product_name=nama,qty=q)); db.commit()
def master(db,code,nama,*pos):
    p=Product(code=code,product_code=code,name=nama,price=0); db.add(p); db.flush()
    for o,pid in pos: db.add(ProductPosMapping(product_id=p.id,outlet_code=o,pos_product_id=pid))
    db.commit()
def setup(db):
    if not db.query(ProductGroupMapping).filter_by(product_group="COLORPLATE").first():
        db.add(ProductGroupMapping(product_group="COLORPLATE",is_active=True))
    m=ProductMenuMapping(product_id=700,is_active=True); db.add(m); db.flush()
    db.add(ProductMenuColorplate(menu_mapping_id=m.id,platecolor="RED",multiplier=2,is_active=True)); db.commit()
def base(db):
    setup(db)
    kirim_closing(db,outlet=O,items=[item(menu_code="SU-001",menu_name="Salmon",sold=6),item(menu_code="SU-002",menu_name="Tuna",sold=4)])
    jual(db,1,500,10,"RED","COLORPLATE"); jual(db,2,300,2,"Ocha","DRINK"); jual(db,3,700,3,"Promo","PROMO")
def flag(db):
    for m in db.query(ClosingMenu): m.not_in_pos=True
    db.commit()
def r(db): return s.susun_rekap(db,outlet=O,start_date=HARI_INI,end_date=HARI_INI)
def total(x): return sum(i["totalSold"] for i in s.susun_isi(x)["items"])
def test_total_12(db_session):
    base(db_session); flag(db_session); master(db_session,"M-OCHA","Ocha Master",(O,300))
    x=r(db_session)[0]; assert not x.blokir and total(x)==12
    i=s.susun_isi(x)["items"][-1]; assert (i["productId"],i["productCode"],i["productName"],i["posQty"])==("M-OCHA","M-OCHA","Ocha Master",2)
def test_belum_master(db_session):
    base(db_session); flag(db_session); x=r(db_session)[0]
    assert [p.product_id for p in x.blokir.produk_belum_master]==[300]
def test_colorplate_dipetakan(db_session):
    base(db_session); flag(db_session); master(db_session,"M-OCHA","Ocha",(O,300))
    m=db_session.query(ClosingMenu).filter_by(menu_code="SU-001").one(); m.not_in_pos=False; db_session.commit()
    petakan(db_session,"SU-001",500); x=r(db_session)[0]
    assert [p.product_id for p in x.blokir.produk_colorplate_dipetakan]==[500]
def test_gabung_master(db_session):
    base(db_session); flag(db_session); jual(db_session,4,301,5,"Ocha2","DRINK"); master(db_session,"M-OCHA","Ocha",(O,300),(O,301))
    x=r(db_session)[0]; assert len(x.items_produk)==1 and x.items_produk[0]["posQty"]==7
def bebas(db,req):
    b=Brand(code="B",name="B",requires_closing=req); db.add(b); db.flush(); db.add(OutletBrandMapping(outlet_code=O,brand_id=b.id)); db.commit()
def test_tanpa_closing_config_true(db_session):
    setup(db_session); bebas(db_session,True); jual(db_session,2,300,2,"Ocha","DRINK"); master(db_session,"M","Ocha",(O,300))
    assert r(db_session)==[]
def test_tanpa_closing_config_false(db_session):
    setup(db_session); bebas(db_session,False); jual(db_session,2,300,2,"Ocha","DRINK"); master(db_session,"M","Ocha",(O,300))
    x=r(db_session)[0]; assert not x.blokir and total(x)==2
    st=s.status_pasangan(db_session,start_date=HARI_INI,end_date=HARI_INI); assert st[0].can_send
def test_tanpa_closing_ada_plate_blokir(db_session):
    setup(db_session); bebas(db_session,False); jual(db_session,1,500,10,"RED","COLORPLATE")
    x=r(db_session)[0]; assert [p.product_id for p in x.blokir.colorplate_tanpa_closing]==[500]
def test_void(db_session):
    setup(db_session); bebas(db_session,False)
    db_session.add(make_sale_row(transaction_id=9,outlet_code=O,sale_date=HARI_INI,deleted=1)); db_session.add(make_item_row(order_detail_id=1,transaction_id=9,outlet_code=O,sale_date=HARI_INI,product_id=300,product_group="DRINK",product_name="O",qty=4)); db_session.commit()
    assert r(db_session)==[]
```

Tambahkan juga:

- Test route: 404 `TidakAdaPenjualan`, isi 422 blokir baru, PATCH `requires_closing`.
- `test_migrate.py` dan test integrasi migrasi 019, mengikuti pola migrasi 018.
- Publish colorplate tetap menghasilkan event yang sama setelah refactor langkah 3.

### Langkah 9: Dokumen

Perbarui `docs/usulan-kontrak-kirim-closing.md`, lalu **kirim ulang ke pemilik API** karena kontraknya berubah:

| Field | Sebelum | Sesudah |
|---|---|---|
| `productId` | Integer ProductID POS | String `products.code` |
| `productCode` | Tidak ada | `products.product_code` |
| `productName` | Nama dari POS | `products.name` |
| `pos_only` | Semua produk POS di luar menu | Hanya produk non-colorplate |

Jelaskan juga bahwa satu kiriman bisa berisi `pos_only` saja untuk brand tanpa syarat closing. Pertanyaan no. 5 di kontrak juga perlu diperbarui.

## 6. Langkah frontend

1. Jalankan `npm run gen:api` setelah backend berjalan.
2. **`src/components/admin/brands-view.tsx`:** tambahkan switch "Wajib closing report" pada form brand dan kirim `requires_closing` lewat PATCH.
3. **`src/components/closing/closing-export-panel.tsx`:**
   - `AlasanBlokir`: tampilkan tiga alasan baru, dengan tautan ke `/closing-menu` untuk mapping colorplate dan `/produk` untuk produk belum master.
   - Pasangan dengan `has_closing: false`: tampilkan penanda "Tanpa closing".
   - Teks "Cara kerja kirim": jelaskan colorplate tidak dihitung dari POS dan produk lain wajib punya master.
   - Keadaan kosong: ganti "Belum ada closing report" menjadi "Belum ada data untuk dikirim".
4. **`e2e/mock-backend.mjs`, test panel, dan test brand:** sesuaikan dengan field baru.
5. **Tab perbandingan `/closing`:** RED tetap tampil sebagai "hanya POS" di sana, sehingga totalnya bisa berbeda dari Total Sold di tab kirim. Tambahkan catatan singkat di layar supaya admin tidak mengira ada kesalahan.

## 7. Risiko yang belum diselesaikan rencana ini

| Risiko | Dampak | Tindak lanjut |
|---|---|---|
| **Mapping closing dan konversi warna berlaku global**, padahal ProductID dinomori per outlet (`ProductPosMapping`). | Kalau nomornya berbeda antar-outlet, qty bisa masuk ke menu yang salah atau produk bisa keliru dianggap colorplate. | Lihat hasil query bagian 4. Kalau ada bentrok, jadikan mapping per outlet sebagai pekerjaan terpisah sebelum deploy. |
| **`products.code` unik global**, sedangkan impor memakai ProductID POS sebagai kode. | ProductID sama di dua brand hanya bisa jadi satu produk impor. Brand kedua perlu produk manual dengan kode lain, atau kirimannya terblokir. | Periksa kandidat berstatus `bentrok` di halaman Produk. |
| **Group `COLORPLATE` dinonaktifkan.** | Mengikuti aturan publish, RED dianggap non-colorplate dan akan memblokir sebagai produk belum master. | Blokir ini mencegah angka salah terkirim, tetapi perlu diketahui admin. |
| **Aturan memakai konfigurasi saat ini, bukan histori.** | Mengubah konversi bisa membuat tanggal lama berstatus "Perlu kirim ulang". | Perilaku ini aman, tetapi perlu diinformasikan ke admin. |
| **`not_in_pos` berlaku global per menu.** | Menu tidak bisa berbeda status antar-outlet. | Perlu dikerjakan hanya kalau kebutuhan itu benar-benar ada. |

## 8. Urutan deploy

1. Jalankan query bagian 4 dan putuskan tindak lanjutnya.
2. Dapatkan konfirmasi pemilik API atas kontrak baru.
3. Lengkapi master `products` untuk produk non-colorplate, karena tanpa ini kiriman akan terblokir.
4. Set `requires_closing = FALSE` hanya untuk brand tanpa colorplate.
5. Deploy backend (migrasi 016, 018, dan 019 berjalan saat container start), lalu frontend.
6. Uji satu outlet dan satu tanggal ke staging. Bandingkan Total Sold dengan perhitungan manual sebelum dibuka untuk semua outlet.

## 9. Checklist selesai

- [x] Skenario contoh menghasilkan total 12.
- [x] Produk colorplate dan berkonversi tidak muncul sebagai `pos_only`.
- [x] Menu closing tidak bisa terkirim dengan qty produk colorplate di `posQty`.
- [x] Item `pos_only` memakai kode master, dan dua ProductID ke satu master digabung.
- [x] `requires_closing = TRUE` tetap menolak kiriman tanpa closing.
- [x] `requires_closing = FALSE` bisa mengirim dan tampil di status.
- [x] Event publish colorplate tidak berubah.
- [x] Unit test, test integrasi Postgres, lint, dan test frontend lulus. (Backend: 1.359 unit + 38 integrasi di `sync_test` lulus, ruff bersih. Frontend: 404 unit, typecheck, lint, prettier, 9 E2E closing lulus.)
- [ ] Kontrak baru sudah dikonfirmasi pemilik API.
- [x] TODO backend dan frontend sudah diperbarui (backend 8.12, frontend 12.8).
## 10. Todo migrasi tanpa menyentuh data produksi

Hasil pemeriksaan (4 November 2026, read-only, tidak ada koneksi ke database):

| Temuan | Arti untuk produksi |
|---|---|
| `Dockerfile` CMD menjalankan `python migrate.py` sebelum gunicorn, dan `COPY . .` membawa folder `migrations/` ke image. | Begitu image baru di-build dan container produksi di-start, 019 **langsung jalan otomatis**. Tidak ada flag untuk melewatinya. |
| Restart container lama (image lama) tidak membawa file 019. | Aman. Yang memicu migrasi hanya build + deploy image baru. |
| `migrate.py` melewati file yang sudah tercatat di `schema_migrations`. | 016 dan 018 juga ikut jalan saat deploy kalau belum tercatat di produksi. Statusnya belum diketahui. |
| `app/main.py` dan `app/database.py` tidak memanggil `create_all`. | Menjalankan aplikasi tidak mengubah skema. `init_db.py` hanya drop kalau `INIT_DB_CONFIRM=DROP-ALL`. |
| `.env` lokal menunjuk `localhost:5433/maharasa_pos`. | Belum diketahui apakah ini DB lokal atau tunnel ke produksi. Sampai jelas, `migrate.py`, `init_db.py`, dan server lokal **tidak dijalankan**. |
| Unit test memakai SQLite in-memory (`tests/conftest.py`). Test integrasi hanya mau jalan ke `sync_test` dan memakai skema terpisah yang dihapus lagi. | Aman untuk pengembangan dan pengujian 019. |
| 019 hanya `ADD COLUMN IF NOT EXISTS ... DEFAULT TRUE`. | Tidak mengubah/menghapus baris. PostgreSQL 11+ tidak menulis ulang tabel. Tetap butuh lock singkat `ACCESS EXCLUSIVE` di `brands`. |

Di luar migrasi, kode baru juga bisa menulis data produksi lewat aksi admin: kirim rekap (`closing_export_logs` + API eksternal) dan PATCH brand (`requires_closing`). Itu hanya terjadi setelah deploy dan saat admin menekan tombol.

### Todo

Pengembangan (tidak menyentuh produksi):

- [x] Konfirmasi: `localhost:5433/maharasa_pos` di `.env` adalah DB lokal, bukan produksi (dikonfirmasi user, 4 November 2026). `migrate.py` lokal tetap mengubah skema DB lokal; jalankan setelah disetujui.
- [x] Tulis `migrations/019_brand_requires_closing.sql` dengan header seperti 018 (hanya ADD COLUMN, default TRUE, idempoten).
- [x] Unit test `tests/unit/test_migrate.py`: 019 hanya berisi `ALTER TABLE brands ADD COLUMN IF NOT EXISTS requires_closing`, tanpa UPDATE/DELETE/DROP.
- [x] Test integrasi `tests/integration/test_migrasi_019_postgres.py`, pola 018: skema `uji_migrasi_019` di `sync_test`, jalankan 009 → 019, cek tipe kolom sama dengan model, brand lama bernilai TRUE dan isinya tidak berubah, dijalankan ulang tidak gagal.
- [x] Jalankan unit test dan test integrasi ke `sync_test` saja. (1.329 unit test lulus; 3 test integrasi 019 + 3 test 018 lulus di `sync_test` lokal. Model `Brand.requires_closing` ikut ditambah.)
- [ ] Opsional: uji 001–019 di salinan `pg_dump` produksi yang di-restore ke DB terpisah, bukan ke produksi.

Sebelum deploy (read-only ke produksi, butuh izin):

- [ ] `python migrate.py --status` ke produksi. Perintah ini hanya membaca `schema_migrations`. Catat apakah 016 dan 018 sudah jalan.
- [ ] Query bagian 4 (ProductID bentrok antar-outlet).
- [ ] `SELECT version();`, pastikan PostgreSQL 11+.
- [ ] Ambil `pg_dump` produksi sebagai cadangan sebelum deploy.

Deploy (mengubah skema produksi, butuh persetujuan eksplisit):

- [ ] Jangan build/deploy image baru ke produksi sampai semua item di atas selesai dan disetujui.
- [ ] Deploy di jam sepi karena ada lock singkat di `brands`.
- [ ] Setelah deploy: cek log `[migrate]`, jalankan `migrate.py --status`, dan pastikan semua brand `requires_closing = TRUE`.
- [ ] Mengubah `requires_closing = FALSE` untuk brand tertentu adalah perubahan data. Lakukan lewat halaman admin, setelah disetujui.
