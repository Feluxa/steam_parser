import asyncio
import os
import time
from decimal import Decimal
from typing import Any
from urllib.parse import quote, urlencode

import httpx
import psycopg
from fastapi import HTTPException
from psycopg.rows import dict_row

from api import (
    DMARKET_BASE_URL,
    GAME_IDS,
    LOOTFARM_BASE_URL,
    create_dmarket_headers,
    extract_dmarket_order_price,
    extract_marketcsgo_order_price,
    extract_marketcsgo_price,
    first_value,
    get_lootfarm_price_file,
    get_market_base_url,
    parse_decimal,
    parse_dmarket_money,
)


POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "15432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "steam_orders")
POSTGRES_USER = os.getenv("POSTGRES_USER", "steam_orders")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "steam_orders")

ARBITRAGE_REFRESH_GAME = os.getenv("ARBITRAGE_REFRESH_GAME", "cs2")
ARBITRAGE_REFRESH_GAMES = [
    game.strip().lower()
    for game in os.getenv("ARBITRAGE_REFRESH_GAMES", ARBITRAGE_REFRESH_GAME).split(",")
    if game.strip()
]
ARBITRAGE_REFRESH_DELAY = float(os.getenv("ARBITRAGE_REFRESH_DELAY", "60"))
ARBITRAGE_REQUEST_TIMEOUT = float(os.getenv("ARBITRAGE_REQUEST_TIMEOUT", "20"))
ARBITRAGE_DMARKET_PAGE_LIMIT = int(os.getenv("ARBITRAGE_DMARKET_PAGE_LIMIT", "100"))
ARBITRAGE_DMARKET_MAX_PAGES = int(os.getenv("ARBITRAGE_DMARKET_MAX_PAGES", "1000"))
ARBITRAGE_DMARKET_PAGE_DELAY = float(os.getenv("ARBITRAGE_DMARKET_PAGE_DELAY", "1"))
ARBITRAGE_DMARKET_TARGET_BATCH_SIZE = int(os.getenv("ARBITRAGE_DMARKET_TARGET_BATCH_SIZE", "100"))
ARBITRAGE_DMARKET_TARGET_WRITE_CHUNK = int(os.getenv("ARBITRAGE_DMARKET_TARGET_WRITE_CHUNK", "10"))
ARBITRAGE_DMARKET_TARGET_DELAY = float(os.getenv("ARBITRAGE_DMARKET_TARGET_DELAY", "0.3"))


MarketItem = dict[str, dict[str, Decimal | int | None]]

COMMON_DMARKET_TARGET_NAMES = [
    "AK-47 | Redline (Field-Tested)",
    "AWP | Asiimov (Field-Tested)",
    "AK-47 | Slate (Field-Tested)",
    "M4A1-S | Printstream (Field-Tested)",
    "AK-47 | The Empress (Field-Tested)",
    "AWP | Neo-Noir (Field-Tested)",
    "USP-S | Kill Confirmed (Field-Tested)",
    "Desert Eagle | Printstream (Field-Tested)",
    "Glock-18 | Water Elemental (Field-Tested)",
    "M4A4 | Desolate Space (Field-Tested)",
]


def get_connection() -> psycopg.Connection:
    return psycopg.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        dbname=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        row_factory=dict_row,
    )


