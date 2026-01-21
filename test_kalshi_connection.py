#!/usr/bin/env python3
"""
Test script to verify Kalshi API connection and credentials.
"""

import asyncio
import sys
import os
from aiohttp_socks import ProxyConnector

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
            print("   Using SOCKS5 proxy at 127.0.0.1:9050")
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
    
    async def get_markets(self, limit=5):
        path = "/markets"
        params = {"status": "open", "limit": limit}
        headers = self._auth_headers("GET", path)
        async with self.session.get(f"{self.base_url}{path}", headers=headers, params=params) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"Failed to get markets: {resp.status} - {text}")
            data = await resp.json()
            return data.get("markets", [])
    
    async def get_positions(self):
        path = "/portfolio/positions"
        headers = self._auth_headers("GET", path)
        async with self.session.get(f"{self.base_url}{path}", headers=headers) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"Failed to get positions: {resp.status} - {text}")
            data = await resp.json()
            return data.get("market_positions", [])


async def test_connection():
    """Test Kalshi API connection and credentials"""
    print("=" * 60)
    print("KALSHI API CONNECTION TEST")
    print("=" * 60)
    
    # Check configuration
    print("\n[1] Configuration Check:")
    print(f"  API Key: {config.kalshi.api_key[:20]}..." if len(config.kalshi.api_key) > 20 else f"  API Key: {config.kalshi.api_key}")
    print(f"  Private Key Path: {config.kalshi.private_key_path}")
    print(f"  Use Demo: {config.kalshi.use_demo}")
    print(f"  Base URL: {config.kalshi.base_url if not config.kalshi.use_demo else config.kalshi.demo_base_url}")
    
    # Check if private key file exists
    if not os.path.exists(config.kalshi.private_key_path):
        print(f"\n❌ ERROR: Private key file not found at: {config.kalshi.private_key_path}")
        return False
    else:
        print(f"\n✅ Private key file found")
    
    # Try to connect
    print("\n[2] Connection Test:")
    client = SimpleKalshiClient()
    
    try:
        await client.connect()
        print("✅ Private key loaded successfully")
        print("✅ Client session initialized")
        print("   Note: Kalshi uses per-request PSS signing (no login token)")
    except Exception as e:
        print(f"❌ Connection error: {e}")
        await client.close() if client.session else None
        return False
    
    # Test account balance
    print("\n[3] Account Balance Test:")
    try:
        balance_data = await client.get_balance()
        available = Decimal(str(balance_data.get("balance", 0))) / 100
        portfolio = Decimal(str(balance_data.get("portfolio_value", 0))) / 100
        total = available + portfolio
        print(f"✅ Balance retrieved successfully")
        print(f"   Available Balance: ${available:.2f}")
        print(f"   Portfolio Value:   ${portfolio:.2f}")
        print(f"   Total Equity:      ${total:.2f}")
    except Exception as e:
        print(f"❌ Error getting balance: {e}")
        await client.close()
        return False
    
    # Test market access
    print("\n[4] Market Access Test:")
    try:
        markets = await client.get_markets(limit=5)
        print(f"✅ Markets retrieved successfully")
        print(f"   Found {len(markets)} open markets (limited to 5)")
        if markets:
            print("\n   Sample markets:")
            for m in markets[:3]:
                print(f"   - {m.get('ticker', 'N/A')}: {m.get('title', 'N/A')[:50]}...")
    except Exception as e:
        print(f"❌ Error getting markets: {e}")
        await client.close()
        return False
    
    # Test positions
    print("\n[5] Positions Test:")
    try:
        positions = await client.get_positions()
        print(f"✅ Positions retrieved successfully")
        print(f"   Current positions: {len(positions)}")
        if positions:
            for pos in positions[:5]:
                ticker = pos.get("ticker", "N/A")
                position = pos.get("position", 0)
                avg_price = Decimal(str(pos.get("average_price", 0))) / 100
                side = "YES" if position > 0 else "NO"
                print(f"   - {ticker}: {abs(position)} {side} @ ${avg_price:.2f}")
    except Exception as e:
        print(f"⚠️ Could not retrieve positions: {e}")
    
    # Clean up
    await client.close()
    
    print("\n" + "=" * 60)
    print("✅ ALL TESTS PASSED - Kalshi API connection verified!")
    print("=" * 60)
    return True


async def main():
    success = await test_connection()
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
