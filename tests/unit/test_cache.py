"""Cache TTL kecil di memori proses untuk query ringkasan yang sering dipoll."""

from app.core import cache as cache_module
from app.core.cache import TtlCache


class Jam:
    def __init__(self):
        self.sekarang = 1000.0

    def __call__(self):
        return self.sekarang


def test_nilai_dipakai_ulang_sebelum_kedaluwarsa(monkeypatch):
    jam = Jam()
    monkeypatch.setattr(cache_module.time, "monotonic", jam)
    c = TtlCache(ttl_seconds=30)
    dihitung = []

    def hitung():
        dihitung.append(1)
        return len(dihitung)

    assert c.get_or_set("a", hitung) == 1
    jam.sekarang += 29
    assert c.get_or_set("a", hitung) == 1
    assert len(dihitung) == 1


def test_dihitung_ulang_setelah_kedaluwarsa(monkeypatch):
    jam = Jam()
    monkeypatch.setattr(cache_module.time, "monotonic", jam)
    c = TtlCache(ttl_seconds=30)
    nilai = iter([1, 2])

    assert c.get_or_set("a", lambda: next(nilai)) == 1
    jam.sekarang += 31
    assert c.get_or_set("a", lambda: next(nilai)) == 2


def test_kunci_berbeda_terpisah():
    c = TtlCache(ttl_seconds=30)

    assert c.get_or_set("a", lambda: "A") == "A"
    assert c.get_or_set("b", lambda: "B") == "B"


def test_error_tidak_disimpan():
    c = TtlCache(ttl_seconds=30)

    def gagal():
        raise RuntimeError("db mati")

    try:
        c.get_or_set("a", gagal)
    except RuntimeError:
        pass

    assert c.get_or_set("a", lambda: "pulih") == "pulih"


def test_clear_semua_cache():
    c = TtlCache(ttl_seconds=30)
    c.get_or_set("a", lambda: 1)

    cache_module.clear_all()

    assert c.get_or_set("a", lambda: 2) == 2


def test_ttl_nol_berarti_cache_mati():
    """REPORT_CACHE_TTL_SECONDS=0 harus benar-benar mematikan cache — bukan
    menyimpan entri yang langsung basi dan tetap memakan memori."""
    c = TtlCache(ttl_seconds=0)
    nilai = iter([1, 2])

    assert c.get_or_set("a", lambda: next(nilai)) == 1
    assert c.get_or_set("a", lambda: next(nilai)) == 2
    assert len(c) == 0


def test_jumlah_entri_dibatasi():
    """Kunci laporan memuat tanggal & filter bebas — tanpa batas, kombinasi
    filter yang terus berganti membuat memori worker tumbuh tanpa henti."""
    c = TtlCache(ttl_seconds=30, max_entries=3)

    for k in "abcde":
        c.get_or_set(k, lambda k=k: k)

    assert len(c) == 3


def test_yang_dibuang_entri_paling_lama(monkeypatch):
    jam = Jam()
    monkeypatch.setattr(cache_module.time, "monotonic", jam)
    c = TtlCache(ttl_seconds=30, max_entries=2)

    c.get_or_set("lama", lambda: "L")
    jam.sekarang += 1
    c.get_or_set("tengah", lambda: "T")
    jam.sekarang += 1
    c.get_or_set("baru", lambda: "B")

    # "tengah" & "baru" masih tersimpan, "lama" sudah dibuang.
    assert c.get_or_set("tengah", lambda: "dihitung ulang") == "T"
    assert c.get_or_set("baru", lambda: "dihitung ulang") == "B"
    assert c.get_or_set("lama", lambda: "dihitung ulang") == "dihitung ulang"


def test_entri_yang_dihitung_ulang_tidak_dianggap_paling_lama(monkeypatch):
    """Kunci yang disimpan ulang setelah basi harus pindah ke ujung antrean.

    `dict[k] = v` pada kunci yang sudah ada tidak mengubah urutannya — tanpa
    penanganan khusus, entri yang baru saja disegarkan justru dibuang duluan.
    """
    jam = Jam()
    monkeypatch.setattr(cache_module.time, "monotonic", jam)
    c = TtlCache(ttl_seconds=30, max_entries=2)

    c.get_or_set("segar", lambda: "S")
    jam.sekarang += 1
    c.get_or_set("dihitung_ulang", lambda: 1)
    jam.sekarang += 31  # keduanya basi sekarang
    c.get_or_set("segar", lambda: "S2")  # diperbarui → segar lagi
    c.get_or_set("baru", lambda: "B")

    assert c.get_or_set("segar", lambda: "salah") == "S2"
    assert c.get_or_set("baru", lambda: "salah") == "B"


def test_batas_default_500():
    assert TtlCache(ttl_seconds=30).max_entries == 500
