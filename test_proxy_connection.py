import asyncio
import aiohttp
from aiohttp_socks import ProxyConnector

async def test_proxy():
    print("Testing connection via SOCKS5 proxy...")
    connector = ProxyConnector.from_url("socks5://127.0.0.1:9050")
    async with aiohttp.ClientSession(connector=connector) as session:
        try:
            # Try to hit the Kalshi API
            url = "https://api.elections.kalshi.com/trade-api/v2/markets"
            params = {"limit": 1}
            async with session.get(url, params=params) as resp:
                print(f"Status: {resp.status}")
                if resp.status == 200:
                    print("Success! Proxy is working.")
                    data = await resp.json()
                    print(f"Markets found: {len(data.get('markets', []))}")
                else:
                    print("Failed with status code:", resp.status)
                    print(await resp.text())
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_proxy())
