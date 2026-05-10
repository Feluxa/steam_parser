import json
import os
import time
from decimal import Decimal, InvalidOperation
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

import psycopg
from psycopg.rows import dict_row


POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "15432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "steam_orders")
POSTGRES_USER = os.getenv("POSTGRES_USER", "steam_orders")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "steam_orders")

ORDERS_URL = "https://steamcommunity.com/market/itemordershistogram"
REQUEST_TIMEOUT = 30
REQUEST_RETRIES = 3
REQUEST_RETRY_DELAY = 2
LOOP_DELAY = 1
STEAM_FEE_MULTIPLIER = Decimal("1.15")


def get_connection() -> psycopg.Connection:
    return psycopg.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        dbname=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        row_factory=dict_row,
    )


def get_oldest_skin(connection: psycopg.Connection) -> Optional[dict]:
    return connection.execute(
        """
        SELECT id, name
        FROM skins
        ORDER BY last_update ASC NULLS FIRST, id ASC
        LIMIT 1
        """
    ).fetchone()


def get_order_prices(item_nameid: int) -> dict[str, Optional[str]]:
    params = {
        "norender": 1,
        "country": "RU",
        "language": "english",
        "currency": 5,
        "item_nameid": item_nameid,
        "two_factor": 0,
    }
    url = f"{ORDERS_URL}?{urlencode(params)}"

    for attempt in range(1, REQUEST_RETRIES + 1):
        try:
            with urlopen(url, timeout=REQUEST_TIMEOUT) as response:
                data = json.load(response)

            return {
                "sell_order_price": data.get("sell_order_price"),
                "buy_order_price": data.get("buy_order_price"),
            }
        except (HTTPError, URLError, TimeoutError) as error:
            if attempt == REQUEST_RETRIES:
                print(f"Skip item_nameid={item_nameid}: {error}")
                break

            time.sleep(REQUEST_RETRY_DELAY)

    return {
        "sell_order_price": None,
        "buy_order_price": None,
    }


def parse_rub_price(price: Optional[str]) -> Optional[Decimal]:
    if price is None:
        return None

    normalized = (
        price.replace(" руб.", "")
        .replace("руб.", "")
        .replace(" ", "")
        .replace(",", ".")
    )

    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None


def update_skin(
    connection: psycopg.Connection,
    item_nameid: int,
    best_sell: Optional[Decimal],
    best_buy: Optional[Decimal],
    potential_profit_abs: Optional[Decimal],
    potential_profit_percent: Optional[Decimal],
) -> None:
    connection.execute(
        """
        UPDATE skins
        SET
            best_sell = %s,
            best_buy = %s,
            potential_profit_abs = %s,
            potential_profit_percent = %s,
            last_update = NOW()
        WHERE id = %s
        """,
        (
            best_sell,
            best_buy,
            potential_profit_abs,
            potential_profit_percent,
            item_nameid,
        ),
    )


def calculate_potential_profit_abs(
    best_sell: Optional[Decimal],
    best_buy: Optional[Decimal],
) -> Optional[Decimal]:
    if best_sell is None or best_buy is None:
        return None

    return (best_sell - best_buy * STEAM_FEE_MULTIPLIER).quantize(Decimal("0.01"))


def calculate_potential_profit_percent(
    potential_profit_abs: Optional[Decimal],
    best_buy: Optional[Decimal],
) -> Optional[Decimal]:
    if potential_profit_abs is None or best_buy is None or best_buy == 0:
        return None

    return (potential_profit_abs / best_buy * Decimal("100")).quantize(Decimal("0.01"))


def main() -> None:
    with get_connection() as connection:
        while True:
            skin = get_oldest_skin(connection)
            if skin is None:
                print("No skins in database")
                time.sleep(LOOP_DELAY)
                continue

            prices = get_order_prices(skin["id"])
            best_sell = parse_rub_price(prices["sell_order_price"])
            best_buy = parse_rub_price(prices["buy_order_price"])
            potential_profit_abs = calculate_potential_profit_abs(best_sell, best_buy)
            potential_profit_percent = calculate_potential_profit_percent(
                potential_profit_abs,
                best_buy,
            )

            update_skin(
                connection,
                skin["id"],
                best_sell,
                best_buy,
                potential_profit_abs,
                potential_profit_percent,
            )
            connection.commit()

            print(
                f"Updated {skin['name']}: "
                f"best_sell={best_sell}, best_buy={best_buy}, "
                f"potential_profit_abs={potential_profit_abs}, "
                f"potential_profit_percent={potential_profit_percent}"
            )
            time.sleep(LOOP_DELAY)


if __name__ == "__main__":
    main()
