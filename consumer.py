"""Contoh consumer RabbitMQ.

Kredensial WAJIB lewat environment — tidak ada nilai default, supaya tidak ada
lagi kredensial produksi yang ikut ter-commit ke repository.

    RABBITMQ_HOST=... RABBITMQ_USER=... RABBITMQ_PASSWORD=... python consumer.py
"""

import json
import os
import sys

import pika

REQUIRED_ENV = ("RABBITMQ_HOST", "RABBITMQ_USER", "RABBITMQ_PASSWORD")

EXCHANGE = os.getenv("RABBITMQ_EXCHANGE", "posdata_exchange")
QUEUE = os.getenv("RABBITMQ_QUEUE", "posdata.queue")
ROUTING_KEY = os.getenv("RABBITMQ_ROUTING_KEY", "posdata.created")


def load_config():
    missing = [name for name in REQUIRED_ENV if not os.getenv(name)]

    if missing:
        print(f"[!] Env belum diisi: {', '.join(missing)}")
        sys.exit(1)

    return {
        "host": os.getenv("RABBITMQ_HOST"),
        "user": os.getenv("RABBITMQ_USER"),
        "password": os.getenv("RABBITMQ_PASSWORD"),
    }


def callback(ch, method, properties, body):
    try:
        data = json.loads(body)

        print("Received:", data)

        # proses data di sini:
        # simpan ke database / teruskan ke API lain / perbarui cache

        ch.basic_ack(delivery_tag=method.delivery_tag)

    except Exception as e:
        print("ERROR:", str(e))
        # requeue=False supaya pesan rusak tidak berputar tanpa henti;
        # arahkan ke dead-letter queue kalau perlu ditinjau manual
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def consume():
    config = load_config()

    credentials = pika.PlainCredentials(config["user"], config["password"])

    connection = pika.BlockingConnection(
        pika.ConnectionParameters(host=config["host"], credentials=credentials)
    )

    channel = connection.channel()

    channel.exchange_declare(exchange=EXCHANGE, exchange_type="direct", durable=True)
    channel.queue_declare(queue=QUEUE, durable=True)
    channel.queue_bind(exchange=EXCHANGE, queue=QUEUE, routing_key=ROUTING_KEY)

    # fair dispatch — satu pesan per consumer sampai di-ack
    channel.basic_qos(prefetch_count=1)

    channel.basic_consume(queue=QUEUE, on_message_callback=callback)

    print(f"Menunggu pesan di queue '{QUEUE}' (exchange '{EXCHANGE}')...")
    channel.start_consuming()


if __name__ == "__main__":
    consume()
