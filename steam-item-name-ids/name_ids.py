import asyncio
import argparse
import json
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

# Get запрос на https://steamcommunity.com/market/search/render/
async def fetch_json(session: aiohttp.ClientSession, url: str, params: dict):
    async with session.get(url, params=params) as r:
        r.raise_for_status()
        return await r.json()
    

# HTML запрос на https://steamcommunity.com/market/listings/730/Kilowatt%20Case
async def fetch_text(session: aiohttp.ClientSession, url: str):
    async with session.get(url) as r:
        r.raise_for_status()
        return await r.text()
    
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
async def get_market_names(session: aiohttp.ClientSession, app_id: int, limit: int | None = None):
    names = []
    start = 0
    total_count = None

    while total_count is None or start < total_count:
        if limit is not None and len(names) >= limit:
            break

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

        page_names = [
            item["hash_name"]
            for item in data.get("results", [])
            if item.get("hash_name")
        ]

        if not page_names:
            break

        names.extend(page_names)
        print(f"Loaded market names: {len(names)}/{total_count}")

        start += SEARCH_PAGE_SIZE
        await asyncio.sleep(1.0)

    if limit is not None:
        return names[:limit]

    return names

async def get_item_nameid(session: aiohttp.ClientSession, app_id: int, market_hash_name: str):
    encoded_name = quote(market_hash_name, safe="")
    url = f"https://steamcommunity.com/market/listings/{app_id}/{encoded_name}"

    html = await fetch_text(session, url)
    match = ITEM_NAMEID_RE.search(html)

    if not match:
        return None
    
    return{
        "market_hash_name": market_hash_name,
        "item_nameid": int(match.group(1)),
    }

async def main(game: SteamGame, limit: int):
    output = Path(f"steam-item-name-ids/dump/{game.name}.json")
    output.parent.mkdir(parents=True, exist_ok=True)

    print(f"Selected game: {game.name}, app_id: {game.app_id}")
    print(f"Output file: {output}")

    async with aiohttp.ClientSession(headers=HEADERS) as session:
        names = await get_market_names(session, app_id=game.app_id, limit=limit)

        result = []

        for index, name in enumerate(names, start=1):
            item = await get_item_nameid(session, app_id=game.app_id, market_hash_name=name)
            if item:
                result.append(item)
                print(item)

            if index % 50 == 0:
                output.write_text(
                    json.dumps(result, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                print(f"Progress saved: {index}/{len(names)}")

            await asyncio.sleep(1.0)
    
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args()
    selected_game = choose_game()
    asyncio.run(main(game=selected_game, limit=args.limit))
