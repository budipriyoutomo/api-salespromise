"""`sales` dan `items[].prices` untuk kirim rekap closing (kontrak revisi 3).

Kontrak: docs/usulan-kontrak-kirim-closing.md bagian 2.2–2.5.

Modul ini murni (tanpa DB): masukannya baris POS yang sudah dikelompokkan
per item, `SaleMode`, dan harga, plus total header transaksi per `SaleMode`.

    subtotal       Σ qty × Price baris POS (bukan header), supaya cocok dengan
                   jumlah `prices` per item.
    discountTotal  Σ ReceiptDiscount header
    otherTaxTotal  Σ ServiceCharge header
    vatTotal       Σ TransactionVAT header
    orderFee       Σ OtherIncome header (sementara, menunggu jawaban ERP)
    grandTotal     subtotal − discountTotal + otherTaxTotal + vatTotal + orderFee

Rumus grandTotal berlaku untuk semua outlet. Di outlet ST hasilnya sama dengan
ReceiptSalePrice. Di outlet TS ReceiptSalePrice hanya subtotal − diskon,
padahal tamu membayar subtotal + SC + PPN (dikonfirmasi user 2026-11-12).

colorplateSold menu closing diberi harga piring warna menu itu
(`bagi_colorplate`): baris COLORPLATE POS warna itu (SaleMode + harga)
dipasangkan ke menu-menu berwarna sama. Produk COLORPLATE POS sendiri tidak
dikirim sebagai item.

POS mencatat diskon, service charge, dan PPN per transaksi. Nilainya dibagi
ke baris `prices` sebanding dengan qty × price, dibulatkan 2 desimal, dan sisa
pembulatan ditaruh di baris terbesar. Jadi per `visitPurposeName`, jumlah
`prices` selalu sama persis dengan `sales` (di luar orderFee).
"""

from collections.abc import Hashable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

DUA_DESIMAL = Decimal("0.01")

# SaleMode POS → visitPurposeName. Nama resmi belum diketahui (kontrak 2.2).
NAMA_TUJUAN_KUNJUNGAN: dict[int, str] = {}


def nama_tujuan(sale_mode: int) -> str:
    return NAMA_TUJUAN_KUNJUNGAN.get(sale_mode, f"SALEMODE {sale_mode}")


def bulat(nilai) -> Decimal:
    return Decimal(nilai or 0).quantize(DUA_DESIMAL, rounding=ROUND_HALF_UP)


def angka(nilai: Decimal):
    """Decimal → int kalau bulat, selain itu float (2 desimal)."""
    nilai = bulat(nilai)
    return int(nilai) if nilai == nilai.to_integral_value() else float(nilai)


def bagi(total, bobot: list[Decimal]) -> list[Decimal]:
    """Bagi `total` sebanding `bobot`; jumlah hasilnya tepat `total` (2 desimal)."""
    if not bobot:
        return []
    total = bulat(total)
    jumlah = sum(bobot)
    if jumlah == 0:
        bobot, jumlah = [Decimal(1)] * len(bobot), Decimal(len(bobot))
    bagian = [bulat(total * b / jumlah) for b in bobot]
    terbesar = max(range(len(bobot)), key=lambda i: bobot[i])
    bagian[terbesar] += total - sum(bagian)
    return bagian


def bagi_bulat(total: int, bobot: list[Decimal]) -> list[int]:
    """Bagi bilangan bulat `total` sebanding `bobot`; sisa ke pecahan terbesar."""
    jumlah = sum(bobot)
    if not bobot or jumlah <= 0:
        return [0] * len(bobot)
    mentah = [Decimal(total) * b / jumlah for b in bobot]
    bagian = [int(m) for m in mentah]
    urutan = sorted(range(len(bobot)), key=lambda i: (-(mentah[i] - bagian[i]), i))
    for i in urutan[: total - sum(bagian)]:
        bagian[i] += 1
    return bagian


def bagi_colorplate(
    sold_per_menu: dict[Hashable, int],
    tingkat: dict[tuple[int, Decimal, Decimal], Decimal],
) -> dict[Hashable, dict[tuple[int, Decimal, Decimal], Decimal]]:
    """Pasangkan colorplateSold menu-menu satu warna ke baris harga piring POS warna itu.

    `tingkat`: (SaleMode, RetailPrice, Price) per piring → jumlah piring di POS.
    Jumlah piring POS lebih dulu diskalakan ke total colorplateSold (qty dapur),
    lalu diisikan berurutan ke menu. Kalau qty dapur = qty POS, hasilnya persis
    baris POS, jadi pendapatannya sama dengan uang kasir.

    Hasil: menu → {(SaleMode, RetailPrice, Price): qty}. Kosong kalau tidak ada
    yang terjual; ValueError kalau ada yang terjual tetapi POS tanpa harga.
    """
    menu = sorted(((m, int(q)) for m, q in sold_per_menu.items() if q and int(q) > 0), key=lambda x: str(x[0]))
    total = sum(q for _, q in menu)
    if total == 0:
        return {}
    kunci = sorted(k for k, q in tingkat.items() if q > 0)
    if not kunci:
        raise ValueError("warna ini tidak terjual di POS")
    sisa = dict(zip(kunci, bagi_bulat(total, [Decimal(tingkat[k]) for k in kunci])))

    hasil: dict = {}
    i = 0
    for m, butuh in menu:
        while butuh:
            while sisa[kunci[i]] == 0:
                i += 1
            ambil = min(butuh, sisa[kunci[i]])
            baris = hasil.setdefault(m, {})
            baris[kunci[i]] = baris.get(kunci[i], Decimal(0)) + Decimal(ambil)
            sisa[kunci[i]] -= ambil
            butuh -= ambil
    return hasil


