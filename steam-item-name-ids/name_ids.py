import asyncio
import argparse
import json
import random
import re
from pathlib import Path
from urllib.parse import quote

import aiohttp
from utils.app_id import SteamGame, choose_game

# В разделе Sources есть такая хуйня у киловат кейсика: 
'''

                        $J(document).ready(function() {
                            Market_LoadOrderSpread(176413986);
                            // initial load
                            PollOnUserActionAfterInterval('MarketOrderSpread', 5000, function() {
                                Market_LoadOrderSpread(176413986);
                            }, 2 * 60 * 1000);

                            ItemActivityTicker.Start(176413986);
                        });
'''
# Через re ищем в ХТМЛ эту строку и достаем от туда nameId конкретного предмета
ITEM_NAMEID_RE = re.compile(r"Market_LoadOrderSpread\(\s*(\d+)\s*\)")

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

SEARCH_PAGE_SIZE = 100
SAVE_EVERY_ITEMS = 25
MAX_RETRIES = 8
SEARCH_DELAY_SECONDS = 2.5
ITEM_DELAY_SECONDS = 1.5

# Get запрос на https://steamcommunity.com/market/search/render/
async def fetch_json(session: aiohttp.ClientSession, url: str, params: dict):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with session.get(url, params=params) as r:
                if r.status == 429:
                    wait = 60 * attempt
                    print(f"Rate limit 429. Sleep {wait} seconds...")
                    await asyncio.sleep(wait)
                    continue

                if r.status >= 500:
                    wait = 10 * attempt
                    print(f"Steam server error {r.status}. Sleep {wait} seconds...")
                    await asyncio.sleep(wait)
                    continue

                r.raise_for_status()
                return await r.json()
        except aiohttp.ClientError as error:
            wait = 10 * attempt
            print(f"Request error: {error}. Sleep {wait} seconds...")
            await asyncio.sleep(wait)

    raise RuntimeError(f"Failed to fetch json after {MAX_RETRIES} retries: {url}")
    

# HTML запрос на https://steamcommunity.com/market/listings/730/Kilowatt%20Case
async def fetch_text(session: aiohttp.ClientSession, url: str):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with session.get(url) as r:
                if r.status == 429:
                    wait = 60 * attempt
                    print(f"Rate limit 429. Sleep {wait} seconds...")
                    await asyncio.sleep(wait)
                    continue

                if r.status >= 500:
                    wait = 10 * attempt
                    print(f"Steam server error {r.status}. Sleep {wait} seconds...")
                    await asyncio.sleep(wait)
                    continue

                r.raise_for_status()
                return await r.text()
        except aiohttp.ClientError as error:
            wait = 10 * attempt
            print(f"Request error: {error}. Sleep {wait} seconds...")
            await asyncio.sleep(wait)

    raise RuntimeError(f"Failed to fetch html after {MAX_RETRIES} retries: {url}")
    
# список названия предметов
'''
Стим вернет примерно такую дресню:

{
  "results": [
    {
      "name": "Kilowatt Case",
      "hash_name": "Kilowatt Case"
    }
  ]
}

'''
async def get_market_names_page(
    session: aiohttp.ClientSession,
    app_id: int,
    start: int,
) -> tuple[list[str], int]:
    data = await fetch_json(
        session,
        "https://steamcommunity.com/market/search/render/",
        {
            "appid": app_id,
            "norender": 1,
            "start": start,
            "count": SEARCH_PAGE_SIZE,
            "query": "",
        },
    )

    total_count = int(data.get("total_count", 0))
    names = [
        item["hash_name"]
        for item in data.get("results", [])
        if item.get("hash_name")
    ]

    return names, total_count

async def get_item_nameid(session: aiohttp.ClientSession, app_id: int, market_hash_name: str):
    encoded_name = quote(market_hash_name, safe="")
    url = f"https://steamcommunity.com/market/listings/{app_id}/{encoded_name}"

    html = await fetch_text(session, url)
    match = ITEM_NAMEID_RE.search(html)

    if not match:
        return None
    
    return int(match.group(1))


