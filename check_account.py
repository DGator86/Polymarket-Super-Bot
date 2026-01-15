#!/usr/bin/env python3
import os, requests, time, base64
from dotenv import load_dotenv
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding

load_dotenv("/opt/kalshi-latency-bot/.env")
api_key = os.getenv("KALSHI_API_KEY")
with open("/opt/kalshi-latency-bot/kalshi_private_key.pem", "rb") as f:
    pk = serialization.load_pem_private_key(f.read(), password=None)

def sign(m):
    return base64.b64encode(pk.sign(m.encode(), padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH), hashes.SHA256())).decode()

api = "https://api.elections.kalshi.com/trade-api/v2"

# Balance
ts = str(int(time.time()*1000))
p = "/trade-api/v2/portfolio/balance"
h = {"KALSHI-ACCESS-KEY": api_key, "KALSHI-ACCESS-TIMESTAMP": ts, "KALSHI-ACCESS-SIGNATURE": sign(ts+"GET"+p)}
r = requests.get(api+"/portfolio/balance", headers=h)
b = r.json()
print(f"Cash: ${b.get('balance',0)/100:.2f} | Positions: ${b.get('portfolio_value',0)/100:.2f}")

# Open orders
ts = str(int(time.time()*1000))
p = "/trade-api/v2/portfolio/orders"
h = {"KALSHI-ACCESS-KEY": api_key, "KALSHI-ACCESS-TIMESTAMP": ts, "KALSHI-ACCESS-SIGNATURE": sign(ts+"GET"+p)}
r = requests.get(api+"/portfolio/orders?status=resting", headers=h)
orders = r.json().get("orders",[])
print(f"\nOpen Orders: {len(orders)}")
for o in orders[:5]:
    oid = o.get("order_id","")[:8]
    ticker = o.get("ticker","")
    side = o.get("side","")
    count = o.get("remaining_count",0)
    price = o.get("yes_price") or o.get("no_price") or 0
    print(f"  {oid}... {ticker}: {side} {count} @ ${price/100:.2f}")
