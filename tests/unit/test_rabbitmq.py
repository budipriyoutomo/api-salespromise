"""Test app/services/rabbitmq.py — semua interaksi pika di-mock, broker tidak disentuh."""

import json
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.services.rabbitmq import RabbitMQClient


@pytest.fixture()
def fake_pika(monkeypatch):
    """Ganti modul pika di dalam rabbitmq.py dengan mock."""
    pika = MagicMock()
    pika.BlockingConnection.return_value.is_closed = False
    monkeypatch.setattr("app.services.rabbitmq.pika", pika)
    return pika


class TestKonfigurasi:

    def test_membaca_env(self):
        client = RabbitMQClient()

        assert client.host == "test-rabbit"
        assert client.user == "test-user"
        assert client.password == "test-pass"

    def test_membaca_dari_settings_bukan_os_getenv(self, monkeypatch):
        """Item 3.9 — konfigurasi broker terpusat di app/config.py.

        Mengubah `settings` harus langsung terlihat oleh client; kalau client
        masih membaca `os.environ` sendiri, test ini gagal.
        """
        from app.config import settings

        monkeypatch.setattr(settings, "RABBITMQ_HOST", "broker-lain")
        monkeypatch.setattr(settings, "RABBITMQ_USER", "user-lain")

        client = RabbitMQClient()

        assert client.host == "broker-lain"
        assert client.user == "user-lain"

    # Default RABBITMQ_* diuji di test_config.py::TestDefaultEnv —
    # di sini cukup dipastikan client mengambilnya dari settings.

    def test_belum_terhubung_saat_dibuat(self, fake_pika):
        """Konstruktor tidak boleh membuka koneksi — dependency dipanggil tiap request."""
        RabbitMQClient()

        fake_pika.BlockingConnection.assert_not_called()


class TestConnect:

    def test_membuka_koneksi_saat_pertama_kali(self, fake_pika):
        client = RabbitMQClient()

        client._connect()

        fake_pika.BlockingConnection.assert_called_once()
        assert client.channel is not None

    def test_memakai_kredensial_dari_env(self, fake_pika):
        client = RabbitMQClient()

        client._connect()

        fake_pika.PlainCredentials.assert_called_once_with("test-user", "test-pass")

    def test_parameter_koneksi(self, fake_pika):
        client = RabbitMQClient()

        client._connect()

        kwargs = fake_pika.ConnectionParameters.call_args.kwargs
        assert kwargs["host"] == "test-rabbit"
        assert kwargs["heartbeat"] == 60
        assert kwargs["blocked_connection_timeout"] == 300

    def test_tidak_membuka_koneksi_baru_saat_masih_terbuka(self, fake_pika):
        client = RabbitMQClient()
        client._connect()
        client._connect()
        client._connect()

        assert fake_pika.BlockingConnection.call_count == 1

    def test_reconnect_saat_koneksi_sudah_tertutup(self, fake_pika):
        client = RabbitMQClient()
        client._connect()
        client.connection.is_closed = True

        client._connect()

        assert fake_pika.BlockingConnection.call_count == 2


class TestPublish:

    def test_connect_dipanggil_otomatis(self, fake_pika):
        client = RabbitMQClient()

        client.publish("ex", "rk", {"a": 1})

        fake_pika.BlockingConnection.assert_called_once()

    def test_mendeklarasikan_exchange_direct_durable(self, fake_pika):
        client = RabbitMQClient()

        client.publish("posdata_exchange", "posdata.created", {"a": 1})

        client.channel.exchange_declare.assert_called_once_with(
            exchange="posdata_exchange",
            exchange_type="direct",
            durable=True,
        )

    def test_mengirim_ke_exchange_dan_routing_key_yang_diminta(self, fake_pika):
        client = RabbitMQClient()

        client.publish("ex-a", "rk-b", {"a": 1})

        kwargs = client.channel.basic_publish.call_args.kwargs
        assert kwargs["exchange"] == "ex-a"
        assert kwargs["routing_key"] == "rk-b"

    def test_payload_di_serialize_json(self, fake_pika):
        client = RabbitMQClient()
        payload = {"event": "posdata.created", "data": {"sold": 4}}

        client.publish("ex", "rk", payload)

        body = client.channel.basic_publish.call_args.kwargs["body"]
        assert json.loads(body) == payload

    def test_pesan_persistent_dan_bertipe_json(self, fake_pika):
        """delivery_mode=2 supaya pesan selamat kalau broker restart."""
        client = RabbitMQClient()

        client.publish("ex", "rk", {"a": 1})

        properties = fake_pika.BasicProperties.call_args.kwargs
        assert properties["delivery_mode"] == 2
        assert properties["content_type"] == "application/json"

    def test_decimal_belum_bisa_di_serialize(self, fake_pika):
        """Penanda: `SUM(qty)` dari Postgres bertipe Decimal.

        Route publish sudah membungkusnya dengan `int()`, tapi kalau nanti ada
        field Decimal lain yang lolos ke payload, publish akan gagal di sini.
        Pasang `default=str` pada json.dumps kalau perilaku ini mau diubah.
        """
        client = RabbitMQClient()

        with pytest.raises(TypeError):
            client.publish("ex", "rk", {"sold": Decimal("4.5")})

    def test_error_dari_broker_diteruskan(self, fake_pika):
        client = RabbitMQClient()
        client._connect()
        client.channel.basic_publish.side_effect = RuntimeError("broker menolak")

        with pytest.raises(RuntimeError, match="broker menolak"):
            client.publish("ex", "rk", {"a": 1})


class TestClose:

    def test_menutup_koneksi_yang_terbuka(self, fake_pika):
        client = RabbitMQClient()
        client._connect()

        client.close()

        client.connection.close.assert_called_once()

    def test_aman_dipanggil_saat_belum_pernah_connect(self, fake_pika):
        client = RabbitMQClient()

        client.close()  # tidak boleh melempar exception

    def test_tidak_menutup_dua_kali(self, fake_pika):
        client = RabbitMQClient()
        client._connect()
        client.connection.is_closed = True

        client.close()

        client.connection.close.assert_not_called()
