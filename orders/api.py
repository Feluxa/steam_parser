import os
from decimal import Decimal
from typing import Any

import psycopg
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from psycopg.rows import dict_row


POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "15432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "steam_orders")
POSTGRES_USER = os.getenv("POSTGRES_USER", "steam_orders")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "steam_orders")

PAGE_SIZE = 100
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


@app.get("/skins")
def get_skins(
    field: str = Query("last_update"),
    order_type: str = Query("desc"),
    page: int = Query(1, ge=1),
) -> dict[str, Any]:
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
        ORDER BY {field} {order_type.upper()} {nulls_order}, id ASC
        LIMIT %s OFFSET %s
    """

    with get_connection() as connection:
        rows = connection.execute(query, (PAGE_SIZE, offset)).fetchall()

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
