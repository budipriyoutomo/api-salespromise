"""Worker consumer `closingreport.submitted` dari RabbitMQ (TODO Fase 7.4).

    python -m app.consumers.closing_report_consumer

Proses terpisah dari gunicorn — kalau ikut di dalam API, keempat worker
gunicorn masing-masing menjadi consumer.

Topologi:
    exchange pengirim (CLOSING_EXCHANGE)  hanya dicek ada (passive), tidak dibuat:
                                          declare dengan tipe berbeda dari milik
                                          pengirim akan ditolak broker
    queue kita (CLOSING_QUEUE)            durable, diikat ke exchange pengirim
    <queue>.dlx / <queue>.dlq             tujuan pesan yang ditolak

Keputusan per pesan:
    tersimpan / duplikat                  ack (setelah commit)
    bukan JSON, gagal validasi, error lain  nack tanpa requeue → DLQ
    database putus                        jeda lalu requeue — datanya valid,
                                          tidak boleh dibuang
"""

import json
import logging
import signal
import sys
import time
from dataclasses import dataclass
from enum import Enum

import pika
from pydantic import ValidationError
from sqlalchemy import inspect
from sqlalchemy.exc import DisconnectionError, OperationalError

from app.config import settings
from app.core.request_context import new_request_id, request_id_var, sanitize_request_id
from app.database import SessionLocal
from app.schemas.closing_report_event import ClosingReportSubmitted
from app.services.closing_report_service import simpan_closing_report
from app.utils.logger import LOGGER_NAME, build_formatter, logger

JEDA_ULANGI_DETIK = 5
JEDA_RECONNECT_AWAL = 1
JEDA_RECONNECT_MAKS = 60
HEARTBEAT_DETIK = 60
JEDA_CEK_SKEMA_DETIK = 10

# Dibuat migrasi 011 yang dijalankan container API, bukan worker ini.
TABEL_WAJIB = ("closing_reports", "closing_report_revisions", "closing_report_items", "closing_menus")

# Error database yang biasanya sembuh sendiri (server restart, koneksi putus).
ERROR_SEMENTARA = (OperationalError, DisconnectionError)


class Keputusan(Enum):
    ACK = "ack"
    DLQ = "dlq"
    ULANGI = "ulangi"


class KonfigurasiTidakLengkap(Exception):
    pass


@dataclass(frozen=True)
class KonfigurasiConsumer:
    host: str
    port: int
    vhost: str
    user: str
    password: str
    exchange: str
    routing_key: str
    queue: str
    prefetch: int

    @property
    def dlx(self) -> str:
        return f"{self.queue}.dlx"

    @property
    def dlq(self) -> str:
        return f"{self.queue}.dlq"

    @classmethod
    def dari_settings(cls) -> "KonfigurasiConsumer":
        wajib = ("RABBITMQ_HOST", "RABBITMQ_USER", "RABBITMQ_PASSWORD", "CLOSING_EXCHANGE", "CLOSING_ROUTING_KEY", "CLOSING_QUEUE")
        kosong = [nama for nama in wajib if not getattr(settings, nama)]
        if kosong:
            raise KonfigurasiTidakLengkap(f"Env belum diisi: {', '.join(kosong)}")

        return cls(
            host=settings.RABBITMQ_HOST,
            port=settings.RABBITMQ_PORT,
            vhost=settings.RABBITMQ_VHOST,
            user=settings.RABBITMQ_USER,
            password=settings.RABBITMQ_PASSWORD,
            exchange=settings.CLOSING_EXCHANGE,
            routing_key=settings.CLOSING_ROUTING_KEY,
            queue=settings.CLOSING_QUEUE,
            prefetch=settings.CLOSING_PREFETCH,
        )


