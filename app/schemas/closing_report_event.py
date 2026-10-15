"""Kontrak event `closingreport.submitted` dari RabbitMQ (TODO Fase 7).

Closing report harian per outlet dari sistem lain, untuk dibandingkan dengan
penjualan POS. Field JSON memakai camelCase; di Python snake_case.

Pesan yang gagal validasi di sini tidak boleh menyentuh database — consumer
mengarahkannya ke DLQ.
"""

import datetime as dt
from typing import Annotated, List, Literal, Optional
from uuid import UUID

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)
from pydantic.alias_generators import to_camel

from app.services.brand_service import MAX_BRAND_CODE_LENGTH, normalize_brand_code

# Sama dengan panjang `api_keys.outlet_code`.
MAX_OUTLET_CODE_LENGTH = 20
MAX_NAME_LENGTH = 255
MAX_MENU_CODE_LENGTH = 50
MAX_MESSAGE_ID_LENGTH = 255


def _wajib_isi(maks: int):
    return Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=maks)]


def _ke_utc_naive(value: dt.datetime) -> dt.datetime:
    # Kolom timestamp di DB tanpa timezone dan berisi UTC (lihat app/core/time.py).
    return value.astimezone(dt.timezone.utc).replace(tzinfo=None)


def _brand_code(value: str) -> str:
    normal = normalize_brand_code(value)
    if not normal:
        raise ValueError("brand.code wajib diisi")
    if len(normal) > MAX_BRAND_CODE_LENGTH:
        raise ValueError(f"brand.code maksimal {MAX_BRAND_CODE_LENGTH} karakter")
    return normal


def _kosong_jadi_none(value):
    if isinstance(value, str) and not value.strip():
        return None
    return value


Qty = Annotated[int, Field(ge=0)]

MAX_CATEGORY_CODE_LENGTH = 50


class _Kontrak(BaseModel):
    # Field tambahan dari pengirim diabaikan supaya kontrak bisa bertambah
    # tanpa mematahkan consumer.
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")


class ClosingOutlet(_Kontrak):
    # Huruf tidak diubah di sini. Service mencocokkannya ke `api_keys` setelah
    # normalisasi (jawaban pengirim: sama dengan kode POS setelah dinormalisasi).
    code: _wajib_isi(MAX_OUTLET_CODE_LENGTH)
    name: _wajib_isi(MAX_NAME_LENGTH)


class ClosingBrand(_Kontrak):
    code: Annotated[str, AfterValidator(_brand_code)]
    name: _wajib_isi(MAX_NAME_LENGTH)


class ClosingWasteCategory(_Kontrak):
    # Kunci stabil dari pengirim; huruf tidak diubah. `categoryName` hanya
    # nama tampilan saat pesan disusun dan bisa berubah.
    category_code: _wajib_isi(MAX_CATEGORY_CODE_LENGTH)
    category_name: _wajib_isi(MAX_NAME_LENGTH)
    quantity: Annotated[int, Field(gt=0)]


class ClosingReportItem(_Kontrak):
    # Kunci menu: UUID, selalu terisi, tidak pernah berubah (jawaban pengirim).
    menu_id: UUID
    # Atribut saja — bisa berubah, unik hanya per brand, dan bisa null.
    menu_code: Annotated[
        Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=MAX_MENU_CODE_LENGTH)]],
        BeforeValidator(_kosong_jadi_none),
    ] = None
    menu_name: _wajib_isi(MAX_NAME_LENGTH)
    # Pembanding ke tanggal transaksi POS. Null kalau menu tidak punya baris
    # produksi hari itu — perbandingan memakai `data.date`.
    production_date: Optional[dt.date] = None

    sold: Qty
    waste: Qty
    # Koreksi, boleh negatif (dikonfirmasi pengirim).
    adjustment: int
    # Seharusnya >= 0, tapi pengirim belum memvalidasinya per menu. Diterima;
    # consumer mencatat warning untuk nilai negatif.
    compensation: int
    # Wajib di versi 2, tidak ada di versi 1. Kosong kalau waste = 0.
    waste_by_category: Optional[List[ClosingWasteCategory]] = None

    @model_validator(mode="after")
    def _kategori_tidak_dobel(self):
        kode = [k.category_code for k in self.waste_by_category or []]
        dobel = sorted({k for k in kode if kode.count(k) > 1})
        if dobel:
            raise ValueError(f"wasteByCategory: kategori {', '.join(dobel)} muncul lebih dari sekali")
        return self

    @property
    def waste_kategori_selisih(self) -> bool:
        """Total per kategori tidak sama dengan `waste`. Pengirim menjaminnya
        sama; kalau tidak, laporan tetap disimpan dan consumer mencatat warning
        — angka `waste` sendiri tetap dipakai."""
        if self.waste_by_category is None:
            return False
        return sum(k.quantity for k in self.waste_by_category) != self.waste


class ClosingReportData(_Kontrak):
    closing_report_id: UUID
    date: dt.date
    outlet: ClosingOutlet
    brand: ClosingBrand
    items: List[ClosingReportItem] = Field(min_length=1)

    @model_validator(mode="after")
    def _satu_baris_per_menu_dan_tanggal(self):
        terlihat = set()
        for item in self.items:
            kunci = (item.menu_id, item.production_date)
            if kunci in terlihat:
                raise ValueError(
                    f"menu {item.menu_id} tanggal produksi {item.production_date} muncul lebih dari sekali"
                )
            terlihat.add(kunci)
        return self


class ClosingReportSubmitted(_Kontrak):
    event: Literal["closingreport.submitted"]
    # Versi 2 menambah `items[].wasteByCategory` (docs/bi-closing-report-v2-waste-category.md).
    version: Literal[1, 2]
    message_id: _wajib_isi(MAX_MESSAGE_ID_LENGTH)
    # Wajib ber-offset: tanpa itu tidak bisa diketahui WIB atau UTC.
    sent_at: Annotated[AwareDatetime, AfterValidator(_ke_utc_naive)]
    data: ClosingReportData

    @model_validator(mode="after")
    def _v2_wajib_rincian_waste(self):
        if self.version >= 2:
            tanpa = [str(i.menu_id) for i in self.data.items if i.waste_by_category is None]
            if tanpa:
                raise ValueError(f"version {self.version}: wasteByCategory wajib ada di setiap item ({', '.join(tanpa)})")
        return self
