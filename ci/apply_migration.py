"""CI-допоміжний скрипт: застосовує migrations/V1__create_tables.sql до тестової БД (параметри DB_* зі середовища).
Якщо таблиці вже є, нічого не робить. Чекає, поки PostgreSQL почне приймати з'єднання."""
import sys
import time
from pathlib import Path

import psycopg

# скрипт лежить у ci/, тому додаємо корінь проєкту, щоб працював `import rental`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rental.database import connect

MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "V1__create_tables.sql"


def wait_for_database(seconds=60):
    """Повторює спроби підключення, поки не вийде або не мине час."""
    deadline = time.monotonic() + seconds
    while True:
        try:
            return connect()
        except psycopg.OperationalError as error:
            if time.monotonic() > deadline:
                sys.exit(f"PostgreSQL недоступна за {seconds} с: {error}")
            time.sleep(1)


def main():
    with wait_for_database() as db:
        exists = db.execute("SELECT to_regclass('public.equipment')").fetchone()[0] is not None
        if exists:
            print("Міграція вже застосована, пропускаю.")
            return
        db.execute(MIGRATION.read_text(encoding="utf-8"))
        tables = [row[0] for row in db.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY 1")]
        print(f"Міграцію застосовано. Таблиці: {', '.join(tables)}")


if __name__ == "__main__":
    main()
