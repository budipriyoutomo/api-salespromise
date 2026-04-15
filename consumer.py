import pika
import json
import os

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "202.138.226.247")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "maharasa")
RABBITMQ_PASSWORD = os.getenv("RABBITMQ_PASSWORD", "b@nd0eng")


def callback(ch, method, properties, body):
    try:
        data = json.loads(body)

        print("📥 Received:", data)

        # 🔥 proses data di sini
        # contoh:
        # save ke database
        # trigger API lain
        # update cache

        ch.basic_ack(delivery_tag=method.delivery_tag)

    except Exception as e:
        print("❌ ERROR:", str(e))
        # optional: reject message
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def consume():
    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASSWORD)

    connection = pika.BlockingConnection(
        pika.ConnectionParameters(host=RABBITMQ_HOST, credentials=credentials)
    )

    channel = connection.channel()

    # ✅ declare exchange
    channel.exchange_declare(
        exchange='sales_exchange',
        exchange_type='direct',
        durable=True
    )

    # ✅ declare queue
    channel.queue_declare(
        queue='sales.queue',
        durable=True
    )

    # ✅ bind queue ke exchange
    channel.queue_bind(
        exchange='sales_exchange',
        queue='sales.queue',
        routing_key='sales.created'
    )

    # ✅ fair dispatch
    channel.basic_qos(prefetch_count=1)

    channel.basic_consume(
        queue='sales.queue',
        on_message_callback=callback
    )

    print("🚀 Waiting for messages...")
    channel.start_consuming()


if __name__ == "__main__":
    consume()