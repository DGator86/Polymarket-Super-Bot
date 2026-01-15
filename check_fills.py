#!/usr/bin/env python3
import os, time, base64, requests
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding

for line in open("/opt/kalshi-latency-bot/.env"):
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

# Get fills
r = requests.get(base_url + "/portfolio/fills?limit=100", headers=headers("GET", "/portfolio/fills?limit=100"))
fills = r.json().get("fills", [])
print(f"Found {len(fills)} fills (trades)")
print("=" * 100)

# Group by time to see what happened
total_cost = 0
for f in fills:
    created = f.get("created_time", "")[:19]
    ticker = f.get("ticker", "")
    side = f.get("side", "")
    count = f.get("count", 0)
    price = f.get("price", 0) / 100
    cost = count * price
    total_cost += cost
    action = f.get("action", "")
    print(f"{created} | {action} {side} {count} @ ${price:.2f} = ${cost:.2f} | {ticker}")

print("=" * 100)
print(f"TOTAL SPENT: ${total_cost:.2f}")
