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
