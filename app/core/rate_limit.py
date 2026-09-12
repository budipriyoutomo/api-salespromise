"""Pembatas laju sederhana berbasis sliding window.

Dipakai untuk menahan penebakan password di `/api/auth/login`.

KETERBATASAN YANG PERLU DISADARI
--------------------------------
Hitungannya disimpan di memori proses. Dengan gunicorn 4 worker, batas efektif
menjadi 4x lipat karena tiap worker punya catatannya sendiri, dan seluruh
catatan hilang saat restart.

Untuk penegakan yang sungguh-sungguh (lintas worker dan lintas instance),
catatan ini perlu dipindah ke Redis. Meski begitu, versi in-memory ini sudah
mematikan serangan tebak password yang naif tanpa menambah dependency baru.
"""

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    """Izinkan maksimal `max_attempts` kejadian per `window_seconds` untuk tiap kunci.

    `max_attempts=0` mematikan pembatasan sepenuhnya, supaya bisa dinonaktifkan
    lewat env tanpa mengubah kode.
    """

    def __init__(self, max_attempts: int, window_seconds: int):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds

        self._hits = defaultdict(deque)
        # Endpoint sync dijalankan di threadpool, jadi struktur ini bisa
        # disentuh beberapa thread sekaligus.
        self._lock = threading.Lock()

    def _bersihkan(self, sekarang: float):
        """Buang kunci yang seluruh catatannya sudah kedaluwarsa.

        Tanpa ini, dict-nya tumbuh terus selama proses hidup — tiap IP yang
        pernah mencoba login akan meninggalkan entri permanen.
        """
        batas = sekarang - self.window_seconds

        for kunci in [k for k, v in self._hits.items() if not v or v[-1] <= batas]:
            del self._hits[kunci]

    def allow(self, key: str) -> bool:
        """Catat satu percobaan. `False` berarti jatah sudah habis."""
        if self.max_attempts <= 0:
            return True

        sekarang = time.monotonic()
        batas = sekarang - self.window_seconds

        with self._lock:
            self._bersihkan(sekarang)

            catatan = self._hits[key]
            while catatan and catatan[0] <= batas:
                catatan.popleft()

            if len(catatan) >= self.max_attempts:
                return False

            catatan.append(sekarang)
            return True

    def reset(self, key: str):
        """Kosongkan catatan satu kunci — dipanggil setelah login berhasil."""
        with self._lock:
            self._hits.pop(key, None)

    def clear(self):
        with self._lock:
            self._hits.clear()
