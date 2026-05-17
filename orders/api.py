import os
import asyncio
import time
from decimal import Decimal
from typing import Any
from urllib.parse import quote, urlencode

import httpx
import psycopg
from nacl.bindings import crypto_sign
from nacl.signing import SigningKey
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from psycopg.rows import dict_row


POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "15432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "steam_orders")
POSTGRES_USER = os.getenv("POSTGRES_USER", "steam_orders")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "steam_orders")

PAGE_SIZE = 100
ARBITRAGE_PAGE_SIZE = 50
ARBITRAGE_MAX_SOURCE_ITEMS = 300
ARBITRAGE_REQUEST_TIMEOUT = float(os.getenv("ARBITRAGE_REQUEST_TIMEOUT", "12"))
ARBITRAGE_DMARKET_ITEM_DELAY = float(os.getenv("ARBITRAGE_DMARKET_ITEM_DELAY", "1"))
DMARKET_BASE_URL = os.getenv("DMARKET_BASE_URL", "https://api.dmarket.com")
MARKETCSGO_BASE_URL = os.getenv("MARKETCSGO_BASE_URL", "https://market.csgo.com")
LOOTFARM_BASE_URL = os.getenv("LOOTFARM_BASE_URL", "https://loot.farm")
DMARKET_PUBLIC_KEY = os.getenv("DMARKET_PUBLIC_KEY", "")
DMARKET_SECRET_KEY = os.getenv("DMARKET_SECRET_KEY", "")
MARKETCSGO_API_KEY = os.getenv("MARKETCSGO_API_KEY", "")
SERVICE_FEES = {
    "dmarket": Decimal(os.getenv("ARBITRAGE_DMARKET_FEE", "0.02")),
    "marketcsgo": Decimal(os.getenv("ARBITRAGE_MARKETCSGO_FEE", "0.05")),
    "lootfarm": Decimal(os.getenv("ARBITRAGE_LOOTFARM_FEE", "0.05")),
}
SERVICE_LABELS = {
    "dmarket": "DMarket",
    "marketcsgo": "MarketCSGO",
    "lootfarm": "LootFarm",
}
ALLOWED_SERVICES = set(SERVICE_LABELS)
GAME_IDS = {
    "all": {"dmarket": "a8db", "marketcsgo": "730", "lootfarm": "730"},
    "cs2": {"dmarket": "a8db", "marketcsgo": "730", "lootfarm": "730"},
    "rust": {"marketcsgo": "252490", "lootfarm": "252490"},
    "tf2": {"marketcsgo": "440", "lootfarm": "440"},
}
MARKET_SERVICE_BASE_URLS = {
    "cs2": MARKETCSGO_BASE_URL,
    "rust": os.getenv("MARKETRUST_BASE_URL", "https://rust.tm"),
    "tf2": os.getenv("MARKETTF2_BASE_URL", "https://tf2.tm"),
}
LOOTFARM_PRICE_FILES = {
    "cs2": "fullprice.json",
    "rust": "fullpriceRUST.json",
    "tf2": "fullpriceTF2.json",
}
ALLOWED_PRICE_TYPES = {"normal", "orders"}
D_MARKET_EXTERIORS = {
    "Factory New": "factory-new",
    "Minimal Wear": "minimal-wear",
    "Field-Tested": "field-tested",
    "Well-Worn": "well-worn",
    "Battle-Scarred": "battle-scarred",
}
ALLOWED_FIELDS = {
    "id",
    "name",
    "best_sell",
    "best_buy",
    "potential_profit_abs",
    "potential_profit_percent",
    "liquidity",
    "last_update",
}
ALLOWED_ORDER_TYPES = {"asc", "desc"}
FILTERABLE_FIELDS = {
    "name": {"contains", "not_null"},
    "best_sell": {"min", "max", "not_null"},
    "potential_profit_abs": {"min", "max", "not_null"},
    "potential_profit_percent": {"min", "max", "not_null"},
    "liquidity": {"min", "max", "not_null"},
}

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SortRequest(BaseModel):
    field: str = "last_update"
    order_type: str = "desc"


