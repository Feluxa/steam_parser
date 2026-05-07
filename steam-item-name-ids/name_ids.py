import asyncio
import json
import re
from pathlib import Path
from urllib.parse import quote

import aiohttp

APP_ID = 730 # Айди кс2
# https://steamcommunity.com/market/listings/730/А тут название предмета

OUTPUT= Path("data/cs2_name_ids.json")

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
print("Hello")