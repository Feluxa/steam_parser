import os

import psycopg
from psycopg.rows import dict_row


POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "15432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "steam_orders")
POSTGRES_USER = os.getenv("POSTGRES_USER", "steam_orders")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "steam_orders")


def main() -> None:
    with psycopg.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        dbname=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        row_factory=dict_row,
    ) as connection:
        skins = connection.execute(
            """
            SELECT
                id,
                name,
                best_sell,
                best_buy,
                potential_profit_abs,
                potential_profit_percent,
                liquidity,
                last_update
            FROM skins
            ORDER BY last_update DESC NULLS LAST
            LIMIT 10
            """
        ).fetchall()

    for skin in skins:
        print(
            f"{skin['last_update']} | {skin['id']} | {skin['name']} | "
            f"best_sell={skin['best_sell']} | "
            f"best_buy={skin['best_buy']} | "
            f"potential_profit_abs={skin['potential_profit_abs']} | "
            f"potential_profit_percent={skin['potential_profit_percent']} | "
            f"liquidity={skin['liquidity']}"
        )


if __name__ == "__main__":
    main()