class SearchRequest(BaseModel):
    page: int = Field(1, ge=1)
    sort: SortRequest = Field(default_factory=SortRequest)
    filters: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ArbitrageRequest(BaseModel):
    game: str = "all"
    first_service: str = "marketcsgo"
    second_service: str = "dmarket"
    first_price_types: list[str] = Field(default_factory=lambda: ["normal"])
    second_price_types: list[str] = Field(default_factory=lambda: ["orders"])
    lootfarm_no_overstock: bool = True
    sort: SortRequest = Field(default_factory=lambda: SortRequest(field="profit", order_type="desc"))
    filters: dict[str, dict[str, Any]] = Field(default_factory=dict)
    page: int = Field(1, ge=1)


def get_connection() -> psycopg.Connection:
    return psycopg.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        dbname=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        row_factory=dict_row,
    )


def serialize_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)

    return value


def decimal_to_float(value: Decimal | None) -> float | None:
    if value is None:
        return None

    return float(value)


def parse_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None

    try:
        return Decimal(str(value))
    except Exception:
        return None


def parse_usd_price(value: Any) -> Decimal | None:
    return parse_decimal(value)


def first_value(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in data:
            return data[key]

    return None


def create_dmarket_headers(method: str, request_path: str, body: str = "") -> dict[str, str]:
    if not DMARKET_PUBLIC_KEY or not DMARKET_SECRET_KEY:
        return {}

    nonce = str(int(time.time()))
    signing_payload = f"{method.upper()}{request_path}{body}{nonce}"
    secret_key = DMARKET_SECRET_KEY.strip().removeprefix("0x")
    try:
        secret_key_bytes = bytes.fromhex(secret_key)
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail="DMARKET_SECRET_KEY must be a hex-encoded Ed25519 key",
        ) from error

    if len(secret_key_bytes) == 64:
        signature = crypto_sign(signing_payload.encode("utf-8"), secret_key_bytes)[:64].hex()
    elif len(secret_key_bytes) == 32:
        signing_key = SigningKey(secret_key_bytes)
        signature = signing_key.sign(signing_payload.encode("utf-8")).signature.hex()
    else:
        raise HTTPException(
            status_code=400,
            detail="DMARKET_SECRET_KEY must be a 32-byte hex seed or 64-byte hex private key",
        )

    return {
        "X-Api-Key": DMARKET_PUBLIC_KEY,
        "X-Request-Sign": f"dmar ed25519 {signature}",
        "X-Sign-Date": nonce,
    }


def validate_sort(field: str, order_type: str) -> tuple[str, str]:
    field = field.lower()
    order_type = order_type.lower()

    if field not in ALLOWED_FIELDS:
        raise HTTPException(
            status_code=400,
            detail=f"field must be one of: {', '.join(sorted(ALLOWED_FIELDS))}",
        )

    if order_type not in ALLOWED_ORDER_TYPES:
        raise HTTPException(
            status_code=400,
            detail="order_type must be asc or desc",
        )

    return field, order_type


def build_where_clause(
    filters: dict[str, dict[str, Any]],
) -> tuple[str, list[Any]]:
    clauses = []
    values = []

    for raw_field, field_filter in filters.items():
        field = raw_field.lower()
        if field not in FILTERABLE_FIELDS:
            raise HTTPException(
                status_code=400,
                detail=f"filter field must be one of: {', '.join(sorted(FILTERABLE_FIELDS))}",
            )

        allowed_operations = FILTERABLE_FIELDS[field]

        if not isinstance(field_filter, dict):
            raise HTTPException(
                status_code=400,
                detail=f"{field} filter must be an object",
            )

        for operation, value in field_filter.items():
            operation = operation.lower()
            if operation not in allowed_operations:
                raise HTTPException(
                    status_code=400,
                    detail=f"{field} does not support {operation}",
                )

            if operation == "min":
                clauses.append(f"{field} >= %s")
                values.append(value)
            elif operation == "max":
                clauses.append(f"{field} <= %s")
                values.append(value)
            elif operation == "not_null" and value:
                clauses.append(f"{field} IS NOT NULL")
            elif operation == "contains" and value:
                clauses.append(f"{field} ILIKE %s")
                values.append(f"%{value}%")

    if not clauses:
        return "", values

    return f"WHERE {' AND '.join(clauses)}", values