@dataclass
class HeaderMode:
    """Total header transaksi satu SaleMode pada satu outlet + tanggal."""

    pax: int = 0
    diskon: Decimal = Decimal(0)
    service_charge: Decimal = Decimal(0)
    ppn: Decimal = Decimal(0)
    pendapatan_lain: Decimal = Decimal(0)
    persen_service_charge: Decimal = Decimal(0)
    persen_ppn: Decimal = Decimal(0)


@dataclass
class _Baris:
    item: Hashable
    sale_mode: int
    harga_asli: Decimal
    harga: Decimal
    qty: Decimal

    @property
    def dasar(self) -> Decimal:
        return self.qty * self.harga


def susun(
    baris_per_item: dict[Hashable, dict[tuple[int, Decimal, Decimal], Decimal]],
    header: dict[int, HeaderMode],
) -> tuple[dict[Hashable, list[dict]], list[dict]]:
    """Susun `prices` per item dan `sales` per tujuan kunjungan.

    `baris_per_item`: item → {(SaleMode, RetailPrice, Price): qty}.
    Baris dengan qty 0 dibuang.
    """
    per_mode: dict[int, list[_Baris]] = {}
    for item, isi in baris_per_item.items():
        for (mode, harga_asli, harga), qty in isi.items():
            qty = Decimal(qty)
            if qty == 0:
                continue
            per_mode.setdefault(mode, []).append(_Baris(item, mode, Decimal(harga_asli), Decimal(harga), qty))

    prices: dict[Hashable, list[dict]] = {}
    sales: list[dict] = []
    for mode in sorted(set(per_mode) | set(header)):
        baris = per_mode.get(mode, [])
        h = header.get(mode, HeaderMode())
        dasar = [b.dasar for b in baris]
        diskon = bagi(h.diskon, dasar)
        sc = bagi(h.service_charge, dasar)
        ppn = bagi(h.ppn, dasar)
        nama = nama_tujuan(mode)

        for b, d, s, p in zip(baris, diskon, sc, ppn):
            nilai_dasar = bulat(b.dasar)
            prices.setdefault(b.item, []).append(
                {
                    "visitPurposeName": nama,
                    "qty": angka(b.qty),
                    "originalPrice": angka(b.harga_asli),
                    "price": angka(b.harga),
                    "discount": angka(d / nilai_dasar * 100) if nilai_dasar else 0,
                    "discountValue": angka(d),
                    "otherTax": angka(h.persen_service_charge),
                    "otherTaxValue": angka(s),
                    "vat": angka(h.persen_ppn),
                    "vatValue": angka(p),
                    "otherVat": 0,
                    "otherVatValue": 0,
                    "otherTaxOnVat": 0,
                    "total": angka(nilai_dasar - d + s + p),
                }
            )

        subtotal = sum((bulat(x) for x in dasar), Decimal(0))
        diskon_total, sc_total, ppn_total = bulat(h.diskon), bulat(h.service_charge), bulat(h.ppn)
        biaya = bulat(h.pendapatan_lain)
        grand = subtotal - diskon_total + sc_total + ppn_total + biaya
        sales.append(
            {
                "visitPurposeName": nama,
                "paxTotal": int(h.pax or 0),
                "flagInclusive": 0,
                "subtotal": angka(subtotal),
                "discountTotal": angka(diskon_total),
                "menuDiscountTotal": 0,
                "promotionDiscount": 0,
                "otherTaxTotal": angka(sc_total),
                "vatTotal": angka(ppn_total),
                "otherVatTotal": 0,
                "deliveryFee": 0,
                "orderFee": angka(biaya),
                "voucherTotal": 0,
                "roundingTotal": 0,
                "grandTotal": angka(grand),
                "paymentTotal": angka(grand),
                "payments": [],
            }
        )

    for daftar in prices.values():
        daftar.sort(key=lambda p: (p["visitPurposeName"], p["originalPrice"], p["price"]))
    return prices, sales
