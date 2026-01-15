#!/usr/bin/env python3
"""Find hourly crypto markets on Kalshi"""
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

print("=== SEARCHING FOR HOURLY CRYPTO MARKETS ===\n")

# Search keywords from the screenshots
hourly_keywords = ["price today", "price tomorrow", "10am", "5pm", "hourly", "price at"]
crypto_assets = ["bitcoin", "btc", "ethereum", "eth", "solana", "sol", "ripple", "xrp"]

# Get ALL events - paginate fully
all_events = []
cursor = None
page = 0
while True:
    url = "/events?status=open&limit=200"
    if cursor:
        url += f"&cursor={cursor}"
    data = get(url)
    events = data.get("events", [])
    all_events.extend(events)
    cursor = data.get("cursor")
    page += 1
    print(f"Page {page}: fetched {len(events)} events (total: {len(all_events)})")
    if not cursor or page > 25:
        break

print(f"\nTotal events: {len(all_events)}")

# Find hourly price markets
hourly_markets = []
for e in all_events:
    title = e.get("title", "").lower()
    ticker = e.get("event_ticker", "").lower()
    
    # Check if it's an hourly crypto price market
    is_hourly = any(kw in title for kw in hourly_keywords)
    is_crypto = any(asset in title or asset in ticker for asset in crypto_assets)
    
    if is_hourly and is_crypto:
        hourly_markets.append(e)

print(f"\nFound {len(hourly_markets)} hourly crypto price events!\n")

# Show all hourly markets with their strike prices
for e in hourly_markets:
    print(f"{'='*70}")
    print(f"Event: {e.get('title')}")
    print(f"  Ticker: {e.get('event_ticker')}")
    print(f"  Series: {e.get('series_ticker')}")
    
    # Get markets for this event
    markets_data = get(f"/markets?event_ticker={e.get('event_ticker')}&status=open")
    markets = markets_data.get("markets", [])
    
    if markets:
        print(f"  Open Markets ({len(markets)}):")
        for m in markets[:20]:
            mticker = m.get("ticker", "")
            subtitle = m.get("subtitle", "")
            yes_ask = m.get("yes_ask")
            no_ask = m.get("no_ask")
            yes_bid = m.get("yes_bid")
            no_bid = m.get("no_bid")
            volume = m.get("volume", 0)
            expiration = m.get("expiration_time", "")
            
            yes_ask_str = f"${yes_ask/100:.2f}" if yes_ask else "N/A"
            no_ask_str = f"${no_ask/100:.2f}" if no_ask else "N/A"
            yes_bid_str = f"${yes_bid/100:.2f}" if yes_bid else "N/A"
            no_bid_str = f"${no_bid/100:.2f}" if no_bid else "N/A"
            
            print(f"    {mticker}")
            print(f"      Strike: {subtitle}")
            print(f"      Yes: Bid {yes_bid_str} / Ask {yes_ask_str}")
            print(f"      No:  Bid {no_bid_str} / Ask {no_ask_str}")
            print(f"      Vol: {volume} | Expires: {expiration}")
    else:
        print("  No open markets")
    print()