def fetch_skins(
    page: int,
    field: str,
    order_type: str,
    filters: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    field, order_type = validate_sort(field, order_type)
    where_clause, filter_values = build_where_clause(filters or {})

    offset = (page - 1) * PAGE_SIZE
    nulls_order = "NULLS FIRST" if order_type == "asc" else "NULLS LAST"
    query = f"""
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
        {where_clause}
        ORDER BY {field} {order_type.upper()} {nulls_order}, id ASC
        LIMIT %s OFFSET %s
    """

    with get_connection() as connection:
        rows = connection.execute(
            query,
            (*filter_values, PAGE_SIZE, offset),
        ).fetchall()

    return {
        "page": page,
        "page_size": PAGE_SIZE,
        "field": field,
        "order_type": order_type,
        "items": [
            {key: serialize_value(value) for key, value in row.items()}
            for row in rows
        ],
    }


def fetch_skin_names(limit: int = ARBITRAGE_MAX_SOURCE_ITEMS) -> list[str]:
    query = """
        SELECT name
        FROM skins
        WHERE name IS NOT NULL
        ORDER BY liquidity DESC NULLS LAST, last_update DESC NULLS LAST, id ASC
        LIMIT %s
    """

    with get_connection() as connection:
        rows = connection.execute(query, (limit,)).fetchall()

    return [row["name"] for row in rows if row.get("name")]


def count_skins() -> int:
    with get_connection() as connection:
        row = connection.execute("SELECT COUNT(*) AS count FROM skins WHERE name IS NOT NULL").fetchone()

    return row["count"]


def count_marketplace_names(game: str) -> int:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT COUNT(DISTINCT name) AS count
            FROM marketplace_items
            WHERE game = %s
            """,
            (game,),
        ).fetchone()

    return row["count"]


def parse_dmarket_money(value: Any) -> Decimal | None:
    if isinstance(value, dict):
        amount = parse_decimal(first_value(value, ("amount", "value")))
        if amount is not None:
            return amount / Decimal("100")

        usd_amount = parse_decimal(first_value(value, ("USD", "usd")))
        if usd_amount is not None:
            return usd_amount / Decimal("100")

    amount = parse_decimal(value)
    if amount is None:
        return None

    return amount / Decimal("100")


def extract_dmarket_item_price(item: dict[str, Any]) -> Decimal | None:
    price = first_value(item, ("price", "instantPrice", "discountPrice"))
    parsed_price = parse_dmarket_money(price)
    if parsed_price is not None:
        return parsed_price

    return parse_usd_price(first_value(item, ("priceUSD", "priceUsd", "usdPrice")))


def is_generic_dmarket_order(data: dict[str, Any]) -> bool:
    attributes = data.get("attributes")
    if not isinstance(attributes, dict):
        return True

    for value in attributes.values():
        if value is None:
            continue
        if str(value).lower() != "any":
            return False

    return True


def is_matching_dmarket_order_title(data: dict[str, Any], expected_title: str | None) -> bool:
    if not expected_title:
        return True

    order_title = first_value(data, ("title", "name", "marketHashName", "market_hash_name"))
    if not order_title:
        return True

    return str(order_title).strip() == expected_title.strip()


def extract_dmarket_order_price(data: Any, expected_title: str | None = None) -> Decimal | None:
    if isinstance(data, list):
        prices = [
            extract_dmarket_order_price(item, expected_title)
            for item in data
            if isinstance(item, dict)
        ]
        prices = [price for price in prices if price is not None]
        return max(prices) if prices else None

    if not isinstance(data, dict):
        return None

    if not is_matching_dmarket_order_title(data, expected_title):
        return None

    if not is_generic_dmarket_order(data):
        return None

    price = parse_dmarket_money(
        first_value(data, ("price", "amount", "targetPrice", "purchasePrice")),
    )
    if price is not None:
        return price

    for key in ("orders", "targets", "items", "objects"):
        nested = data.get(key)
        if nested:
            price = extract_dmarket_order_price(nested, expected_title)
            if price is not None:
                return price

    return None


def get_market_base_url(game: str) -> str:
    return MARKET_SERVICE_BASE_URLS.get(game, MARKETCSGO_BASE_URL)


def get_lootfarm_price_file(game: str) -> str:
    return LOOTFARM_PRICE_FILES.get(game, LOOTFARM_PRICE_FILES["cs2"])


def get_steam_app_id(game: str, service: str) -> str:
    return GAME_IDS.get(game, GAME_IDS["cs2"]).get(service, "730")


def get_marketplace_item_url(service: str, name: str, game: str = "cs2") -> str:
    encoded_name = quote(name, safe="")

    if service == "marketcsgo":
        if game in {"rust", "tf2"}:
            return f"{get_market_base_url(game)}/?search={encoded_name}"

        return f"{get_market_base_url(game)}/en/item/{encoded_name}"

    if service == "dmarket":
        return get_dmarket_item_url(name)

    if service == "lootfarm":
        return f"https://loot.farm/#skin={get_steam_app_id(game, service)}_{encoded_name}"

    return ""


def get_dmarket_item_url(name: str) -> str:
    title = name
    params = {
        "title": title,
        "category": "stattrak" if title.startswith("StatTrak") else "normal",
    }

    if title.startswith("StatTrak"):
        title = title.replace("StatTrak™ ", "", 1).replace("StatTrak ", "", 1)
        params["title"] = title

    for exterior, slug in D_MARKET_EXTERIORS.items():
        suffix = f" ({exterior})"
        if title.endswith(suffix):
            params["title"] = title[: -len(suffix)]
            params["exterior"] = slug
            break

    return f"https://dmarket.com/ingame-items/item-list/csgo-skins?{urlencode(params)}"


def normalize_marketcsgo_name(item: dict[str, Any]) -> str | None:
    return first_value(
        item,
        (
            "market_hash_name",
            "market_name",
            "hash_name",
            "name",
        ),
    )


def extract_marketcsgo_price(item: dict[str, Any]) -> Decimal | None:
    return parse_usd_price(
        first_value(
            item,
            (
                "price",
                "price_usd",
                "priceUSD",
                "min_price",
                "sell_price",
                "best_sell",
                "value",
            ),
        ),
    )


def extract_marketcsgo_order_price(item: dict[str, Any]) -> Decimal | None:
    price = parse_usd_price(
        first_value(
            item,
            (
                "buy_order",
                "bid",
                "best_bid",
                "max_bid",
                "highest_buy_order",
            ),
        ),
    )
    if price is not None:
        return price

    return parse_usd_price(first_value(item, ("price", "price_usd", "priceUSD")))


def build_marketcsgo_price_index(data: Any, price_field: str = "normal") -> dict[str, Decimal]:
    items = data.get("items", data) if isinstance(data, dict) else data
    result: dict[str, Decimal] = {}

    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue

            name = normalize_marketcsgo_name(item)
            price = (
                extract_marketcsgo_order_price(item)
                if price_field == "orders"
                else extract_marketcsgo_price(item)
            )
            if name and price is not None:
                current_price = result.get(name)
                result[name] = min(current_price, price) if current_price else price
    elif isinstance(items, dict):
        for name, raw_item in items.items():
            if isinstance(raw_item, dict):
                name = normalize_marketcsgo_name(raw_item) or str(name)
                price = (
                    extract_marketcsgo_order_price(raw_item)
                    if price_field == "orders"
                    else extract_marketcsgo_price(raw_item)
                )
            else:
                price = parse_usd_price(raw_item)

            if price is not None:
                result[str(name)] = price

    return result


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


def build_lootfarm_price_index(data: Any) -> dict[str, dict[str, Decimal | None]]:
    raw_items = data.get("items", data) if isinstance(data, dict) else data
    result: dict[str, dict[str, Decimal | None]] = {}
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
        current = result.setdefault(str(name), {"normal": None, "orders": None})

        if have > 0:
            normal_price = current["normal"]
            current["normal"] = min(normal_price, price) if normal_price is not None else price

        order_price = current["orders"]
        current["orders"] = max(order_price, price) if order_price is not None else price

    return result


async def fetch_dmarket_prices(
    client: httpx.AsyncClient,
    names: list[str],
    price_types: set[str],
    game: str,
) -> dict[str, dict[str, Decimal | None]]:
    game_id = GAME_IDS[game]["dmarket"]
    result = {
        name: {"normal": None, "orders": None}
        for name in names
    }

    for name in names:
        if ARBITRAGE_DMARKET_ITEM_DELAY > 0:
            await asyncio.sleep(ARBITRAGE_DMARKET_ITEM_DELAY)

        if "normal" in price_types:
            response = await client.get(
                f"{DMARKET_BASE_URL}/exchange/v1/market/items",
                params={
                    "gameId": game_id,
                    "title": name,
                    "currency": "USD",
                    "limit": 1,
                    "orderBy": "price",
                    "orderDir": "asc",
                },
            )
            if response.status_code == 429:
                raise HTTPException(status_code=429, detail="DMarket rate limit")
            if response.status_code < 400:
                payload = response.json()
                objects = payload.get("objects", [])
                if objects:
                    exact_objects = [
                        item
                        for item in objects
                        if item.get("title") == name or item.get("name") == name
                    ]
                    result[name]["normal"] = extract_dmarket_item_price(
                        exact_objects[0] if exact_objects else objects[0],
                    )

        if "orders" in price_types:
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
            if response.status_code in {401, 429}:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"DMarket orders returned {response.status_code}",
                )
            if response.status_code < 400:
                result[name]["orders"] = extract_dmarket_order_price(response.json(), name)

    return result


async def fetch_marketcsgo_prices(
    client: httpx.AsyncClient,
    names: list[str],
    price_types: set[str],
    game: str = "cs2",
) -> dict[str, dict[str, Decimal | None]]:
    result = {
        name: {"normal": None, "orders": None}
        for name in names
    }

    market_base_url = get_market_base_url(game)
    if "orders" in price_types:
        orders_response = await client.get(f"{market_base_url}/api/v2/prices/orders/USD.json")
        orders_response.raise_for_status()
        order_prices = build_marketcsgo_price_index(orders_response.json(), price_field="orders")
        normal_prices = {}
        if "normal" in price_types:
            normal_response = await client.get(f"{market_base_url}/api/v2/prices/USD.json")
            normal_response.raise_for_status()
            normal_prices = build_marketcsgo_price_index(normal_response.json())
        for name in names:
            if "normal" in price_types:
                result[name]["normal"] = normal_prices.get(name)
            result[name]["orders"] = order_prices.get(name)
    elif "normal" in price_types:
        response = await client.get(f"{market_base_url}/api/v2/prices/USD.json")
        response.raise_for_status()
        normal_prices = build_marketcsgo_price_index(response.json())
        for name in names:
            result[name]["normal"] = normal_prices.get(name)

    return result


async def fetch_lootfarm_prices(
    client: httpx.AsyncClient,
    names: list[str],
    game: str = "cs2",
) -> dict[str, dict[str, Decimal | None]]:
    result = {
        name: {"normal": None, "orders": None}
        for name in names
    }

    response = await client.get(f"{LOOTFARM_BASE_URL}/{get_lootfarm_price_file(game)}")
    response.raise_for_status()
    prices = build_lootfarm_price_index(response.json())
    for name in names:
        item_prices = prices.get(name, {})
        result[name]["normal"] = item_prices.get("normal")
        result[name]["orders"] = item_prices.get("orders")

    return result


async def fetch_service_prices(
    service: str,
    names: list[str],
    price_types: set[str],
    game: str,
) -> dict[str, dict[str, Decimal | None]]:
    timeout = httpx.Timeout(ARBITRAGE_REQUEST_TIMEOUT)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        if service == "dmarket":
            return await fetch_dmarket_prices(client, names, price_types, game)

        if service == "marketcsgo":
            return await fetch_marketcsgo_prices(client, names, price_types, game)

        if service == "lootfarm":
            return await fetch_lootfarm_prices(client, names, game)

    raise HTTPException(status_code=400, detail=f"unknown service: {service}")


def build_arbitrage_rows(
    names: list[str],
    first_service: str,
    second_service: str,
    first_price_types: set[str],
    second_price_types: set[str],
    first_prices: dict[str, dict[str, Decimal | None]],
    second_prices: dict[str, dict[str, Decimal | None]],
) -> list[dict[str, Any]]:
    rows = []

    for name in names:
        for buy_type in sorted(first_price_types):
            buy_price = first_prices.get(name, {}).get(buy_type)
            if buy_price is None:
                continue

            for sell_type in sorted(second_price_types):
                sell_price = second_prices.get(name, {}).get(sell_type)
                if sell_price is None:
                    continue

                fee = SERVICE_FEES[second_service]
                net_sell = sell_price * (Decimal("1") - fee)
                profit = net_sell - buy_price
                profit_percent = (profit / buy_price * Decimal("100")) if buy_price > 0 else None

                rows.append(
                    {
                        "name": name,
                        "buy_service": first_service,
                        "buy_service_label": SERVICE_LABELS[first_service],
                        "buy_type": buy_type,
                        "buy_price": decimal_to_float(buy_price),
                        "sell_service": second_service,
                        "sell_service_label": SERVICE_LABELS[second_service],
                        "sell_type": sell_type,
                        "sell_price": decimal_to_float(sell_price),
                        "sell_fee_percent": decimal_to_float(fee * Decimal("100")),
                        "net_sell_price": decimal_to_float(net_sell),
                        "profit": decimal_to_float(profit),
                        "profit_percent": decimal_to_float(profit_percent),
                    },
                )

    return sorted(rows, key=lambda row: row["profit"], reverse=True)


def count_price_matches(
    prices: dict[str, dict[str, Decimal | None]],
    price_types: set[str],
) -> dict[str, int]:
    return {
        price_type: sum(
            1
            for item_prices in prices.values()
            if item_prices.get(price_type) is not None
        )
        for price_type in sorted(price_types)
    }


def count_cached_price_matches(
    service: str,
    game: str,
    price_types: set[str],
) -> dict[str, int]:
    result = {}
    with get_connection() as connection:
        for price_type in sorted(price_types):
            column = "normal_price" if price_type == "normal" else "order_price"
            row = connection.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM marketplace_items
                WHERE service = %s
                  AND game = %s
                  AND {column} IS NOT NULL
                """,
                (service, game),
            ).fetchone()
            result[price_type] = row["count"]

    return result


