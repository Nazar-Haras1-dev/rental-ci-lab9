"""Лаба 8: фікстури regression-набору. БД беремо або з контейнера (за замовчуванням, як у вихідному наборі),
або з локальної PostgreSQL (REGRESSION_DB=local). Перед КОЖНИМ тестом стан БД чиститься."""
import os
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest

from rental.database import connect
from rental.repositories import PostgresEquipmentRepository, PostgresRentalRepository
from rental.service import RentalService

MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "V1__create_tables.sql"
TABLES = ("equipment", "rentals", "rental_items")


class AllowPolicy:
    """Зовнішня перевірка, яка завжди дозволяє оренду."""

    def is_allowed(self, equipment, quantity, days):
        return True


# ===============================================================
# Джерело БД (один раз на запуск)
# ===============================================================
@pytest.fixture(scope="session")
def open_connection():
    """Повертає функцію, яка відкриває НОВЕ з'єднання з тестовою БД."""
    mode = os.getenv("REGRESSION_DB", "container")

    if mode == "local":
        # --- локальна PostgreSQL (змінні DB_*), міграція вже застосована вручну, як у лабі 4 ---
        with connect() as db:
            name = db.info.dbname
            missing = [t for t in TABLES if db.execute("SELECT to_regclass(%s)", (f"public.{t}",)).fetchone()[0] is None]
        if "test" not in name.lower():
            pytest.exit(f"БД '{name}' не схожа на тестову (потрібне слово 'test' у назві).", returncode=2)
        if missing:
            pytest.exit(f"У БД немає таблиць {missing}. Застосуй migrations/V1__create_tables.sql.", returncode=2)
        yield connect
        return

    # --- контейнер PostgreSQL через Testcontainers (потрібен Docker) ---
    try:
        from testcontainers.postgres import PostgresContainer
        container = PostgresContainer("postgres:17.6-alpine")
        container.start()
    except Exception as error:  # noqa: BLE001
        pytest.exit("Не вдалося запустити контейнер PostgreSQL (потрібен Docker). Без Docker запускай з "
                    f"REGRESSION_DB=local.\nДеталі: {error!r}", returncode=2)
    try:
        options = dict(host=container.get_container_host_ip(), port=int(container.get_exposed_port(5432)),
                       user=container.username, password=container.password, dbname=container.dbname, autocommit=True)
        with psycopg.connect(**options) as db:
            db.execute(MIGRATION.read_text(encoding="utf-8"))  # міграція автоматично
        yield lambda: psycopg.connect(**options)
    finally:
        container.stop()


# ===============================================================
# Ізоляція: кожен тест починає з порожньої БД і має свої сервіс та репозиторії
# ===============================================================
def _clean(connection):
    connection.execute("TRUNCATE rental_items, rentals, equipment RESTART IDENTITY CASCADE")


@pytest.fixture
def sut(open_connection):
    with open_connection() as db:
        _clean(db)
        equipment = PostgresEquipmentRepository(db)
        rentals = PostgresRentalRepository(db)
        yield SimpleNamespace(
            db=db, equipment=equipment, rentals=rentals,
            service=RentalService(equipment, rentals, AllowPolicy()),
            open_connection=open_connection,
        )
        _clean(db)
