"""Лаба 6: тести REST API. Сервер FastAPI стартує автоматично (або береться вже запущений),
а тести ходять до нього справжніми HTTP-запитами через requests."""
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import psycopg
import pytest
import requests

from rental.database import connect

ROOT = Path(__file__).resolve().parents[2]  # папка sut-b
TABLES = ("equipment", "rentals", "rental_items")


# ===============================================================
# Допоміжне: унікальні коди, щоб тести не залежали від старих даних у БД
# ===============================================================
def make_unique(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:12]}"  # до 40 символів, як вимагає SUT


# ===============================================================
# Невеликий HTTP-клієнт: база адреси + таймаут
# ===============================================================
class Api:
    def __init__(self, base_url):
        self.base_url = base_url
        self.session = requests.Session()

    def get(self, path):
        return self.session.get(self.base_url + path, timeout=10)

    def post(self, path, json=None):
        return self.session.post(self.base_url + path, json=json, timeout=10)


# ===============================================================
# Підготовка сервера
# ===============================================================
def _check_database():
    """Сервер працює з локальною PostgreSQL (змінні DB_*), тому перевіряємо її заздалегідь."""
    try:
        with connect() as db:
            missing = [
                table for table in TABLES
                if db.execute("SELECT to_regclass(%s)", (f"public.{table}",)).fetchone()[0] is None
            ]
    except psycopg.OperationalError as error:
        pytest.exit("Немає підключення до PostgreSQL. Перевір DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD "
                    f"і що сервер БД запущений.\nДеталі: {error}", returncode=2)
    if missing:
        pytest.exit(f"У БД немає таблиць {missing}. Застосуй migrations/V1__create_tables.sql.", returncode=2)


def _wait_until_ready(url, process=None, log=None, seconds=30):
    """Чекаємо не фіксовану паузу, а реальну умову: сервер відповів на запит."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:  # сервер упав одразу після старту
            log.seek(0)
            pytest.exit("Сервер API завершився під час старту:\n" + log.read().decode(errors="replace"), returncode=2)
        try:
            requests.get(url + "/equipment/1", timeout=2)  # будь-яка відповідь (навіть 404) = сервер живий
            return
        except requests.RequestException:
            time.sleep(0.3)
    pytest.exit(f"Сервер API не відповів за {seconds} секунд: {url}", returncode=2)


def _free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="session")
def api_url():
    # --- варіант 1: сервер уже запущений вручну, адреса в змінній API_BASE_URL ---
    external = os.getenv("API_BASE_URL")
    if external:
        url = external.rstrip("/")
        _wait_until_ready(url)
        yield url
        return

    # --- варіант 2 (за замовчуванням): піднімаємо uvicorn самі на вільному порту ---
    _check_database()
    port = _free_port()
    env = os.environ.copy()
    env.pop("RENTAL_POLICY_URL", None)  # без WireMock: працює локальна політика, що дозволяє оренду
    log = tempfile.TemporaryFile()
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "rental.api:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    try:
        url = f"http://127.0.0.1:{port}"
        _wait_until_ready(url, process, log)
        print(f"\n[api] сервер запущено: {url}")
        yield url
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


# ===============================================================
# Фікстури для тестів
# ===============================================================
@pytest.fixture
def api(api_url):
    return Api(api_url)


@pytest.fixture
def unique():
    return make_unique


@pytest.fixture
def make_equipment(api):
    """Створює обладнання через POST /equipment і повертає тіло відповіді (з id)."""
    def make(daily_rate=1000, stock=10, code=None):
        body = {"code": code or make_unique("API-E"), "daily_rate": daily_rate, "stock": stock}
        response = api.post("/equipment", body)
        assert response.status_code == 201, response.text
        return response.json()

    return make


@pytest.fixture
def make_rental(api):
    """Створює оренду через POST /rentals і повертає тіло відповіді (з id)."""
    def make(equipment, quantity=1, days=1, premium=False, reference=None):
        body = {"reference": reference or make_unique("API-R"), "equipment_id": equipment["id"],
                "quantity": quantity, "days": days, "premium": premium}
        response = api.post("/rentals", body)
        assert response.status_code == 201, response.text
        return response.json()

    return make
