# 176413986 - киловат кейс nameid

import requests
import time

def get_market_orders(item_nameid: int, currency: int = 5):  # 5 = RUB
    url = "https://steamcommunity.com/market/itemordershistogram"
    params = {
        "country": "RU",
        "language": "russian",
        "currency": currency,
        "item_nameid": item_nameid,
        "norender": 1
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
    }
    
    r = requests.get(url, params=params, headers=headers)
    if r.status_code != 200:
        print("Ошибка:", r.status_code)
        return None
    
    data = r.json()
    return {
        "highest_buy": int(data.get("highest_buy_order", 0)) / 100,   # в копейках
        "lowest_sell": int(data.get("lowest_sell_order", 0)) / 100,
    }

# Пример использования
print(get_market_orders(176413986))  # замени на реальный nameid