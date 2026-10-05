"""Penjaga docker-compose.yml untuk worker consumer closing report (TODO Fase 7.5)."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
SERVICES = COMPOSE["services"]

API = "maharasa-apisales"
CONSUMER = "maharasa-closing-consumer"


def test_consumer_service_ada_dengan_image_yang_sama():
    assert CONSUMER in SERVICES
    assert SERVICES[CONSUMER]["build"] == SERVICES[API]["build"]


def test_consumer_menjalankan_modul_worker_dalam_exec_form():
    """Exec form: python jadi PID 1 dan menerima SIGTERM langsung, bukan lewat sh."""
    assert SERVICES[CONSUMER]["command"] == ["python", "-m", "app.consumers.closing_report_consumer"]


def test_consumer_tidak_menjalankan_migrasi():
    """Migrasi hanya oleh container API (advisory lock tetap ada, tapi satu sumber lebih jelas)."""
    assert "migrate" not in " ".join(SERVICES[CONSUMER]["command"])


def test_consumer_tidak_membuka_port():
    assert "ports" not in SERVICES[CONSUMER]


def test_consumer_terhubung_ke_rabbitmq_dan_postgres():
    assert set(SERVICES[CONSUMER]["networks"]) == {"rabbitmq_net", "postgres_net"}


def test_consumer_restart_otomatis():
    assert SERVICES[CONSUMER]["restart"] == "unless-stopped"


def test_consumer_menulis_log_ke_file_sendiri():
    """Dua container menulis ke logs/api.log yang sama akan saling menyisip."""
    env = SERVICES[CONSUMER]["environment"]
    assert env["LOG_FILE"] != "logs/api.log"
    assert env["LOG_FILE"].startswith("logs/")


def test_consumer_diberi_waktu_menyelesaikan_pesan_saat_berhenti():
    assert SERVICES[CONSUMER]["stop_grace_period"] == "30s"


def test_api_tidak_berubah():
    api = SERVICES[API]
    assert api["ports"] == ["8001:8000"]
    assert "command" not in api