def proses_pesan(body: bytes, session_factory=SessionLocal) -> Keputusan:
    """Validasi lalu simpan satu pesan. Tidak pernah melempar exception."""
    try:
        raw = json.loads(body)
    except (ValueError, UnicodeDecodeError) as e:
        logger.error("CLOSING REPORT DITOLAK: bukan JSON", extra={"error": str(e), "body_bytes": len(body)})
        return Keputusan.DLQ

    if not isinstance(raw, dict):
        logger.error("CLOSING REPORT DITOLAK: JSON bukan objek", extra={"tipe": type(raw).__name__})
        return Keputusan.DLQ

    try:
        event = ClosingReportSubmitted.model_validate(raw)
    except ValidationError as e:
        logger.error(
            "CLOSING REPORT DITOLAK: gagal validasi",
            extra={
                "message_id": str(raw.get("messageId")),
                "errors": e.errors(include_url=False, include_input=False),
            },
        )
        return Keputusan.DLQ

    token = request_id_var.set(sanitize_request_id(event.message_id) or new_request_id())
    db = session_factory()
    try:
        hasil = simpan_closing_report(db, event, raw)
    except ERROR_SEMENTARA as e:
        logger.warning("CLOSING REPORT DIULANG: database tidak tersedia", extra={"error": str(e).strip()})
        return Keputusan.ULANGI
    except Exception:
        logger.exception("CLOSING REPORT DITOLAK: gagal disimpan")
        return Keputusan.DLQ
    else:
        logger.info(
            f"CLOSING REPORT {hasil.status.value.upper()}",
            extra={
                "message_id": event.message_id,
                "closing_report_id": str(event.data.closing_report_id),
                "outlet": event.data.outlet.code,
                "outlet_dikenal": hasil.outlet_dikenal,
                "report_date": str(event.data.date),
                "items": len(event.data.items),
                "revision_id": hasil.revision_id,
            },
        )
        if not hasil.outlet_dikenal:
            logger.warning("CLOSING REPORT: outlet belum terdaftar di api_keys", extra={"outlet": event.data.outlet.code})
        negatif = [str(i.menu_id) for i in event.data.items if i.compensation < 0]
        if negatif:
            # Pengirim belum memvalidasinya per menu; laporan tetap disimpan
            # (keputusan 2026-10-05) supaya satu angka tidak membuang laporan sehari.
            logger.warning(
                "CLOSING REPORT: compensation negatif",
                extra={"closing_report_id": str(event.data.closing_report_id), "menu_ids": negatif},
            )
        return Keputusan.ACK
    finally:
        db.close()
        request_id_var.reset(token)


def skema_siap(session_factory=SessionLocal) -> bool:
    """Tabel closing report sudah dibuat migrasi dan database bisa dihubungi."""
    try:
        db = session_factory()
    except ERROR_SEMENTARA:
        return False
    try:
        inspektor = inspect(db.get_bind())
        return all(inspektor.has_table(tabel) for tabel in TABEL_WAJIB)
    except ERROR_SEMENTARA:
        return False
    finally:
        db.close()


def on_message(ch, method, properties, body):
    keputusan = proses_pesan(body)

    if keputusan is Keputusan.ACK:
        ch.basic_ack(delivery_tag=method.delivery_tag)
    elif keputusan is Keputusan.ULANGI:
        # connection.sleep, bukan time.sleep: heartbeat tetap terkirim selama menunggu.
        ch.connection.sleep(JEDA_ULANGI_DETIK)
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
    else:
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def siapkan_channel(ch, cfg: KonfigurasiConsumer):
    # Exchange milik pengirim: gagal (404) kalau belum ada, bukan dibuat diam-diam.
    ch.exchange_declare(exchange=cfg.exchange, passive=True)

    ch.exchange_declare(exchange=cfg.dlx, exchange_type="direct", durable=True)
    ch.queue_declare(queue=cfg.dlq, durable=True)
    ch.queue_bind(queue=cfg.dlq, exchange=cfg.dlx, routing_key=cfg.queue)

    ch.queue_declare(
        queue=cfg.queue,
        durable=True,
        arguments={"x-dead-letter-exchange": cfg.dlx, "x-dead-letter-routing-key": cfg.queue},
    )
    ch.queue_bind(queue=cfg.queue, exchange=cfg.exchange, routing_key=cfg.routing_key)

    ch.basic_qos(prefetch_count=cfg.prefetch)
    ch.basic_consume(queue=cfg.queue, on_message_callback=on_message)


