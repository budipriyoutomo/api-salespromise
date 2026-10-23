"""Cache TTL kecil di memori proses.

Untuk query ringkasan yang dipoll terus oleh dashboard dan boleh basi beberapa
detik. Per worker gunicorn — tidak dibagi antar worker, dan itu tidak apa-apa:
tujuannya memangkas query berulang, bukan konsistensi.

Error tidak disimpan; panggilan berikutnya mencoba lagi.
"""

import threading
import time

_SEMUA: list["TtlCache"] = []


class TtlCache:

    def __init__(self, ttl_seconds: float):
        self.ttl = ttl_seconds
        self._isi: dict = {}
        self._lock = threading.Lock()
        _SEMUA.append(self)

    def get_or_set(self, key, hitung):
        sekarang = time.monotonic()
        with self._lock:
            ada = self._isi.get(key)
            if ada is not None and ada[0] > sekarang:
                return ada[1]

        # Dihitung di luar lock: query lambat tidak boleh menahan kunci lain.
        nilai = hitung()
        with self._lock:
            self._isi[key] = (time.monotonic() + self.ttl, nilai)
        return nilai

    def clear(self):
        with self._lock:
            self._isi.clear()


def clear_all():
    """Kosongkan semua cache — dipakai test supaya tidak bocor antar-test."""
    for c in _SEMUA:
        c.clear()