def build_arbitrage_sql_filters(filters: dict[str, dict[str, Any]]) -> tuple[str, list[Any]]:
    if not filters:
        return "", []

    filter_fields = {
        "name",
        "buy_price",
        "sell_price",
        "net_sell_price",
        "profit",
        "profit_percent",
    }
    clauses = []
    values = []

    for raw_field, field_filter in filters.items():
        field = raw_field.lower()
        if field not in filter_fields:
            raise HTTPException(
                status_code=400,
                detail=f"arbitrage filter field must be one of: {', '.join(sorted(filter_fields))}",
            )

        if not isinstance(field_filter, dict):
            raise HTTPException(status_code=400, detail=f"{field} filter must be an object")

        contains = field_filter.get("contains")
        min_value = parse_decimal(field_filter.get("min"))
        max_value = parse_decimal(field_filter.get("max"))
        not_null = bool(field_filter.get("not_null"))

        if contains:
            clauses.append(f"{field} ILIKE %s")
            values.append(f"%{contains}%")

        if min_value is not None:
            clauses.append(f"{field} >= %s")
            values.append(min_value)

        if max_value is not None:
            clauses.append(f"{field} <= %s")
            values.append(max_value)

        if not_null:
            clauses.append(f"{field} IS NOT NULL")

    if not clauses:
        return "", []

    return f"WHERE {' AND '.join(clauses)}", values