class Worker:
    def __init__(self, cfg: KonfigurasiConsumer):
        self.cfg = cfg
        self.berhenti = False
        self.connection = None
        self.channel = None

    def _parameter(self):
        return pika.ConnectionParameters(
            host=self.cfg.host,
            port=self.cfg.port,
            virtual_host=self.cfg.vhost,
            credentials=pika.PlainCredentials(self.cfg.user, self.cfg.password),
            heartbeat=HEARTBEAT_DETIK,
            blocked_connection_timeout=300,
        )

    def tunggu_skema(self) -> bool:
        """Tunggu migrasi 011. Tanpa ini pesan pertama gagal disimpan dan masuk DLQ."""
        while not self.berhenti:
            if skema_siap():
                return True
            logger.warning(
                "CLOSING CONSUMER MENUNGGU: tabel closing report belum ada atau database belum siap",
                extra={"coba_lagi_detik": JEDA_CEK_SKEMA_DETIK},
            )
            time.sleep(JEDA_CEK_SKEMA_DETIK)
        return False

    def run(self):
        # Belum terhubung ke broker selama menunggu, jadi tidak ada pesan yang tertahan.
        if not self.tunggu_skema():
            logger.info("CLOSING CONSUMER BERHENTI")
            return

        jeda = JEDA_RECONNECT_AWAL
        while not self.berhenti:
            try:
                self.connection = pika.BlockingConnection(self._parameter())
                self.channel = self.connection.channel()
                siapkan_channel(self.channel, self.cfg)
                logger.info(
                    "CLOSING CONSUMER SIAP",
                    extra={"queue": self.cfg.queue, "exchange": self.cfg.exchange, "routing_key": self.cfg.routing_key},
                )
                jeda = JEDA_RECONNECT_AWAL
                self.channel.start_consuming()
            except pika.exceptions.AMQPError as e:
                # Termasuk exchange pengirim belum ada (404) — dicoba lagi,
                # bukan berhenti, supaya container tidak restart berulang.
                if self.berhenti:
                    break
                logger.error(
                    "CLOSING CONSUMER TERPUTUS",
                    extra={"error": f"{type(e).__name__}: {e}", "coba_lagi_detik": jeda},
                )
                time.sleep(jeda)
                jeda = min(jeda * 2, JEDA_RECONNECT_MAKS)
            finally:
                self._tutup()
        logger.info("CLOSING CONSUMER BERHENTI")

    def stop(self, *_):
        """Aman dipanggil dari signal handler: pesan yang sedang diproses diselesaikan dulu."""
        self.berhenti = True
        if self.connection is not None and self.channel is not None:
            self.connection.add_callback_threadsafe(self.channel.stop_consuming)

    def _tutup(self):
        try:
            if self.connection is not None and self.connection.is_open:
                self.connection.close()
        except Exception:
            pass
        self.connection = None
        self.channel = None


def _log_ke_stdout():
    # Logger aplikasi hanya menulis ke file; worker juga perlu terlihat di `docker logs`.
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(build_formatter(settings.LOG_FORMAT))
    logging.getLogger(LOGGER_NAME).addHandler(handler)


def main() -> int:
    _log_ke_stdout()
    try:
        cfg = KonfigurasiConsumer.dari_settings()
    except KonfigurasiTidakLengkap as e:
        logger.error(f"CLOSING CONSUMER TIDAK START: {e}")
        return 1

    worker = Worker(cfg)
    signal.signal(signal.SIGTERM, worker.stop)
    signal.signal(signal.SIGINT, worker.stop)
    worker.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
