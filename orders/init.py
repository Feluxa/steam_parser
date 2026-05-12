import json
import os
from pathlib import Path

import psycopg

from item_filters import EXCLUDE_NON_WEAPON_ITEMS, should_parse_item


BASE_DIR = Path(__file__).resolve().parents[1]
CS2_FILE = BASE_DIR / "steam-item-name-ids" / "dump" / "cs2.json"

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "15432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "steam_orders")
POSTGRES_USER = os.getenv("POSTGRES_USER", "steam_orders")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "steam_orders")
WEAPON_SUBSTRINGS = (
    "M4A1-S",
    "M4A4",
    "AK-47",
    "Desert Eagle",
    "Glock-18",
    "USP-S",
)


def load_skins() -> list[tuple[int, str]]:
    with CS2_FILE.open("r", encoding="utf-8") as file:
        items = json.load(file)

    return [
        (item_id, name)
        for name, item_id in items.items()
        if any(weapon in name for weapon in WEAPON_SUBSTRINGS)
        and should_parse_item(name)
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


def prune_excluded_skins(connection: psycopg.Connection) -> int:
    if not EXCLUDE_NON_WEAPON_ITEMS:
        return 0

    rows = connection.execute("SELECT id, name FROM skins").fetchall()
    excluded_ids = [(row[0],) for row in rows if not should_parse_item(row[1])]

    if not excluded_ids:
        return 0

    with connection.cursor() as cursor:
        cursor.executemany("DELETE FROM skins WHERE id = %s", excluded_ids)

    return len(excluded_ids)


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
        skins = load_skins()
        if table_exists(connection):
            deleted_count = prune_excluded_skins(connection)
            insert_skins(connection, skins)
            print("Table skins already exists, init skipped")
            print(f"Inserted or updated {len(skins)} skins")
            if deleted_count:
                print(f"Deleted {deleted_count} excluded skins")
            return

        create_table(connection)
        insert_skins(connection, skins)

    print(f"Inserted or updated {len(skins)} skins")


if __name__ == "__main__":
    main()
