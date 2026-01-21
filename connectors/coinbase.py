"""
Coinbase Advanced Trade API Connector

Provides real-time crypto prices for latency arbitrage strategies:
- BTC/ETH price feeds
- Sub-second WebSocket updates
- Order book depth

This is used to detect when Kalshi crypto markets lag behind actual prices.

API Documentation: https://docs.cdp.coinbase.com/advanced-trade/docs/welcome
"""

import asyncio
import aiohttp
import websockets
import json
import hmac
import hashlib
import time
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, List, Dict, Any, Callable, Awaitable

from config import config
from core.models import CryptoPrice

logger = logging.getLogger(__name__)


# Common trading pairs for Kalshi markets
SYMBOLS = {
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
    "SOL": "SOL-USD",
}


class CoinbaseClient:
    """
    Coinbase Advanced Trade API client.
    
    Provides both REST API for snapshots and WebSocket for real-time streaming.
    For latency arbitrage, we primarily use the WebSocket feed.
    
    Usage:
        client = CoinbaseClient()
        await client.connect()
        
        # One-time price check
        price = await client.get_price("BTC-USD")
        
        # Real-time streaming
        await client.stream_prices(["BTC-USD"], my_callback)
    """
    
    REST_URL = "https://api.coinbase.com/api/v3/brokerage"
    WS_URL = "wss://advanced-trade-ws.coinbase.com"
    
    # Public API (no auth needed for market data)
    PUBLIC_REST_URL = "https://api.exchange.coinbase.com"
    PUBLIC_WS_URL = "wss://ws-feed.exchange.coinbase.com"
    
    def __init__(self, api_key: str = None, api_secret: str = None):
        self.api_key = api_key or config.data_sources.coinbase_api_key
        self.api_secret = api_secret or config.data_sources.coinbase_api_secret
        self.session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
    
    async def connect(self):
        """Initialize HTTP session"""
        self.session = aiohttp.ClientSession()
        logger.info("Coinbase client connected")
    
    async def close(self):
        """Clean up resources"""
        self._running = False
        if self._ws:
            await self._ws.close()
        if self.session:
            await self.session.close()
    
    def _sign(self, timestamp: str, method: str, path: str, body: str = "") -> str:
        """Generate HMAC signature for authenticated requests"""
        message = timestamp + method + path + body
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return signature
    
    # =========================================================================
    # PUBLIC REST API (No Auth Required)
    # =========================================================================
    
    async def get_candles(
        self, 
        symbol: str, 
        granularity: int = 900,
        start: Optional[int] = None,
        end: Optional[int] = None
    ) -> List[Dict]:
        """
        Get historical candles for a product.
        
        Args:
            symbol: Product ID (e.g. 'BTC-USD')
            granularity: Candle size in seconds (60, 300, 900, 3600, 21600, 86400)
            start: Start timestamp (Unix epoch seconds)
            end: End timestamp (Unix epoch seconds)
        """
        if not self.session:
            await self.connect()
            
        # Coinbase Exchange API (formerly Pro)
        url = f"{self.PUBLIC_REST_URL}/products/{symbol}/candles"
        params = {"granularity": granularity}
        if start:
            params["start"] = datetime.fromtimestamp(start, timezone.utc).isoformat()
        if end:
            params["end"] = datetime.fromtimestamp(end, timezone.utc).isoformat()
        
        async with self.session.get(url, params=params) as resp:
            if resp.status != 200:
                text = await resp.text()
                # Log warning but return empty list to allow retry/skip logic
                logger.warning(f"Coinbase API error: {resp.status} - {text}")
                return []
            
            # Returns [time, low, high, open, close, volume]
            return await resp.json()

    async def get_price(self, symbol: str = "BTC-USD") -> CryptoPrice:
        """
        Get current price for a trading pair.
        Uses public API, no authentication needed.
        """
        if not self.session:
            await self.connect()
        
        url = f"{self.PUBLIC_REST_URL}/products/{symbol}/ticker"
        
        async with self.session.get(url) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"Coinbase API error: {resp.status} - {text}")
            
            data = await resp.json()
            
            return CryptoPrice(
                symbol=symbol,
                price=Decimal(data["price"]),
                bid=Decimal(data["bid"]),
                ask=Decimal(data["ask"]),
                volume_24h=Decimal(data["volume"]),
                timestamp=datetime.fromisoformat(data["time"].replace("Z", "+00:00")),
                exchange="coinbase"
            )
    
    async def get_orderbook(self, symbol: str = "BTC-USD", level: int = 2) -> Dict:
        """
        Get order book for a trading pair.
        
        Args:
            symbol: Trading pair
            level: 1 = best bid/ask, 2 = top 50, 3 = full book
        """
        if not self.session:
            await self.connect()
        
        url = f"{self.PUBLIC_REST_URL}/products/{symbol}/book?level={level}"
        
        async with self.session.get(url) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"Coinbase API error: {resp.status} - {text}")
            
            return await resp.json()
    
    async def get_products(self) -> List[Dict]:
        """Get list of available trading pairs"""
        if not self.session:
            await self.connect()
        
        url = f"{self.PUBLIC_REST_URL}/products"
        
        async with self.session.get(url) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"Coinbase API error: {resp.status} - {text}")
            
            return await resp.json()
    
    # =========================================================================
    # WEBSOCKET STREAMING
    # =========================================================================
    
    async def stream_prices(
        self,
        symbols: List[str],
        callback: Callable[[CryptoPrice], Awaitable[None]],
        include_orderbook: bool = False
    ):
        """
        Stream real-time price updates via WebSocket.
        
        This is the core method for latency arbitrage - provides sub-second
        price updates that can be compared against Kalshi quotes.
        
        Args:
            symbols: List of trading pairs (e.g., ["BTC-USD", "ETH-USD"])
            callback: Async function called with each price update
            include_orderbook: Also stream level2 orderbook updates
        """
        self._running = True
        
        channels = ["ticker"]
        if include_orderbook:
            channels.append("level2")
        
        subscribe_msg = {
            "type": "subscribe",
            "product_ids": symbols,
            "channels": channels
        }
        
        while self._running:
            try:
                async with websockets.connect(self.PUBLIC_WS_URL) as ws:
                    self._ws = ws
                    await ws.send(json.dumps(subscribe_msg))
                    
                    logger.info(f"Subscribed to Coinbase feed for {symbols}")
                    
                    async for message in ws:
                        if not self._running:
                            break
                        
                        try:
                            data = json.loads(message)
                            msg_type = data.get("type")
                            
                            if msg_type == "ticker":
                                price = self._parse_ticker(data)
                                if price:
                                    await callback(price)
                            
                            elif msg_type == "subscriptions":
                                logger.debug(f"Subscription confirmed: {data}")
                            
                            elif msg_type == "error":
                                logger.error(f"WebSocket error: {data}")
                        
                        except json.JSONDecodeError:
                            logger.warning(f"Invalid message: {message[:100]}")
                        except Exception as e:
                            logger.error(f"Error processing message: {e}")
            
            except websockets.ConnectionClosed:
                if self._running:
                    logger.warning("WebSocket disconnected, reconnecting...")
                    await asyncio.sleep(1)
            except Exception as e:
                if self._running:
                    logger.error(f"WebSocket error: {e}, reconnecting...")
                    await asyncio.sleep(5)
    
    async def stream_orderbook(
        self,
        symbols: List[str],
        callback: Callable[[Dict], Awaitable[None]]
    ):
        """
        Stream real-time orderbook updates.
        
        Provides level2 (top 50 levels) orderbook changes.
        """
        self._running = True
        
        subscribe_msg = {
            "type": "subscribe",
            "product_ids": symbols,
            "channels": ["level2"]
        }
        
        while self._running:
            try:
                async with websockets.connect(self.PUBLIC_WS_URL) as ws:
                    self._ws = ws
                    await ws.send(json.dumps(subscribe_msg))
                    
                    async for message in ws:
                        if not self._running:
                            break
                        
                        try:
                            data = json.loads(message)
                            if data.get("type") in ["snapshot", "l2update"]:
                                await callback(data)
                        except Exception as e:
                            logger.error(f"Error processing orderbook: {e}")
            
            except websockets.ConnectionClosed:
                if self._running:
                    await asyncio.sleep(1)
    
    def _parse_ticker(self, data: Dict) -> Optional[CryptoPrice]:
        """Parse WebSocket ticker message into CryptoPrice"""
        try:
            return CryptoPrice(
                symbol=data["product_id"],
                price=Decimal(data["price"]),
                bid=Decimal(data.get("best_bid", data["price"])),
                ask=Decimal(data.get("best_ask", data["price"])),
                volume_24h=Decimal(data.get("volume_24h", "0")),
                timestamp=datetime.fromisoformat(data["time"].replace("Z", "+00:00")),
                exchange="coinbase"
            )
        except (KeyError, ValueError) as e:
            logger.warning(f"Failed to parse ticker: {e}")
            return None
    
    # =========================================================================
    # LATENCY ARBITRAGE HELPERS
    # =========================================================================
    
    async def get_btc_price(self) -> CryptoPrice:
        """Convenience method for BTC price"""
        return await self.get_price("BTC-USD")
    
    async def get_eth_price(self) -> CryptoPrice:
        """Convenience method for ETH price"""
        return await self.get_price("ETH-USD")
    
    def calculate_price_threshold_prob(
        self,
        current_price: Decimal,
        threshold: Decimal,
        volatility_pct: Decimal = Decimal("0.02"),
        time_to_expiry_hours: float = 24
    ) -> Decimal:
        """
        Estimate probability of price exceeding threshold.
        
        Simple model using log-normal assumption.
        For more accuracy, use historical volatility or options-implied vol.
        
        Args:
            current_price: Current spot price
            threshold: Target price threshold
            volatility_pct: Assumed daily volatility (e.g., 0.02 = 2%)
            time_to_expiry_hours: Hours until market settles
        
        Returns:
            Estimated probability (0-1)
        """
        import math
        
        # Adjust volatility for time period
        time_factor = math.sqrt(time_to_expiry_hours / 24)
        adj_vol = float(volatility_pct) * time_factor
        
        # Log-normal CDF approximation
        if current_price <= 0:
            return Decimal("0")
        
        log_ratio = math.log(float(threshold) / float(current_price))
        z_score = log_ratio / adj_vol
        
        # Standard normal CDF approximation
        prob_below = 0.5 * (1 + math.erf(z_score / math.sqrt(2)))
        prob_above = 1 - prob_below
        
        return Decimal(str(round(prob_above, 4)))


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

async def create_coinbase_client() -> CoinbaseClient:
    """Factory function to create and connect a Coinbase client"""
    client = CoinbaseClient()
    await client.connect()
    return client


# =============================================================================
# STANDALONE PRICE MONITOR
# =============================================================================

async def monitor_crypto_prices(
    symbols: List[str] = None,
    interval_seconds: float = 1.0
):
    """
    Simple price monitoring for testing.
    Prints prices to console.
    """
    symbols = symbols or ["BTC-USD", "ETH-USD"]
    client = await create_coinbase_client()
    
    async def print_price(price: CryptoPrice):
        print(f"[{price.timestamp.strftime('%H:%M:%S.%f')[:-3]}] "
              f"{price.symbol}: ${price.price:,.2f} "
              f"(bid: ${price.bid:,.2f}, ask: ${price.ask:,.2f})")
    
    try:
        await client.stream_prices(symbols, print_price)
    except KeyboardInterrupt:
        pass
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(monitor_crypto_prices())
