import json
import time
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

# GET https://steamcommunity.com/market/itemordershistogram?norender=1&country=RU&language=english&currency=5&item_nameid=176000861&two_factor=0


BASE_DIR = Path(__file__).resolve().parents[1]
CS2_FILE = BASE_DIR / "steam-item-name-ids" / "dump" / "cs2.json"
PREFIX = "M4A1-S"
ORDERS_URL = "https://steamcommunity.com/market/itemordershistogram"
MIN_PROFIT_MULTIPLIER = 1.15
REQUEST_TIMEOUT = 30
REQUEST_RETRIES = 3
REQUEST_RETRY_DELAY = 2


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


def parse_rub_price(price: Optional[str]) -> Optional[float]:
    if price is None:
        return None

    normalized = (
        price.replace(" руб.", "")
        .replace("руб.", "")
        .replace(" ", "")
        .replace(",", ".")
    )

    try:
        return float(normalized)
    except ValueError:
        return None


def has_price_gap(sell_order_price: Optional[str], buy_order_price: Optional[str]) -> bool:
    sell_price = parse_rub_price(sell_order_price)
    buy_price = parse_rub_price(buy_order_price)

    if sell_price is None or buy_price is None:
        return False

    return buy_price * MIN_PROFIT_MULTIPLIER < sell_price


def get_potential_profit(
    sell_order_price: Optional[str],
    buy_order_price: Optional[str],
) -> Optional[float]:
    sell_price = parse_rub_price(sell_order_price)
    buy_price = parse_rub_price(buy_order_price)

    if sell_price is None or buy_price is None:
        return None

    return round(sell_price - buy_price * MIN_PROFIT_MULTIPLIER, 2)


def main() -> None:
    with CS2_FILE.open("r", encoding="utf-8") as file:
        items = json.load(file)

    m4a1s_items = {
        name: item_id
        for name, item_id in items.items()
        if name.startswith(PREFIX)
    }

    results = {}
    for name, item_nameid in m4a1s_items.items():
        prices = get_order_prices(item_nameid)
        if not has_price_gap(
            prices["sell_order_price"],
            prices["buy_order_price"],
        ):
            continue

        results[name] = {
            "item_nameid": item_nameid,
            **prices,
            "potential": get_potential_profit(
                prices["sell_order_price"],
                prices["buy_order_price"],
            ),
        }

    print(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\nTotal: {len(results)}")


if __name__ == "__main__":
    main()