def validate_arbitrage_sort(field: str, order_type: str) -> tuple[str, str]:
    sort_fields = {
        "name": "name",
        "buy_price": "buy_price",
        "sell_price": "sell_price",
        "net_sell_price": "net_sell_price",
        "profit": "profit",
        "profit_percent": "profit_percent",
    }
    field = field.lower()
    order_type = order_type.lower()

    if field not in sort_fields:
        raise HTTPException(
            status_code=400,
            detail=f"arbitrage sort field must be one of: {', '.join(sorted(sort_fields))}",
        )

    if order_type not in ALLOWED_ORDER_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"sort order_type must be one of: {', '.join(sorted(ALLOWED_ORDER_TYPES))}",
        )

    return sort_fields[field], order_type


def fetch_cached_arbitrage_rows(
    first_service: str,
    second_service: str,
    game: str,
    first_price_types: set[str],
    second_price_types: set[str],
    filters: dict[str, dict[str, Any]],
    page: int,
    lootfarm_no_overstock: bool,
    sort_field: str,
    sort_order: str,
) -> tuple[list[dict[str, Any]], int]:
    price_column = {
        "normal": "normal_price",
        "orders": "order_price",
    }
    sell_fee = SERVICE_FEES[second_service]
    select_queries = []
    values: list[Any] = []

    for buy_type in sorted(first_price_types):
        for sell_type in sorted(second_price_types):
            buy_column = price_column[buy_type]
            sell_column = price_column[sell_type]
            select_queries.append(
                f"""
                SELECT
                    first_items.name,
                    %s AS buy_type,
                    first_items.{buy_column} AS buy_price,
                    first_items.normal_count AS buy_normal_count,
                    first_items.order_count AS buy_order_count,
                    %s AS sell_type,
                    second_items.{sell_column} AS sell_price,
                    second_items.normal_count AS sell_normal_count,
                    second_items.order_count AS sell_order_count,
                    second_items.{sell_column} * (1 - %s) AS net_sell_price,
                    second_items.{sell_column} * (1 - %s) - first_items.{buy_column} AS profit,
                    CASE
                        WHEN first_items.{buy_column} > 0 THEN
                            (second_items.{sell_column} * (1 - %s) - first_items.{buy_column})
                            / first_items.{buy_column} * 100
                        ELSE NULL
                    END AS profit_percent
                FROM marketplace_items first_items
                JOIN marketplace_items second_items
                  ON second_items.game = first_items.game
                 AND second_items.name = first_items.name
                WHERE first_items.service = %s
                  AND first_items.game = %s
                  AND first_items.{buy_column} IS NOT NULL
                  AND second_items.service = %s
                  AND second_items.{sell_column} IS NOT NULL
                """
            )
            values.extend([
                buy_type,
                sell_type,
                sell_fee,
                sell_fee,
                sell_fee,
                first_service,
                game,
                second_service,
            ])
            if lootfarm_no_overstock:
                if first_service == "lootfarm" and buy_type == "orders":
                    select_queries[-1] += " AND first_items.order_count > 0"
                if second_service == "lootfarm" and sell_type == "orders":
                    select_queries[-1] += " AND second_items.order_count > 0"

    where_clause, filter_values = build_arbitrage_sql_filters(filters)
    offset = (page - 1) * ARBITRAGE_PAGE_SIZE
    cte = f"""
        WITH opportunities AS (
            {' UNION ALL '.join(select_queries)}
        )
    """
    query = f"""
        {cte}
        SELECT *
        FROM opportunities
        {where_clause}
        ORDER BY {sort_field} {sort_order.upper()} NULLS LAST, name ASC
        LIMIT %s OFFSET %s
    """
    count_query = f"""
        {cte}
        SELECT COUNT(*) AS count
        FROM opportunities
        {where_clause}
    """

    with get_connection() as connection:
        total_row = connection.execute(
            count_query,
            (*values, *filter_values),
        ).fetchone()
        rows = connection.execute(
            query,
            (*values, *filter_values, ARBITRAGE_PAGE_SIZE, offset),
        ).fetchall()

    return [
        {
            "name": row["name"],
            "buy_service": first_service,
            "buy_service_label": SERVICE_LABELS[first_service],
            "buy_type": row["buy_type"],
            "buy_price": decimal_to_float(row["buy_price"]),
            "buy_url": get_marketplace_item_url(first_service, row["name"], game),
            "buy_overstock": (
                first_service == "lootfarm"
                and row["buy_type"] == "orders"
                and (row["buy_order_count"] is None or row["buy_order_count"] <= 0)
            ),
            "sell_service": second_service,
            "sell_service_label": SERVICE_LABELS[second_service],
            "sell_type": row["sell_type"],
            "sell_price": decimal_to_float(row["sell_price"]),
            "sell_url": get_marketplace_item_url(second_service, row["name"], game),
            "sell_overstock": (
                second_service == "lootfarm"
                and row["sell_type"] == "orders"
                and (row["sell_order_count"] is None or row["sell_order_count"] <= 0)
            ),
            "lootfarm_stock_remaining": (
                max(0, int(row["sell_order_count"] or 0))
                if second_service == "lootfarm" and row["sell_type"] == "orders"
                else None
            ),
            "lootfarm_stock_limit": (
                max(0, int(row["sell_normal_count"] or 0) + int(row["sell_order_count"] or 0))
                if second_service == "lootfarm" and row["sell_type"] == "orders"
                else None
            ),
            "sell_fee_percent": decimal_to_float(sell_fee * Decimal("100")),
            "net_sell_price": decimal_to_float(row["net_sell_price"]),
            "profit": decimal_to_float(row["profit"]),
            "profit_percent": decimal_to_float(row["profit_percent"]),
        }
        for row in rows
    ], total_row["count"]