def load_dump(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}

    data = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(data, dict):
        return {str(name): int(item_nameid) for name, item_nameid in data.items()}

    
    # [{"market_hash_name": "...", "item_nameid": 123}]
    if isinstance(data, list):
        return {
            str(item["market_hash_name"]): int(item["item_nameid"])
            for item in data
            if "market_hash_name" in item and "item_nameid" in item
        }

    return {}


def save_dump(path: Path, data: dict[str, int]) -> None:
    ordered_data = dict(sorted(data.items(), key=lambda item: item[0].casefold()))
    path.write_text(
        json.dumps(ordered_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"next_start": 0, "processed_count": 0}

    data = json.loads(path.read_text(encoding="utf-8"))

    return {
        "next_start": int(data.get("next_start", 0)),
        "processed_count": int(data.get("processed_count", 0)),
    }


def save_state(path: Path, *, next_start: int, processed_count: int) -> None:
    path.write_text(
        json.dumps(
            {
                "next_start": next_start,
                "processed_count": processed_count,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


async def main(game: SteamGame, limit: int, reset_state: bool):
    output = Path(f"steam-item-name-ids/dump/{game.name}.json")
    state_path = Path(f"steam-item-name-ids/dump/{game.name}_state.json")
    output.parent.mkdir(parents=True, exist_ok=True)

    print(f"Selected game: {game.name}, app_id: {game.app_id}")
    print(f"Output file: {output}")
    print(f"State file: {state_path}")

    result = load_dump(output)
    state = {"next_start": 0, "processed_count": 0} if reset_state else load_state(state_path)

    print(f"Already saved items: {len(result)}")
    print(f"Resume from market start: {state['next_start']}")

    async with aiohttp.ClientSession(headers=HEADERS) as session:
        start = state["next_start"]
        total_count = None
        processed_count = state["processed_count"]

        while total_count is None or start < total_count:
            if limit is not None and processed_count >= limit:
                break

            names, total_count = await get_market_names_page(
                session,
                app_id=game.app_id,
                start=start,
            )

            if not names:
                break

            print(f"Loaded market names page: start={start}, got={len(names)}, total={total_count}")

            for name in names:
                if limit is not None and processed_count >= limit:
                    break

                processed_count += 1

                if name in result:
                    print(f"Skip existing: {name}")
                    continue

                try:
                    item_nameid = await get_item_nameid(session, app_id=game.app_id, market_hash_name=name)
                except Exception as error:
                    print(f"Failed: {name} | {error}")
                    save_dump(output, result)
                    save_state(state_path, next_start=start, processed_count=processed_count)
                    continue

                if item_nameid:
                    result[name] = item_nameid
                    print(f"{name}: {item_nameid}")
                    save_dump(output, result)
                    save_state(state_path, next_start=start, processed_count=processed_count)

                if processed_count % SAVE_EVERY_ITEMS == 0:
                    save_dump(output, result)
                    save_state(state_path, next_start=start, processed_count=processed_count)
                    print(
                        f"Progress saved: processed={processed_count}, "
                        f"market_start={start}, total saved={len(result)}"
                    )

                await asyncio.sleep(ITEM_DELAY_SECONDS + random.uniform(0.5, 2.0))

            start += len(names)
            save_dump(output, result)
            save_state(state_path, next_start=start, processed_count=processed_count)
            await asyncio.sleep(SEARCH_DELAY_SECONDS + random.uniform(0.5, 2.0))
    
    save_dump(output, result)
    save_state(state_path, next_start=start, processed_count=processed_count)

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--reset-state", action="store_true")
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args()
    selected_game = choose_game()
    asyncio.run(main(game=selected_game, limit=args.limit, reset_state=args.reset_state))
