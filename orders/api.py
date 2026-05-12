import os
from decimal import Decimal
from typing import Any

import psycopg
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
