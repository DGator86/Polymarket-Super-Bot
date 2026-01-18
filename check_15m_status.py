import asyncio
import aiohttp
from aiohttp_socks import ProxyConnector
from datetime import datetime, timezone

async def check_15m():
    connector = ProxyConnector.from_url("socks5://127.0.0.1:9050")
    now = datetime.now(timezone.utc)
    time_str = now.strftime("%H:%M:%S")
    print(f"Current UTC: {time_str}")
    print()
    
    async with aiohttp.ClientSession(connector=connector) as session:
        for series in ["KXBTC15M", "KXETH15M", "KXSOL15M"]:
            url = "https://api.elections.kalshi.com/trade-api/v2/markets"
            params = {"series_ticker": series, "limit": 100}
            
            async with session.get(url, params=params) as resp:
                data = await resp.json()
                markets = data.get("markets", [])
                
                # Find open or active markets
                active = [m for m in markets if m.get("status") in ["open", "active", "trading"]]
                print(f"{series}: {len(active)} active (out of {len(markets)} total)")
                
                # Show markets by status
                statuses = {}
                for m in markets:
                    s = m.get("status")
                    statuses[s] = statuses.get(s, 0) + 1
                print(f"  Status breakdown: {statuses}")
                
                # Show a few with bids
                with_bids = [m for m in markets if m.get("yes_bid", 0) > 0]
                print(f"  Markets with bids: {len(with_bids)}")
                for m in with_bids[:3]:
                    ticker = m.get("ticker")
                    status = m.get("status")
                    bid = m.get("yes_bid")
                    ask = m.get("yes_ask")
                    print(f"    {ticker} - {status} - Bid:{bid}c Ask:{ask}c")
                print()

asyncio.run(check_15m())
