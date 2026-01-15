#!/usr/bin/env python3
"""Search Kalshi for crypto markets"""
import requests
import os
import json
from dotenv import load_dotenv
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
import base64
import time

load_dotenv("/opt/kalshi-latency-bot/.env")
api_key = os.getenv("KALSHI_API_KEY")
key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH")

with open(key_path, "rb") as f:
    private_key = serialization.load_pem_private_key(f.read(), password=None)

def sign(message):
    signature = private_key.sign(
        message.encode(),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256()
    )
    return base64.b64encode(signature).decode()

api_base = "https://api.elections.kalshi.com/trade-api/v2"

def make_request(endpoint):
    timestamp = str(int(time.time() * 1000))
    path = "/trade-api/v2" + endpoint.split("?")[0]
    sig = sign(timestamp + "GET" + path)
    headers = {
        "KALSHI-ACCESS-KEY": api_key,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "KALSHI-ACCESS-SIGNATURE": sig
    }
    return requests.get(api_base + endpoint, headers=headers)

print("=== KALSHI CRYPTO MARKET SEARCH ===\n")

# Get all events
all_events = []
cursor = None
for _ in range(10):
    url = "/events?status=open&limit=200"
    if cursor:
        url += "&cursor=" + cursor
    response = make_request(url)
    data = response.json()
    events = data.get("events", [])
    all_events.extend(events)
    cursor = data.get("cursor")
    if not cursor:
        break

print(f"Total events fetched: {len(all_events)}")

# Filter for crypto
crypto_keywords = ["bitcoin", "btc", "ethereum", "eth", "crypto", "kxbtc", "kxeth", "solana", "sol"]
crypto_events = []
for e in all_events:
    title = str(e.get("title", "")).lower()
    ticker = str(e.get("event_ticker", "")).lower()
    category = str(e.get("category", "")).lower()
    combined = title + " " + ticker
    if category == "crypto" or any(kw in combined for kw in crypto_keywords):
        crypto_events.append(e)

print(f"Crypto events found: {len(crypto_events)}\n")

# Show ALL crypto events
for e in crypto_events:
    title = e.get("title", "N/A")
    event_ticker = e.get("event_ticker", "N/A")
    category = e.get("category", "N/A")
    series = e.get("series_ticker", "N/A")
    
    print(f"Event: {title}")
    print(f"  Ticker: {event_ticker}")
    print(f"  Category: {category}")
    print(f"  Series: {series}")
    
    # Get markets for this event
    m_resp = make_request("/markets?event_ticker=" + str(event_ticker) + "&status=open")
    m_data = m_resp.json()
    markets = m_data.get("markets", [])
    
    if markets:
        print(f"  Markets ({len(markets)}):")
        for m in markets[:10]:
            yes_ask = m.get("yes_ask")
            no_ask = m.get("no_ask")
            yes_str = "${:.2f}".format(yes_ask/100) if yes_ask else "N/A"
            no_str = "${:.2f}".format(no_ask/100) if no_ask else "N/A"
            subtitle = str(m.get("subtitle", ""))[:50]
            mticker = m.get("ticker", "N/A")
            vol = m.get("volume", 0)
            print(f"    - {mticker}: {subtitle}")
            print(f"      Yes: {yes_str} | No: {no_str} | Volume: {vol}")
    else:
        print("  No open markets")
    print()

# Also show categories breakdown
print("\n=== CATEGORIES BREAKDOWN ===")
categories = {}
for e in all_events:
    cat = e.get("category", "Unknown")
    categories[cat] = categories.get(cat, 0) + 1
for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
    print(f"  {cat}: {count}")
