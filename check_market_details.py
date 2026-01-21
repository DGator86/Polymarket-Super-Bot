import asyncio
import sys
import os
from aiohttp_socks import ProxyConnector
import aiohttp
import json
import base64
from datetime import datetime, timezone
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import config

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

    async def get_market(self, ticker):
        path = f"/markets/{ticker}"
        headers = self._auth_headers("GET", path)
        async with self.session.get(f"{self.base_url}{path}", headers=headers) as resp:
            return await resp.json()

async def main():
    ticker = "KXBTC-26JAN2317-B93250"
    client = SimpleKalshiClient()
    await client.connect()
    data = await client.get_market(ticker)
    await client.close()
    
    print(json.dumps(data, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
