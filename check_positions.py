#!/usr/bin/env python3
import os, time, base64, requests
from pathlib import Path
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding

env_path = Path("/opt/kalshi-latency-bot/.env")
if env_path.exists():
    for line in open(env_path):
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            os.environ.setdefault(k, v)

api_key = os.getenv("KALSHI_API_KEY")
key_path = "/opt/kalshi-latency-bot/kalshi_private_key.pem"
base_url = "https://api.elections.kalshi.com/trade-api/v2"

with open(key_path, "rb") as f:
    pk = serialization.load_pem_private_key(f.read(), password=None)

def sign(msg):
    return base64.b64encode(pk.sign(msg.encode(), padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH), hashes.SHA256())).decode()

def headers(m, p):
    ts = str(int(time.time() * 1000))
    return {"KALSHI-ACCESS-KEY": api_key, "KALSHI-ACCESS-SIGNATURE": sign(ts + m + "/trade-api/v2" + p), "KALSHI-ACCESS-TIMESTAMP": ts}

# Get balance first
r = requests.get(base_url + "/portfolio/balance", headers=headers("GET", "/portfolio/balance"))
bal = r.json()
cash = bal.get("balance", 0) / 100
portfolio = bal.get("portfolio_value", 0) / 100
print(f"CASH: ${cash:.2f} | PORTFOLIO: ${portfolio:.2f} | TOTAL: ${cash + portfolio:.2f}")
print("=" * 80)

# Get positions
r = requests.get(base_url + "/portfolio/positions", headers=headers("GET", "/portfolio/positions"))
pos = r.json().get("market_positions", [])

print("CURRENT POSITIONS:")
for p in pos:
    ticker = p.get("ticker", "")
    position = p.get("position", 0)
    if position == 0:
        continue
    side = "YES" if position > 0 else "NO"
    qty = abs(position)
    exposure = p.get("market_exposure", 0) / 100
    print(f"  {ticker}: {qty} {side} (${exposure:.2f})")

# Check what these positions mean
print("\n" + "=" * 80)
print("POSITION ANALYSIS:")
print("=" * 80)

# Parse tickers
for p in pos:
    ticker = p.get("ticker", "")
    position = p.get("position", 0)
    if position == 0:
        continue
    
    # Parse ticker: KXBTCD-26JAN1617-T97499.99
    parts = ticker.split("-")
    if len(parts) >= 3:
        asset = parts[0]  # KXBTCD
        expiry = parts[1]  # 26JAN1617
        strike_part = parts[2]  # T97499.99
        
        if strike_part.startswith("T"):
            strike = float(strike_part[1:])
        elif strike_part.startswith("B"):
            strike = float(strike_part[1:])
        else:
            strike = 0
            
        side = "YES (above)" if position > 0 else "NO (below)"
        qty = abs(position)
        
        if "BTC" in asset:
            crypto = "BTC"
        elif "ETH" in asset:
            crypto = "ETH"
        else:
            crypto = asset
            
        print(f"{crypto} @ ${strike:,.2f} by {expiry}: {qty} {side}")