def create_tables(connection: psycopg.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS marketplace_items (
            service TEXT NOT NULL,
            game TEXT NOT NULL,
            name TEXT NOT NULL,
            normal_price NUMERIC(18, 6),
            order_price NUMERIC(18, 6),
            normal_count INTEGER,
            order_count INTEGER,
            last_update TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            normal_last_update TIMESTAMPTZ,
            order_last_update TIMESTAMPTZ,
            error TEXT,
            PRIMARY KEY (service, game, name)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_marketplace_items_name
        ON marketplace_items (game, name)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_marketplace_items_last_update
        ON marketplace_items (last_update)
        """
    )


def merge_normal_item(items: MarketItem, name: str, price: Decimal | None) -> None:
    if not name or price is None:
        return

    current = items.setdefault(
        name,
        {"normal_price": None, "order_price": None, "normal_count": 0, "order_count": 0},
    )
    current["normal_count"] = int(current["normal_count"] or 0) + 1
    current_price = current["normal_price"]
    if current_price is None or price < current_price:
        current["normal_price"] = price


def merge_order_item(items: MarketItem, name: str, price: Decimal | None) -> None:
    if not name or price is None:
        return

    current = items.setdefault(
        name,
        {"normal_price": None, "order_price": None, "normal_count": 0, "order_count": 0},
    )
    current["order_count"] = int(current["order_count"] or 0) + 1
    current_price = current["order_price"]
    if current_price is None or price > current_price:
        current["order_price"] = price


def extract_dmarket_listing_name(item: dict[str, Any]) -> str | None:
    return first_value(item, ("title", "name", "marketHashName", "market_hash_name"))


def extract_dmarket_listing_price(item: dict[str, Any]) -> Decimal | None:
    price = first_value(item, ("price", "instantPrice", "discountPrice"))
    if isinstance(price, dict):
        parsed = parse_dmarket_money(price)
        if parsed is not None:
            return parsed
    else:
        parsed = first_value(item, ("price", "instantPrice", "discountPrice"))
        if parsed is not None:
            return Decimal(str(parsed)) / Decimal("100")

    return parse_dmarket_money(first_value(item, ("priceUSD", "priceUsd", "usdPrice")))


def extract_dmarket_cursor(payload: dict[str, Any]) -> str | None:
    cursor = first_value(payload, ("cursor", "next", "nextCursor", "nextPageCursor"))
    if cursor:
        return str(cursor)

    total = payload.get("total")
    objects = payload.get("objects", [])
    if isinstance(total, int) and isinstance(objects, list) and objects:
        return None

    return None


async def fetch_marketcsgo_full_market(client: httpx.AsyncClient, game: str) -> MarketItem:
    items: MarketItem = {}
    market_base_url = get_market_base_url(game)

    normal_response = await client.get(f"{market_base_url}/api/v2/prices/USD.json")
    normal_response.raise_for_status()
    normal_payload = normal_response.json()
    normal_raw_items = normal_payload.get("items", normal_payload) if isinstance(normal_payload, dict) else normal_payload
    if isinstance(normal_raw_items, dict):
        normal_iterable = normal_raw_items.values()
    elif isinstance(normal_raw_items, list):
        normal_iterable = normal_raw_items
    else:
        normal_iterable = []

    for raw_item in normal_iterable:
        if not isinstance(raw_item, dict):
            continue

        name = first_value(raw_item, ("market_hash_name", "market_name", "hash_name", "name"))
        if not name:
            continue

        merge_normal_item(items, name, extract_marketcsgo_price(raw_item))

    order_response = await client.get(f"{market_base_url}/api/v2/prices/orders/USD.json")
    order_response.raise_for_status()
    order_payload = order_response.json()
    order_raw_items = order_payload.get("items", order_payload) if isinstance(order_payload, dict) else order_payload
    if isinstance(order_raw_items, dict):
        order_iterable = order_raw_items.values()
    elif isinstance(order_raw_items, list):
        order_iterable = order_raw_items
    else:
        order_iterable = []

    for raw_item in order_iterable:
        if not isinstance(raw_item, dict):
            continue

        name = first_value(raw_item, ("market_hash_name", "market_name", "hash_name", "name"))
        if not name:
            continue

        merge_order_item(items, name, extract_marketcsgo_order_price(raw_item))

    return items


def parse_lootfarm_price(value: Any) -> Decimal | None:
    price = parse_decimal(value)
    if price is None or price <= 0:
        return None

    return price / Decimal("100")


def parse_lootfarm_count(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


async def fetch_lootfarm_full_market(client: httpx.AsyncClient, game: str) -> MarketItem:
    response = await client.get(f"{LOOTFARM_BASE_URL}/{get_lootfarm_price_file(game)}")
    response.raise_for_status()
    payload = response.json()
    raw_items = payload.get("items", payload) if isinstance(payload, dict) else payload
    items: MarketItem = {}

    if isinstance(raw_items, dict):
        iterable = raw_items.values()
    elif isinstance(raw_items, list):
        iterable = raw_items
    else:
        iterable = []

    for raw_item in iterable:
        if not isinstance(raw_item, dict):
            continue

        name = first_value(raw_item, ("name", "market_hash_name", "marketHashName"))
        price = parse_lootfarm_price(first_value(raw_item, ("price", "cost", "value")))
        if not name or price is None:
            continue

        have = parse_lootfarm_count(raw_item.get("have"))
        max_count = parse_lootfarm_count(raw_item.get("max"))
        values = items.setdefault(
            str(name),
            {"normal_price": None, "order_price": None, "normal_count": 0, "order_count": 0},
        )

        if have > 0:
            values["normal_count"] = have
            current_normal = values["normal_price"]
            if current_normal is None or price < current_normal:
                values["normal_price"] = price

        values["order_count"] = max_count - have
        current_order = values["order_price"]
        if current_order is None or price > current_order:
            values["order_price"] = price

    return items


async def refresh_dmarket_full_listings(
    client: httpx.AsyncClient,
    connection: psycopg.Connection,
) -> int:
    game_id = GAME_IDS[ARBITRAGE_REFRESH_GAME]["dmarket"]
    total_items: MarketItem = {}
    cursor = ""
    offset = 0

    for page in range(ARBITRAGE_DMARKET_MAX_PAGES):
        page_items: MarketItem = {}
        params = {
            "gameId": game_id,
            "currency": "USD",
            "limit": ARBITRAGE_DMARKET_PAGE_LIMIT,
            "orderBy": "price",
            "orderDir": "asc",
        }
        if cursor:
            params["cursor"] = cursor
        else:
            params["offset"] = offset

        response = await client.get(
            f"{DMARKET_BASE_URL}/exchange/v1/market/items",
            params=params,
            headers=create_dmarket_headers(
                "GET",
                f"/exchange/v1/market/items?{urlencode(params)}",
            ),
        )
        if response.status_code == 429:
            raise HTTPException(status_code=429, detail="DMarket listing rate limit")
        response.raise_for_status()

        payload = response.json()
        objects = payload.get("objects", [])
        if not objects:
            break

        for item in objects:
            if not isinstance(item, dict):
                continue

            name = extract_dmarket_listing_name(item)
            price = extract_dmarket_listing_price(item)
            if name:
                merge_normal_item(page_items, name, price)
                merge_normal_item(total_items, name, price)

        upsert_market_items(
            connection,
            "dmarket",
            ARBITRAGE_REFRESH_GAME,
            page_items,
            update_normal=True,
            update_orders=False,
        )
        connection.commit()

        next_cursor = extract_dmarket_cursor(payload)
        if not next_cursor:
            total = payload.get("total")
            if isinstance(total, int) and offset + len(objects) < total:
                offset += len(objects)
            else:
                break
        else:
            cursor = next_cursor

        if ARBITRAGE_DMARKET_PAGE_DELAY > 0:
            await asyncio.sleep(ARBITRAGE_DMARKET_PAGE_DELAY)

        print(f"DMarket listings page={page + 1}, collected={len(total_items)}")

    return len(total_items)


def upsert_market_items(
    connection: psycopg.Connection,
    service: str,
    game: str,
    items: MarketItem,
    update_normal: bool,
    update_orders: bool,
    error: str | None = None,
) -> None:
    if not items:
        return

    rows = [
        (
            service,
            game,
            name,
            values.get("normal_price"),
            values.get("order_price"),
            values.get("normal_count"),
            values.get("order_count"),
            error,
        )
        for name, values in items.items()
    ]

    normal_price_set = "normal_price = EXCLUDED.normal_price," if update_normal else "normal_price = marketplace_items.normal_price,"
    normal_count_set = "normal_count = EXCLUDED.normal_count," if update_normal else "normal_count = marketplace_items.normal_count,"
    normal_time_set = "normal_last_update = NOW()," if update_normal else "normal_last_update = marketplace_items.normal_last_update,"
    order_price_set = "order_price = EXCLUDED.order_price," if update_orders else "order_price = marketplace_items.order_price,"
    order_count_set = "order_count = EXCLUDED.order_count," if update_orders else "order_count = marketplace_items.order_count,"
    order_time_set = "order_last_update = NOW()," if update_orders else "order_last_update = marketplace_items.order_last_update,"
    inserted_normal_time = "NOW()" if update_normal else "NULL"
    inserted_order_time = "NOW()" if update_orders else "NULL"

    query = f"""
        INSERT INTO marketplace_items (
            service,
            game,
            name,
            normal_price,
            order_price,
            normal_count,
            order_count,
            last_update,
            normal_last_update,
            order_last_update,
            error
        )
        VALUES (
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            NOW(),
            {inserted_normal_time},
            {inserted_order_time},
            %s
        )
        ON CONFLICT (service, game, name) DO UPDATE SET
            {normal_price_set}
            {order_price_set}
            {normal_count_set}
            {order_count_set}
            {normal_time_set}
            {order_time_set}
            last_update = NOW(),
            error = EXCLUDED.error
    """

    with connection.cursor() as cursor:
        cursor.executemany(query, rows)


def get_dmarket_target_names(connection: psycopg.Connection) -> list[str]:
    common_rows = connection.execute(
        """
        SELECT common_names.name
        FROM unnest(%s::text[]) AS common_names(name)
        LEFT JOIN marketplace_items dmarket
          ON dmarket.game = %s
         AND dmarket.name = common_names.name
         AND dmarket.service = 'dmarket'
        ORDER BY dmarket.order_last_update ASC NULLS FIRST
        LIMIT %s
        """,
        (COMMON_DMARKET_TARGET_NAMES, ARBITRAGE_REFRESH_GAME, ARBITRAGE_DMARKET_TARGET_BATCH_SIZE),
    ).fetchall()
    names = [row["name"] for row in common_rows]

    if len(names) >= ARBITRAGE_DMARKET_TARGET_BATCH_SIZE:
        return names

    remaining = ARBITRAGE_DMARKET_TARGET_BATCH_SIZE - len(names)
    skin_rows = connection.execute(
        """
        SELECT skins.name
        FROM skins
        LEFT JOIN marketplace_items dmarket
          ON dmarket.game = %s
         AND dmarket.name = skins.name
         AND dmarket.service = 'dmarket'
        WHERE skins.name <> ALL(%s)
        ORDER BY dmarket.order_last_update ASC NULLS FIRST,
                 skins.liquidity DESC NULLS LAST,
                 skins.best_sell DESC NULLS LAST,
                 skins.name ASC
        LIMIT %s
        """,
        (ARBITRAGE_REFRESH_GAME, names or [""], remaining),
    ).fetchall()
    names.extend(row["name"] for row in skin_rows)

    if len(names) >= ARBITRAGE_DMARKET_TARGET_BATCH_SIZE:
        return names

    remaining = ARBITRAGE_DMARKET_TARGET_BATCH_SIZE - len(names)
    marketcsgo_rows = connection.execute(
        """
        SELECT marketcsgo.name
        FROM marketplace_items marketcsgo
        LEFT JOIN marketplace_items dmarket
          ON dmarket.game = marketcsgo.game
         AND dmarket.name = marketcsgo.name
         AND dmarket.service = 'dmarket'
        WHERE marketcsgo.game = %s
          AND marketcsgo.service = 'marketcsgo'
          AND marketcsgo.name <> ALL(%s)
        ORDER BY dmarket.order_last_update ASC NULLS FIRST, marketcsgo.normal_price DESC NULLS LAST
        LIMIT %s
        """,
        (ARBITRAGE_REFRESH_GAME, names or [""], remaining),
    ).fetchall()
    names.extend(row["name"] for row in marketcsgo_rows)

    if len(names) >= ARBITRAGE_DMARKET_TARGET_BATCH_SIZE:
        return names

    remaining = ARBITRAGE_DMARKET_TARGET_BATCH_SIZE - len(names)
    dmarket_rows = connection.execute(
        """
        SELECT name
        FROM marketplace_items
        WHERE game = %s
          AND service = 'dmarket'
          AND name <> ALL(%s)
        ORDER BY order_last_update ASC NULLS FIRST, normal_price DESC NULLS LAST, name ASC
        LIMIT %s
        """,
        (ARBITRAGE_REFRESH_GAME, names or [""], remaining),
    ).fetchall()

    return [*names, *[row["name"] for row in dmarket_rows]]


async def fetch_dmarket_targets(
    client: httpx.AsyncClient,
    names: list[str],
) -> MarketItem:
    items: MarketItem = {}
    game_id = GAME_IDS[ARBITRAGE_REFRESH_GAME]["dmarket"]

    for name in names:
        query_string = urlencode({"currency": "USD"})
        encoded_name = quote(name, safe="")
        request_path = f"/marketplace-api/v1/targets-by-title/{game_id}/{encoded_name}?{query_string}"
        signing_path = f"/marketplace-api/v1/targets-by-title/{game_id}/{name}?{query_string}"
        response = await client.get(
            f"{DMARKET_BASE_URL}{request_path}",
            headers=create_dmarket_headers("GET", signing_path),
        )
        if response.status_code == 401:
            response = await client.get(
                f"{DMARKET_BASE_URL}{request_path}",
                headers=create_dmarket_headers("GET", request_path),
            )
        if response.status_code == 429:
            raise HTTPException(status_code=429, detail="DMarket targets rate limit")
        response.raise_for_status()

        price = extract_dmarket_order_price(response.json(), name)
        values = items.setdefault(
            name,
            {"normal_price": None, "order_price": None, "normal_count": 0, "order_count": 0},
        )
        values["order_price"] = price
        values["order_count"] = 1 if price is not None else 0

        if ARBITRAGE_DMARKET_TARGET_DELAY > 0:
            await asyncio.sleep(ARBITRAGE_DMARKET_TARGET_DELAY)

    return items


async def refresh_full_markets() -> None:
    timeout = httpx.Timeout(ARBITRAGE_REQUEST_TIMEOUT)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        with get_connection() as connection:
            create_tables(connection)
            connection.commit()

            for game in ARBITRAGE_REFRESH_GAMES:
                if game not in GAME_IDS:
                    print(f"Unknown arbitrage game skipped: {game}")
                    continue

                marketcsgo_items = await fetch_marketcsgo_full_market(client, game)
                upsert_market_items(
                    connection,
                    "marketcsgo",
                    game,
                    marketcsgo_items,
                    update_normal=True,
                    update_orders=True,
                )
                connection.commit()
                print(f"MarketCSGO {game} full market updated: {len(marketcsgo_items)} items")

                lootfarm_items = await fetch_lootfarm_full_market(client, game)
                upsert_market_items(
                    connection,
                    "lootfarm",
                    game,
                    lootfarm_items,
                    update_normal=True,
                    update_orders=True,
                )
                connection.commit()
                print(f"LootFarm {game} full market updated: {len(lootfarm_items)} items")

            if "cs2" in ARBITRAGE_REFRESH_GAMES:
                target_names = get_dmarket_target_names(connection)
                target_count = 0
                chunk_size = max(1, ARBITRAGE_DMARKET_TARGET_WRITE_CHUNK)
                for index in range(0, len(target_names), chunk_size):
                    chunk_names = target_names[index:index + chunk_size]
                    dmarket_targets = await fetch_dmarket_targets(client, chunk_names)
                    upsert_market_items(
                        connection,
                        "dmarket",
                        "cs2",
                        dmarket_targets,
                        update_normal=False,
                        update_orders=True,
                    )
                    connection.commit()
                    target_count += len(dmarket_targets)
                    print(f"DMarket targets updated: {target_count}/{len(target_names)} items")

                dmarket_count = await refresh_dmarket_full_listings(client, connection)
                print(f"DMarket listings updated: {dmarket_count} items")


def main() -> None:
    while True:
        started_at = time.monotonic()
        try:
            asyncio.run(refresh_full_markets())
        except psycopg.OperationalError as error:
            print(f"Postgres is not ready: {error}")
        except Exception as error:
            print(f"Arbitrage loop failed: {error}")

        elapsed = time.monotonic() - started_at
        time.sleep(max(ARBITRAGE_REFRESH_DELAY - elapsed, 0))


if __name__ == "__main__":
    main()
