#!/usr/bin/env python3
"""
Debug script to see actual Polymarket API response structure
"""

import requests
import json

def fetch_markets():
    url = "https://gamma-api.polymarket.com/markets"
    params = {
        "limit": 5,
        "active": "true",
        "_sort": "volume24hr",
        "_order": "desc"
    }

    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    return response.json()

markets = fetch_markets()

print("First market structure:")
print(json.dumps(markets[0], indent=2))

print("\n\nKeys available:")
print(markets[0].keys())

if "tokens" in markets[0]:
    print("\n\nToken structure:")
    print(json.dumps(markets[0]["tokens"], indent=2))
