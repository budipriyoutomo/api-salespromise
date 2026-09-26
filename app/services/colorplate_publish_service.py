"""Rekap yang dipublish ke RabbitMQ: qty per warna colorplate / outlet / tanggal.

    sold(warna) = qty menu COLORPLATE warna itu          (kalau group COLORPLATE aktif)
                + Σ qty menu × multiplier                (menu aktif, konversi aktif)

Contoh: PROMO "Buy 1 Get 2 RED" terjual 3 dengan konversi RED × 2, dan
COLORPLATE RED terjual 4 → event RED sold = 4 + 3 × 2 = 10.

Menu yang ProductID-nya ada di group COLORPLATE tidak dikonversi lagi selama
group itu aktif — sudah terhitung langsung.
"""

from dataclasses import dataclass
from datetime import date

from app.services import product_group_service, product_menu_service
from app.services.sales_service import SalesService, color_key


@dataclass
class RekapWarna:
    platecolor: str
    outlet_code: str
    sale_date: date
    sold: int


class TidakAdaYangDipublish(Exception):
    """Group COLORPLATE nonaktif dan tidak ada konversi menu aktif."""


def rekap_colorplate(db, outlet=None, start_date=None, end_date=None) -> list[RekapWarna]:
    colorplate_aktif = SalesService.COLORPLATE in {
        product_group_service.normalize_product_group(g) for g in product_group_service.get_active_groups(db)
    }
    konversi = product_menu_service.get_active_conversions(db)

    if not colorplate_aktif and not konversi:
        raise TidakAdaYangDipublish()

    # (kunci warna, outlet, tanggal) → [nama warna, total]
    total: dict = {}

    def tambah(platecolor, outlet_code, sale_date, qty, dari_colorplate):
        kunci = (color_key(platecolor), outlet_code, sale_date)
        baris = total.get(kunci)
        if baris is None:
            total[kunci] = [platecolor, qty]
            return
        baris[1] += qty
        # Nama dari data COLORPLATE diutamakan, supaya ejaannya sama dengan
        # event sebelum konversi menu ada.
        if dari_colorplate:
            baris[0] = platecolor

    if colorplate_aktif:
        for row in SalesService.get_sales_by_product_groups(
            db, [SalesService.COLORPLATE], outlet=outlet, start_date=start_date, end_date=end_date
        ):
            tambah(row.product_name, row.outlet_code, row.sale_date, row.sold or 0, dari_colorplate=True)

    if konversi:
        for row in SalesService.get_sales_by_product_ids(
            db,
            list(konversi),
            outlet=outlet,
            start_date=start_date,
            end_date=end_date,
            exclude_groups=[SalesService.COLORPLATE] if colorplate_aktif else None,
        ):
            for platecolor, multiplier in konversi[row.product_id]:
                tambah(platecolor, row.outlet_code, row.sale_date, (row.sold or 0) * multiplier, dari_colorplate=False)

    hasil = [
        # `int()` memotong desimal, sama seperti publish sebelumnya.
        RekapWarna(platecolor=nama, outlet_code=outlet_code, sale_date=sale_date, sold=int(sold))
        for (_, outlet_code, sale_date), (nama, sold) in total.items()
    ]
    hasil.sort(key=lambda r: (r.sale_date, r.outlet_code or "", color_key(r.platecolor)))
    return hasil