def apply_arbitrage_filters(
    rows: list[dict[str, Any]],
    filters: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if not filters:
        return rows

    filter_fields = {
        "name",
        "buy_price",
        "sell_price",
        "net_sell_price",
        "profit",
        "profit_percent",
    }

    filtered_rows = rows
    for raw_field, field_filter in filters.items():
        field = raw_field.lower()
        if field not in filter_fields:
            raise HTTPException(
                status_code=400,
                detail=f"arbitrage filter field must be one of: {', '.join(sorted(filter_fields))}",
            )

        if not isinstance(field_filter, dict):
            raise HTTPException(status_code=400, detail=f"{field} filter must be an object")

        contains = field_filter.get("contains")
        min_value = parse_decimal(field_filter.get("min"))
        max_value = parse_decimal(field_filter.get("max"))
        not_null = bool(field_filter.get("not_null"))

        if contains:
            needle = str(contains).lower()
            filtered_rows = [
                row for row in filtered_rows
                if needle in str(row.get(field, "")).lower()
            ]

        if min_value is not None:
            filtered_rows = [
                row for row in filtered_rows
                if row.get(field) is not None and Decimal(str(row[field])) >= min_value
            ]

        if max_value is not None:
            filtered_rows = [
                row for row in filtered_rows
                if row.get(field) is not None and Decimal(str(row[field])) <= max_value
            ]

        if not_null:
            filtered_rows = [
                row for row in filtered_rows
                if row.get(field) is not None
            ]

    return filtered_rows


@app.get("/skins")
def get_skins(
    field: str = Query("last_update"),
    order_type: str = Query("desc"),
    page: int = Query(1, ge=1),
) -> dict[str, Any]:
    return fetch_skins(page, field, order_type)


@app.post("/skins/search")
def search_skins(request: SearchRequest) -> dict[str, Any]:
    return fetch_skins(
        page=request.page,
        field=request.sort.field,
        order_type=request.sort.order_type,
        filters=request.filters,
    )


@app.post("/arbitrage/search")
async def search_arbitrage(request: ArbitrageRequest) -> dict[str, Any]:
    game = request.game.lower()
    query_game = "cs2" if game == "all" else game
    first_service = request.first_service.lower()
    second_service = request.second_service.lower()
    first_price_types = {price_type.lower() for price_type in request.first_price_types}
    second_price_types = {price_type.lower() for price_type in request.second_price_types}

    if first_service == "lootfarm":
        first_price_types = {"normal"}
    if second_service == "lootfarm":
        second_price_types = {"orders"}

    if game not in GAME_IDS:
        raise HTTPException(
            status_code=400,
            detail=f"game must be one of: {', '.join(sorted(GAME_IDS))}",
        )

    if first_service not in ALLOWED_SERVICES or second_service not in ALLOWED_SERVICES:
        raise HTTPException(
            status_code=400,
            detail=f"service must be one of: {', '.join(sorted(ALLOWED_SERVICES))}",
        )

    if not first_price_types or not first_price_types.issubset(ALLOWED_PRICE_TYPES):
        raise HTTPException(
            status_code=400,
            detail=f"first_price_types must include: {', '.join(sorted(ALLOWED_PRICE_TYPES))}",
        )

    if not second_price_types or not second_price_types.issubset(ALLOWED_PRICE_TYPES):
        raise HTTPException(
            status_code=400,
            detail=f"second_price_types must include: {', '.join(sorted(ALLOWED_PRICE_TYPES))}",
        )

    sort_field, sort_order = validate_arbitrage_sort(request.sort.field, request.sort.order_type)
    source_items = count_marketplace_names(query_game)
    page_items, total_found = fetch_cached_arbitrage_rows(
        first_service=first_service,
        second_service=second_service,
        game=query_game,
        first_price_types=first_price_types,
        second_price_types=second_price_types,
        filters=request.filters,
        page=request.page,
        lootfarm_no_overstock=request.lootfarm_no_overstock,
        sort_field=sort_field,
        sort_order=sort_order,
    )

    return {
        "page": request.page,
        "page_size": ARBITRAGE_PAGE_SIZE,
        "currency": "USD",
        "source_items": source_items,
        "price_matches": {
            f"buy {first_service}": count_cached_price_matches(first_service, query_game, first_price_types),
            f"sell {second_service}": count_cached_price_matches(second_service, query_game, second_price_types),
        },
        "fees": {
            service: decimal_to_float(fee)
            for service, fee in SERVICE_FEES.items()
        },
        "items": page_items,
        "total_found": total_found,
    }
