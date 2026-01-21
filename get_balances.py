import asyncio
import sqlite3
import os
import sys
from datetime import datetime
from aiohttp_socks import ProxyConnector
import aiohttp
from decimal import Decimal

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import config

# Direct import to avoid circular dependencies
import aiohttp
import base64
import time
import json
from datetime import datetime, timezone
from decimal import Decimal
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

class SimpleKalshiClient:
    """Minimal Kalshi client for testing authentication - Uses PSS signing"""
    
    def __init__(self):
        self.api_key = config.kalshi.api_key
        self.private_key_path = config.kalshi.private_key_path
        
        if config.kalshi.use_demo:
            self.base_url = config.kalshi.demo_base_url
        else:
            # Use updated production URL
            self.base_url = "https://api.elections.kalshi.com/trade-api/v2"
            
        self.private_key = None
        self.session = None
    
    async def connect(self):
        self._load_private_key()
        try:
            connector = ProxyConnector.from_url("socks5://127.0.0.1:9050")
            self.session = aiohttp.ClientSession(connector=connector)
        except Exception as e:
            print(f"   Proxy connection failed: {e}. Falling back to direct.")
            self.session = aiohttp.ClientSession()
        # NOTE: Kalshi no longer uses /log_in token - authenticate directly with each request
        
    async def close(self):
        if self.session:
            await self.session.close()
    
    def _load_private_key(self):
        with open(self.private_key_path, "rb") as f:
            self.private_key = serialization.load_pem_private_key(
                f.read(), 
                password=None,
                backend=default_backend()
            )
    
    def _sign_pss(self, timestamp_ms: int, method: str, path: str) -> str:
        """Sign using RSA-PSS as per Kalshi's current API requirements"""
        # Strip query params from path for signing
        path_without_query = path.split('?')[0]
        message = f"{timestamp_ms}{method}{path_without_query}".encode('utf-8')
        signature = self.private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH  # Use max length as per spec
            ),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode('utf-8')
    
    def _auth_headers(self, method: str, path: str):
        """Generate authentication headers for each request"""
        timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        # Path for signing should be the full API path
        full_path = f"/trade-api/v2{path}"
        signature = self._sign_pss(timestamp_ms, method, full_path)
        return {
            "KALSHI-ACCESS-KEY": self.api_key,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": str(timestamp_ms),
            "Content-Type": "application/json"
        }
    
    async def get_balance(self):
        path = "/portfolio/balance"
        headers = self._auth_headers("GET", path)
        async with self.session.get(f"{self.base_url}{path}", headers=headers) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"Failed to get balance: {resp.status} - {text}")
            return await resp.json()

async def get_real_balance():
    try:
        # Use our local SimpleKalshiClient since it has the proxy logic
        client = SimpleKalshiClient()
        await client.connect()
        data = await client.get_balance()
        await client.close()
        
        balance = Decimal(str(data.get("balance", 0))) / 100
        portfolio = Decimal(str(data.get("portfolio_value", 0))) / 100
        return balance, portfolio
    except Exception as e:
        print(f"Error getting real balance: {e}")
        return 0, 0

def get_paper_balance(db_path):
    if not os.path.exists(db_path):
        return None
    
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        
        # Try to get from snapshots first
        try:
            cur.execute("SELECT * FROM portfolio_snapshots ORDER BY timestamp DESC LIMIT 1")
            row = cur.fetchone()
            if row:
                # Assuming schema: id, timestamp, cash, portfolio, equity, ...
                # Based on observation: (1702, '...', 0.53, 920.35, 920.88, ...)
                if len(row) >= 5:
                    return row[2], row[3], row[4]
        except Exception as e:
            # print(f"Snapshot read error for {db_path}: {e}")
            pass
            
        # If no snapshots, calculate rough estimate from trades
        # Assuming $1000 start
        try:
            cur.execute("SELECT SUM(quantity * price)/100.0 FROM trades")
            res = cur.fetchone()
            spent = res[0] if res and res[0] else 0
        except:
            spent = 0
        
        # This is a very rough estimate as it doesn't account for P&L from closed positions
        return 1000 - spent, spent, 1000 
        
    except Exception as e:
        print(f"Error reading DB {db_path}: {e}")
        return None
    finally:
        if 'conn' in locals():
            conn.close()

async def main():
    print("=" * 60)
    print("ACCOUNT BALANCES OVERVIEW")
    print("=" * 60)
    
    # 1. Real Money Account
    cash, port = await get_real_balance()
    print(f"💰 REAL MONEY ACCOUNT")
    print(f"   Cash:      ${cash:.2f}")
    print(f"   Portfolio: ${port:.2f}")
    print(f"   Total:     ${cash + port:.2f}")
    print("-" * 60)
    
    # 2. Paper Accounts
    print(f"📝 PAPER TRADING ACCOUNTS")
    
    # Integrated Bot
    integrated_db = "/root/kalshi-bot/integrated_paper_data/paper_trades.db"
    if not os.access(integrated_db, os.R_OK):
        print(f"   [Hourly/Integrated Bot] Cannot read DB at {integrated_db}")
    else:
        stats = get_paper_balance(integrated_db)
    if stats:
        cash, port, equity = stats
        print(f"   [Hourly/Integrated Bot]")
        print(f"   Cash:      ${cash:.2f}")
        print(f"   Portfolio: ${port:.2f}")
        print(f"   Total:     ${equity:.2f}")
    else:
        print(f"   [Hourly/Integrated Bot] Data not available")
        
    print()
    
    # 15m Bot
    bot15m_db = "/root/kalshi-bot/paper_15m_data/paper_trades.db"
    stats = get_paper_balance(bot15m_db)
    if stats:
        # Check if we got the rough estimate (tuple of 3)
        cash, port, equity = stats
        print(f"   [Fast 15m Bot]")
        print(f"   Cash:      ${cash:.2f}")
        print(f"   Portfolio: ${port:.2f}")
        print(f"   Total:     ${equity:.2f} (Est.)")
    else:
        print(f"   [Fast 15m Bot] Data not available")

    print()
    
    # Webapp Bot
    webapp_db = "/home/root/webapp/paper_trading_data/paper_trades.db"
    stats = get_paper_balance(webapp_db)
    if stats:
        cash, port, equity = stats
        print(f"   [Webapp Bot]")
        print(f"   Cash:      ${cash:.2f}")
        print(f"   Portfolio: ${port:.2f}")
        print(f"   Total:     ${equity:.2f}")
    else:
        print(f"   [Webapp Bot] Not started yet or no data")

    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
