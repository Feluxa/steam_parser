import json
import os
from pathlib import Path

import psycopg


BASE_DIR = Path(__file__).resolve().parents[1]
CS2_FILE = BASE_DIR / "steam-item-name-ids" / "dump" / "cs2.json"

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "15432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "steam_orders")
POSTGRES_USER = os.getenv("POSTGRES_USER", "steam_orders")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "steam_orders")
SKIN_SUBSTRING = "M4A1-S"


def load_skins() -> list[tuple[int, str]]:
    with CS2_FILE.open("r", encoding="utf-8") as file:
        items = json.load(file)

    return [
        (item_id, name)
        for name, item_id in items.items()
        if SKIN_SUBSTRING in name
    ]


def create_table(connection: psycopg.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE skins (
            id BIGINT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            best_sell NUMERIC(14, 2),
            best_buy NUMERIC(14, 2),
            potential_profit_abs NUMERIC(14, 2),
            potential_profit_percent NUMERIC(14, 2),
            liquidity NUMERIC(14, 2),
            last_update TIMESTAMPTZ
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_skins_last_update
        ON skins (last_update)
        """
    )


def insert_skins(connection: psycopg.Connection, skins: list[tuple[int, str]]) -> None:
    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO skins (id, name)
            VALUES (%s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name
            """,
            skins,
        )


def table_exists(connection: psycopg.Connection) -> bool:
    result = connection.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = 'skins'
        )
        """
    ).fetchone()

    return bool(result[0])


def main() -> None:
    with psycopg.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        dbname=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
    ) as connection:
        if table_exists(connection):
            print("Table skins already exists, init skipped")
            return

        skins = load_skins()
        create_table(connection)
        insert_skins(connection, skins)

    print(f"Inserted or updated {len(skins)} skins")


if __name__ == "__main__":
    main()
