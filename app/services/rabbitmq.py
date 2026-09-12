import json

import pika

from app.config import settings


class RabbitMQClient:
    def __init__(self):
        # Konfigurasi dibaca dari settings, bukan os.getenv yang tersebar —
        # supaya semua env aplikasi terdaftar di satu tempat.
        self.host = settings.RABBITMQ_HOST
        self.user = settings.RABBITMQ_USER
        self.password = settings.RABBITMQ_PASSWORD

        self.connection = None
        self.channel = None

    def _connect(self):
        if self.connection and not self.connection.is_closed:
            return

        credentials = pika.PlainCredentials(self.user, self.password)

        parameters = pika.ConnectionParameters(
            host=self.host,
            credentials=credentials,
            heartbeat=60,
            blocked_connection_timeout=300
        )

        self.connection = pika.BlockingConnection(parameters)
        self.channel = self.connection.channel()

    def publish(self, exchange, routing_key, payload: dict):
        self._connect()

        self.channel.exchange_declare(
            exchange=exchange,
            exchange_type='direct',
            durable=True
        )

        self.channel.basic_publish(
            exchange=exchange,
            routing_key=routing_key,
            body=json.dumps(payload),
            properties=pika.BasicProperties(
                content_type='application/json',
                delivery_mode=2
            )
        )
    def close(self):
        if self.connection and not self.connection.is_closed:
            self.connection.close()
