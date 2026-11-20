"""Cache TTL kecil di memori proses.

Untuk query ringkasan yang dipoll terus oleh dashboard dan boleh basi beberapa
detik. Per worker gunicorn — tidak dibagi antar worker, dan itu tidak apa-apa:
tujuannya memangkas query berulang, bukan konsistensi.

Error tidak disimpan; panggilan berikutnya mencoba lagi.
"""

import threading
import time

_SEMUA: list["TtlCache"] = []

DEFAULT_MAX_ENTRIES = 500


class TtlCache:
    """`ttl_seconds <= 0` mematikan cache: nilai selalu dihitung, tidak disimpan.

    Jumlah entri dibatasi `max_entries`. Saat penuh, entri basi dibuang lebih
    dulu, lalu yang paling lama disimpan — kunci laporan memuat tanggal dan
    filter bebas, jadi tanpa batas memori worker bisa tumbuh terus.
    """

    def __init__(self, ttl_seconds: float, max_entries: int = DEFAULT_MAX_ENTRIES):
        self.ttl = ttl_seconds
        self.max_entries = max_entries
        # dict menjaga urutan sisip; kunci yang disimpan ulang dipindah ke
        # ujung, jadi elemen pertama selalu yang paling lama.
        self._isi: dict = {}
        self._lock = threading.Lock()
        _SEMUA.append(self)

    def __len__(self):
        with self._lock:
            return len(self._isi)

    def get_or_set(self, key, hitung):
        if self.ttl <= 0:
            return hitung()

        sekarang = time.monotonic()
        with self._lock:
            ada = self._isi.get(key)
            if ada is not None and ada[0] > sekarang:
                return ada[1]

        # Dihitung di luar lock: query lambat tidak boleh menahan kunci lain.
        nilai = hitung()
        with self._lock:
            self._isi.pop(key, None)
            self._isi[key] = (time.monotonic() + self.ttl, nilai)
            self._pangkas()
        return nilai

    def _pangkas(self):
        """Dipanggil dengan lock dipegang."""
        if len(self._isi) <= self.max_entries:
            return

        sekarang = time.monotonic()
        for k in [k for k, (kedaluwarsa, _) in self._isi.items() if kedaluwarsa <= sekarang]:
            del self._isi[k]

        while len(self._isi) > self.max_entries:
            del self._isi[next(iter(self._isi))]

    def clear(self):
        with self._lock:
            self._isi.clear()


def clear_all():
    """Kosongkan semua cache — dipakai test supaya tidak bocor antar-test."""
    for c in _SEMUA:
        c.clear()
