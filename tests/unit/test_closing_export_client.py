"""Test HTTP client kirim rekap closing ke API eksternal (TODO Fase 8.5).

Memakai `httpx.MockTransport` — tidak ada jaringan sungguhan. Aturan retry
mengikuti docs/usulan-kontrak-kirim-closing.md bagian 3.
"""

import json

import httpx
import pytest

from app.services import closing_export_client
from app.services.closing_export_client import MAX_RESPONSE_BODY

URL = "https://api.contoh.id/closing-totals"
TOKEN = "token-rahasia-123"
MESSAGE_ID = "6f1c2a7e-3b4d-4e8f-9a10-2b3c4d5e6f70"
PAYLOAD = {"messageId": MESSAGE_ID, "items": [{"totalSold": 13}]}


class Server:
    """Mengembalikan response sesuai urutan; mencatat setiap request."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        hasil = self.responses.pop(0)
        if isinstance(hasil, Exception):
            raise hasil
        return hasil


@pytest.fixture()
def jeda():
    """Jeda antar percobaan yang diminta client, tanpa benar-benar menunggu."""
    return []


def kirim(server, jeda, max_retries=2):
    return closing_export_client.kirim(
        PAYLOAD,
        message_id=MESSAGE_ID,
        url=URL,
        token=TOKEN,
        timeout=5,
        max_retries=max_retries,
        transport=httpx.MockTransport(server),
        sleep=jeda.append,
    )


def test_request_sesuai_kontrak(jeda):
    server = Server(httpx.Response(201, json={"id": "abc"}))

    hasil = kirim(server, jeda)

    req = server.requests[0]
    assert req.method == "POST"
    assert str(req.url) == URL
    assert req.headers["Authorization"] == f"Bearer {TOKEN}"
    assert req.headers["Idempotency-Key"] == MESSAGE_ID
    assert req.headers["Content-Type"] == "application/json"
    assert json.loads(req.content) == PAYLOAD
    assert (hasil.status, hasil.http_status, hasil.attempts, hasil.error) == ("terkirim", 201, 1, None)
    assert json.loads(hasil.response_body) == {"id": "abc"}
    assert jeda == []


@pytest.mark.parametrize("kode", [200, 201, 202, 204])
def test_semua_2xx_terkirim(jeda, kode):
    assert kirim(Server(httpx.Response(kode)), jeda).status == "terkirim"


def test_409_duplikat_tidak_diulang(jeda):
    server = Server(httpx.Response(409, json={"detail": "messageId sudah diterima"}))

    hasil = kirim(server, jeda)

    assert (hasil.status, hasil.http_status, hasil.attempts) == ("duplikat", 409, 1)
    assert len(server.requests) == 1


@pytest.mark.parametrize("kode", [400, 401, 403, 404, 422])
def test_4xx_gagal_tanpa_diulang(jeda, kode):
    server = Server(httpx.Response(kode, text="payload salah"))

    hasil = kirim(server, jeda)

    assert (hasil.status, hasil.http_status, hasil.attempts) == ("gagal", kode, 1)
    assert hasil.response_body == "payload salah"
    assert hasil.error == f"HTTP {kode}"
    assert len(server.requests) == 1


@pytest.mark.parametrize("kode", [429, 500, 502, 503])
def test_sementara_diulang_lalu_berhasil(jeda, kode):
    server = Server(httpx.Response(kode), httpx.Response(200))

    hasil = kirim(server, jeda)

    assert (hasil.status, hasil.attempts) == ("terkirim", 2)
    assert len(jeda) == 1


def test_messageid_dan_body_sama_di_setiap_percobaan(jeda):
    server = Server(httpx.Response(500), httpx.Response(500), httpx.Response(200))

    kirim(server, jeda)

    assert len({r.headers["Idempotency-Key"] for r in server.requests}) == 1
    assert len({r.content for r in server.requests}) == 1


def test_percobaan_habis_gagal(jeda):
    server = Server(httpx.Response(500), httpx.Response(502), httpx.Response(503, text="maintenance"))

    hasil = kirim(server, jeda, max_retries=2)

    assert (hasil.status, hasil.http_status, hasil.attempts) == ("gagal", 503, 3)
    assert hasil.response_body == "maintenance"
    assert jeda == [1, 2]


def test_tanpa_retry(jeda):
    server = Server(httpx.Response(500))

    hasil = kirim(server, jeda, max_retries=0)

    assert (hasil.status, hasil.attempts) == ("gagal", 1)
    assert jeda == []


def test_timeout_diulang(jeda):
    server = Server(httpx.ReadTimeout("lambat"), httpx.Response(200))

    hasil = kirim(server, jeda)

    assert (hasil.status, hasil.attempts) == ("terkirim", 2)


def test_koneksi_gagal_terus(jeda):
    server = Server(*[httpx.ConnectError("tidak bisa terhubung")] * 3)

    hasil = kirim(server, jeda)

    assert (hasil.status, hasil.http_status, hasil.attempts) == ("gagal", None, 3)
    assert hasil.error.startswith("koneksi gagal")


def test_timeout_terakhir_dicatat(jeda):
    server = Server(*[httpx.ReadTimeout("lambat")] * 3)

    hasil = kirim(server, jeda)

    assert (hasil.status, hasil.error) == ("gagal", "timeout")


def test_retry_after_diikuti_dengan_batas(jeda):
    server = Server(
        httpx.Response(429, headers={"Retry-After": "7"}),
        httpx.Response(503, headers={"Retry-After": "3600"}),
        httpx.Response(200),
    )

    kirim(server, jeda)

    assert jeda == [7, closing_export_client.MAX_JEDA]


def test_response_panjang_dipotong(jeda):
    hasil = kirim(Server(httpx.Response(422, text="x" * (MAX_RESPONSE_BODY + 500))), jeda)

    assert len(hasil.response_body) == MAX_RESPONSE_BODY


def test_token_tidak_masuk_hasil(jeda):
    server = Server(httpx.ConnectError(f"gagal ke {URL}"), httpx.Response(401), httpx.Response(200))

    hasil = kirim(server, jeda)

    assert TOKEN not in repr(hasil)
