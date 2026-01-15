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

# Get orders
r = requests.get(base_url + "/portfolio/orders?limit=50", headers=headers("GET", "/portfolio/orders?limit=50"))
orders = r.json().get("orders", [])
print(f"Found {len(orders)} orders")
print("=" * 100)
for o in orders[:30]:
    created = o.get("created_time", "")[:19]
    ticker = o.get("ticker", "")
    side = o.get("side", "")
    count = o.get("count", 0)
    price = o.get("price", 0) / 100
    status = o.get("status", "")
    filled = o.get("filled_count", 0)
    print(f"{created} | {ticker} | {side} {count} @ ${price:.2f} | {status} (filled: {filled})")
