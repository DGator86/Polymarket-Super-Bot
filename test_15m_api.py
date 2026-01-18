#!/usr/bin/env python3
"""Test 15M API calls directly"""
import asyncio
import aiohttp
from aiohttp_socks import ProxyConnector

async def test():
    proxy = "socks5://127.0.0.1:9050"
    url = "https://api.elections.kalshi.com/trade-api/v2/markets"
    
    connector = ProxyConnector.from_url(proxy)
    async with aiohttp.ClientSession(connector=connector) as session:
        # Test with status=active
        params = {"series_ticker": "KXBTC15M", "status": "active", "limit": 50}
        async with session.get(url, params=params) as resp:
            data = await resp.json()
            markets = data.get("markets", [])
            print(f"KXBTC15M with status=active: {len(markets)} markets")
            for m in markets[:5]:
                ticker = m.get("ticker")
                status = m.get("status")
                print(f"  {ticker} - status: {status}")
        
        # Test with status=open
        params = {"series_ticker": "KXBTC15M", "status": "open", "limit": 50}
        async with session.get(url, params=params) as resp:
            data = await resp.json()
            markets = data.get("markets", [])
            print(f"\nKXBTC15M with status=open: {len(markets)} markets")
            for m in markets[:5]:
                ticker = m.get("ticker")
                status = m.get("status")
                print(f"  {ticker} - status: {status}")
        
        # Test without status filter
        params = {"series_ticker": "KXBTC15M", "limit": 50}
        async with session.get(url, params=params) as resp:
            data = await resp.json()
            markets = data.get("markets", [])
            print(f"\nKXBTC15M with NO status filter: {len(markets)} markets")
            status_counts = {}
            for m in markets:
                s = m.get("status", "unknown")
                status_counts[s] = status_counts.get(s, 0) + 1
            print(f"  Status breakdown: {status_counts}")
            
            # Show active ones
            active = [m for m in markets if m.get("status") == "active"]
            print(f"  Active markets: {len(active)}")
            for m in active[:3]:
                ticker = m.get("ticker")
                print(f"    {ticker}")

if __name__ == "__main__":
    asyncio.run(test())
