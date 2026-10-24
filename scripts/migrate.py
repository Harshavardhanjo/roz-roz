"""Apply migrations/*.sql in order. Every statement is idempotent (create ... if not exists)."""

from pathlib import Path

import psycopg

from app.config import settings


def main() -> None:
    url = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url, autocommit=True) as conn:
        for path in sorted(Path(__file__).resolve().parent.parent.joinpath("migrations").glob("*.sql")):
            conn.execute(path.read_text())
            print(f"applied {path.name}")


if __name__ == "__main__":
    main()
