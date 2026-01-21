import asyncio
import sqlite3
import os
import sys
import re
from datetime import datetime, timezone
from decimal import Decimal
from aiohttp_socks import ProxyConnector
import aiohttp
import base64
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

# --- Configuration ---
# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import config

# --- Kalshi Client (Fixed with Proxy) ---
class SimpleKalshiClient:
    def __init__(self):
        self.api_key = config.kalshi.api_key
        self.private_key_path = config.kalshi.private_key_path
        self.base_url = "https://api.elections.kalshi.com/trade-api/v2"
        self.private_key = None
        self.session = None

    async def connect(self):
        self._load_private_key()
        try:
            connector = ProxyConnector.from_url("socks5://127.0.0.1:9050")
            self.session = aiohttp.ClientSession(connector=connector)
        except Exception as e:
            print(f"Proxy error: {e}")
            self.session = aiohttp.ClientSession()

    async def close(self):
        if self.session:
            await self.session.close()

    def _load_private_key(self):
        with open(self.private_key_path, "rb") as f:
            self.private_key = serialization.load_pem_private_key(f.read(), password=None, backend=default_backend())

    def _sign_pss(self, timestamp_ms, method, path):
        path_without_query = path.split('?')[0]
        message = f"{timestamp_ms}{method}{path_without_query}".encode('utf-8')
        signature = self.private_key.sign(message, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH), hashes.SHA256())
        return base64.b64encode(signature).decode('utf-8')

    def _auth_headers(self, method, path):
        timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        full_path = f"/trade-api/v2{path}"
        signature = self._sign_pss(timestamp_ms, method, full_path)
        return {
            "KALSHI-ACCESS-KEY": self.api_key,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": str(timestamp_ms),
            "Content-Type": "application/json"
        }

    async def get_positions(self):
        path = "/portfolio/positions"
        headers = self._auth_headers("GET", path)
        async with self.session.get(f"{self.base_url}{path}", headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("market_positions", [])
            return []

    async def get_market(self, ticker):
        path = f"/markets/{ticker}"
        headers = self._auth_headers("GET", path)
        async with self.session.get(f"{self.base_url}{path}", headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("market", {})
            return {}

# --- Helper Functions ---
def parse_expiry(ticker):
    # Try to parse expiry from ticker
    # Format: KXBTC-26JAN1814-B95125 (YYMMM DDHH)
    # Format: KXBTC15M-26JAN181715-15 (YYMMM DDHHMM)
    try:
        parts = ticker.split('-')
        date_part = parts[1] # 26JAN1814 or 26JAN181715
        
        # Parse YYMMM
        year = "20" + date_part[:2]
        month_str = date_part[2:5]
        day = date_part[5:7]
        
        months = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6, 
                  "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
        month = months.get(month_str, 1)
        
        time_part = date_part[7:]
        hour = int(time_part[:2])
        minute = int(time_part[2:4]) if len(time_part) >= 4 else 0
        
        return datetime(int(year), month, int(day), hour, minute, tzinfo=timezone.utc)
    except:
        return datetime.max.replace(tzinfo=timezone.utc) # Assuming future if parse fails

async def get_market_price(client, ticker):
    m = await client.get_market(ticker)
    return Decimal(str(m.get("last_price", 0))) / 100

# --- Main Logic ---
async def main():
    print("=" * 100)
    print(f"{'ACCOUNT / TICKER':<40} {'SIDE':<5} {'QTY':<5} {'ENTRY':<10} {'CURRENT':<10} {'P&L':<10}")
    print("=" * 100)
    
    client = SimpleKalshiClient()
    await client.connect()
    
    # 1. Real Money Account
    print("💰 REAL MONEY ACCOUNT")
    try:
        positions = await client.get_positions()
        if not positions:
            print("  No open positions.")
        for p in positions:
            ticker = p.get("ticker")
            pos_size = p.get("position", 0)
            side = "YES" if pos_size > 0 else "NO"
            qty = abs(pos_size)
            entry = Decimal(str(p.get("average_price", 0))) / 100
            
            # Get current price
            m = await client.get_market(ticker)
            last_price = Decimal(str(m.get("last_price", 0))) / 100
            
            # P&L
            if side == "YES":
                pnl = (last_price - entry) * qty
            else:
                pnl = (entry - last_price) * qty # Short YES is NO
                
            print(f"  {ticker:<38} {side:<5} {qty:<5} ${entry:<9.2f} ${last_price:<9.2f} ${pnl:+.2f}")
            
    except Exception as e:
        print(f"  Error fetching positions: {e}")

    print("-" * 100)
    
    # 2. Reconstruct Paper Positions (Root Bots)
    bots = [
        ("INTEGRATED BOT (Hourly)", "/root/kalshi-bot/integrated_paper_data/paper_trades.db"),
        ("FAST 15M BOT", "/root/kalshi-bot/paper_15m_data/paper_trades.db")
    ]
    
    now = datetime.now(timezone.utc)
    
    for name, db_path in bots:
        print(f"📝 {name}")
        if not os.access(db_path, os.R_OK):
            print(f"  Cannot access DB at {db_path}")
            continue
            
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("SELECT ticker, side, quantity, price, created_at FROM trades ORDER BY created_at ASC")
            rows = cur.fetchall()
            conn.close()
            
            # Reconstruct
            positions = {} # ticker -> {side, qty, cost_basis}
            
            for r in rows:
                ticker, side, qty, price, ts = r
                price = Decimal(str(price)) / 100
                side = side.upper()
                
                if ticker not in positions:
                    positions[ticker] = {"side": side, "qty": 0, "avg_price": Decimal(0)}
                
                pos = positions[ticker]
                
                if pos["side"] == side:
                    # Add
                    total_cost = (pos["qty"] * pos["avg_price"]) + (qty * price)
                    pos["qty"] += qty
                    if pos["qty"] > 0:
                        pos["avg_price"] = total_cost / pos["qty"]
                else:
                    # Reduce / Close (Simplified logic matching engine)
                    if qty >= pos["qty"]:
                        # Closed
                        pos["qty"] = 0
                        pos["avg_price"] = 0
                        pos["side"] = side # Flip? No, engine deletes. We just zero out.
                    else:
                        pos["qty"] -= qty
            
            # Filter and Display
            active_count = 0
            for ticker, pos in positions.items():
                if pos["qty"] > 0:
                    # Check expiry
                    expiry = parse_expiry(ticker)
                    if expiry < now:
                        continue # Expired
                    
                    active_count += 1
                    
                    # Fetch current price
                    curr_price = await get_market_price(client, ticker)
                    
                    # Calc P&L
                    entry = pos["avg_price"]
                    qty = pos["qty"]
                    side = pos["side"]
                    
                    if side == "YES":
                        pnl = (curr_price - entry) * qty
                    else:
                        pnl = (entry - curr_price) * qty
                        
                    print(f"  {ticker:<38} {side:<5} {qty:<5} ${entry:<9.2f} ${curr_price:<9.2f} ${pnl:+.2f}")
            
            if active_count == 0:
                print("  No active positions (or all expired).")
                
        except Exception as e:
            print(f"  Error processing DB: {e}")
            
        print("-" * 100)

    # 3. Webapp Bot (Has positions table)
    print("📝 WEBAPP BOT")
    db_path = "/home/root/webapp/paper_trading_data/paper_trades.db"
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("SELECT ticker, side, quantity, entry_price, current_price FROM positions WHERE settled=0")
            rows = cur.fetchall()
            conn.close()
            
            if not rows:
                 print("  No open positions.")
            
            for r in rows:
                ticker, side, qty, entry, curr = r
                side = side.upper()
                entry = Decimal(str(entry))
                curr = Decimal(str(curr))
                
                if side == "YES":
                    pnl = (curr - entry) * qty
                else:
                    pnl = (entry - curr) * qty
                
                print(f"  {ticker:<38} {side:<5} {qty:<5} ${entry:<9.2f} ${curr:<9.2f} ${pnl:+.2f}")
                
        except Exception as e:
            print(f"  Error reading positions: {e}")
    else:
        print("  DB not found.")

    await client.close()
    print("=" * 100)

if __name__ == "__main__":
    asyncio.run(main())
