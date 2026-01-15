#!/usr/bin/env python3
"""Search for crypto markets on Kalshi"""
import requests
import os
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
    sig = private_key.sign(
        message.encode(), 
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH), 
        hashes.SHA256()
    )
    return base64.b64encode(sig).decode()

api_base = "https://api.elections.kalshi.com/trade-api/v2"

def get(endpoint):
    ts = str(int(time.time() * 1000))
    path = "/trade-api/v2" + endpoint.split("?")[0]
    headers = {
        "KALSHI-ACCESS-KEY": api_key, 
        "KALSHI-ACCESS-TIMESTAMP": ts, 
        "KALSHI-ACCESS-SIGNATURE": sign(ts + "GET" + path)
    }
    return requests.get(api_base + endpoint, headers=headers).json()

print("=== KALSHI CRYPTO MARKET SEARCH ===\n")

# Get events - paginate to get more
all_events = []
cursor = None
for page in range(10):
    url = "/events?status=open&limit=200"
    if cursor:
        url += f"&cursor={cursor}"
    data = get(url)
    events = data.get("events", [])
    all_events.extend(events)
    cursor = data.get("cursor")
    if not cursor:
        break

print(f"Total events fetched: {len(all_events)}")

# Filter for crypto category
crypto_events = [e for e in all_events if e.get("category", "").lower() == "crypto"]
print(f"Crypto category events: {len(crypto_events)}\n")

# Show all crypto events and their markets
for e in crypto_events:
    title = e.get("title", "N/A")
    ticker = e.get("event_ticker", "N/A")
    series = e.get("series_ticker", "N/A")
    print(f"Event: {title}")
    print(f"  Ticker: {ticker}")
    print(f"  Series: {series}")
    
    # Get markets for this event
    markets_data = get(f"/markets?event_ticker={ticker}&status=open")
    markets = markets_data.get("markets", [])
    
    if markets:
        print(f"  Open Markets ({len(markets)}):")
        for m in markets[:15]:
            mticker = m.get("ticker", "")
            subtitle = m.get("subtitle", "")[:50]
            yes_ask = m.get("yes_ask")
            no_ask = m.get("no_ask")
            volume = m.get("volume", 0)
            
            yes_str = f"${yes_ask/100:.2f}" if yes_ask else "N/A"
            no_str = f"${no_ask/100:.2f}" if no_ask else "N/A"
            
            print(f"    {mticker}: {subtitle}")
            print(f"      Yes: {yes_str} | No: {no_str} | Vol: {volume}")
    else:
        print("  No open markets")
    print()

# Also search for price-based markets that might be related to crypto
print("\n=== SEARCHING FOR PRICE-BASED BTC/ETH MARKETS ===\n")
keywords = ["bitcoin", "btc", "ethereum", "eth", "15 min", "15-min", "price"]
price_events = []
for e in all_events:
    title = (e.get("title", "") + " " + str(e.get("event_ticker", ""))).lower()
    if any(kw in title for kw in keywords):
        price_events.append(e)

print(f"Found {len(price_events)} potential price-related events")
for e in price_events[:10]:
    print(f"  {e.get('event_ticker')}: {e.get('title', '')[:70]}")
