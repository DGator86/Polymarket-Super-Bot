"""
Kalshi WebSocket Client

Connects to Kalshi's WebSocket API for real-time orderbook updates.
Handles:
- Authentication with RSA-PSS signing
- orderbook_snapshot and orderbook_delta messages
- Automatic reconnection and resubscription
- Heartbeat/ping management

WebSocket URL: wss://api.elections.kalshi.com/trade-api/ws/v2
"""
from __future__ import annotations
import asyncio
import base64
import json
import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Callable, Set
from dataclasses import dataclass

import websockets
from websockets.exceptions import ConnectionClosed
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from config import config
from core.orderbook import OrderbookManager

logger = logging.getLogger(__name__)


@dataclass
class WSConfig:
    """WebSocket configuration"""
    url: str = "wss://api.elections.kalshi.com/trade-api/ws/v2"
    reconnect_delay: float = 5.0
    ping_interval: float = 30.0
    ping_timeout: float = 10.0
    max_reconnect_attempts: int = 10


class KalshiWebSocket:
    """
    Kalshi WebSocket client for real-time orderbook updates.
    
    Usage:
        ws = KalshiWebSocket(book_manager)
        await ws.connect()
        await ws.subscribe(["KXBTC15M-xxx", "KXETH15M-xxx"])
        # Books are updated automatically via book_manager
    """
    
    def __init__(
        self,
        book_manager: OrderbookManager,
        config: WSConfig = None,
        use_auth: bool = True
    ):
        self.books = book_manager
        self.config = config or WSConfig()
        self.use_auth = use_auth
        
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._private_key = None
        self._api_key = getattr(config, 'kalshi', None) and config.kalshi.api_key
        self._subscribed_tickers: Set[str] = set()
        self._running = False
        self._reconnect_count = 0
        
        # Callbacks
        self._on_connected: Optional[Callable] = None
        self._on_disconnected: Optional[Callable] = None
        
    def _load_private_key(self) -> None:
        """Load RSA private key for authentication"""
        try:
            from config import config as cfg
            key_path = cfg.kalshi.private_key_path
            with open(key_path, 'rb') as f:
                self._private_key = serialization.load_pem_private_key(f.read(), password=None)
            self._api_key = cfg.kalshi.api_key
            logger.info("Loaded Kalshi private key for WebSocket auth")
        except Exception as e:
            logger.warning(f"Failed to load private key: {e}")
            self.use_auth = False
            
    def _sign(self, timestamp_ms: int, method: str, path: str) -> str:
        """Sign a message for authentication"""
        if not self._private_key:
            raise RuntimeError("No private key loaded")
        message = f"{timestamp_ms}{method}{path}".encode()
        signature = self._private_key.sign(
            message,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode()
        
    def _auth_headers(self) -> Dict[str, str]:
        """Generate authentication headers for WebSocket connection"""
        if not self.use_auth or not self._private_key:
            return {}
            
        timestamp_ms = int(time.time() * 1000)
        # For WebSocket, sign the connection path
        path = "/trade-api/ws/v2"
        signature = self._sign(timestamp_ms, "GET", path)
        
        return {
            "KALSHI-ACCESS-KEY": self._api_key,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": str(timestamp_ms)
        }
        
    async def connect(self) -> bool:
        """Connect to WebSocket"""
        if self.use_auth:
            self._load_private_key()
            
        try:
            headers = self._auth_headers()
            self._ws = await websockets.connect(
                self.config.url,
                extra_headers=headers if headers else None,
                ping_interval=self.config.ping_interval,
                ping_timeout=self.config.ping_timeout
            )
            self._running = True
            self._reconnect_count = 0
            logger.info(f"Connected to Kalshi WebSocket")
            
            if self._on_connected:
                await self._on_connected()
                
            return True
            
        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            return False
            
    async def disconnect(self) -> None:
        """Disconnect from WebSocket"""
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None
        logger.info("Disconnected from Kalshi WebSocket")
        
    async def subscribe(self, tickers: List[str]) -> None:
        """Subscribe to orderbook updates for given tickers"""
        if not self._ws:
            logger.warning("Cannot subscribe - not connected")
            return
            
        for ticker in tickers:
            if ticker in self._subscribed_tickers:
                continue
                
            msg = {
                "id": int(time.time() * 1000),
                "cmd": "subscribe",
                "params": {
                    "channels": ["orderbook_delta"],
                    "market_ticker": ticker
                }
            }
            
            await self._ws.send(json.dumps(msg))
            self._subscribed_tickers.add(ticker)
            logger.debug(f"Subscribed to {ticker}")
            
    async def unsubscribe(self, tickers: List[str]) -> None:
        """Unsubscribe from orderbook updates"""
        if not self._ws:
            return
            
        for ticker in tickers:
            if ticker not in self._subscribed_tickers:
                continue
                
            msg = {
                "id": int(time.time() * 1000),
                "cmd": "unsubscribe",
                "params": {
                    "channels": ["orderbook_delta"],
                    "market_ticker": ticker
                }
            }
            
            await self._ws.send(json.dumps(msg))
            self._subscribed_tickers.discard(ticker)
            
    async def _handle_message(self, raw_msg: str) -> None:
        """Process incoming WebSocket message"""
        try:
            msg = json.loads(raw_msg)
            msg_type = msg.get("type")
            
            if msg_type == "orderbook_snapshot":
                # Full orderbook snapshot
                data = msg.get("msg", {})
                ticker = data.get("market_ticker")
                seq = data.get("seq", 0)
                yes_bids = data.get("yes", [])
                no_bids = data.get("no", [])
                
                if ticker:
                    self.books.on_snapshot(ticker, yes_bids, no_bids, seq)
                    logger.debug(f"Snapshot: {ticker} seq={seq}")
                    
            elif msg_type == "orderbook_delta":
                # Incremental update
                data = msg.get("msg", {})
                ticker = data.get("market_ticker")
                seq = data.get("seq", 0)
                price = data.get("price", 0)
                delta = data.get("delta", 0)
                side = data.get("side", "yes")
                
                if ticker:
                    # Delta is the new quantity at this price level
                    # If delta is 0, the level is removed
                    current_book = self.books.get_book(ticker)
                    if current_book:
                        if side == "yes":
                            current_qty = current_book.yes_bids.levels.get(price, 0)
                        else:
                            current_qty = current_book.no_bids.levels.get(price, 0)
                        new_qty = max(0, current_qty + delta)
                    else:
                        new_qty = max(0, delta)
                        
                    success = self.books.on_delta(ticker, side, price, new_qty, seq)
                    if not success:
                        # Need to resubscribe for fresh snapshot
                        logger.warning(f"Missed deltas for {ticker}, resubscribing")
                        await self._resubscribe(ticker)
                        
            elif msg_type == "subscribed":
                logger.debug(f"Subscription confirmed: {msg}")
                
            elif msg_type == "error":
                logger.error(f"WebSocket error: {msg}")
                
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON: {raw_msg[:100]}")
        except Exception as e:
            logger.error(f"Error handling message: {e}")
            
    async def _resubscribe(self, ticker: str) -> None:
        """Resubscribe to get fresh snapshot"""
        self._subscribed_tickers.discard(ticker)
        await asyncio.sleep(0.1)
        await self.subscribe([ticker])
        
    async def run(self) -> None:
        """Main loop - receive and process messages"""
        while self._running:
            try:
                if not self._ws:
                    if not await self.connect():
                        await asyncio.sleep(self.config.reconnect_delay)
                        continue
                        
                    # Resubscribe to all tickers after reconnect
                    tickers = list(self._subscribed_tickers)
                    self._subscribed_tickers.clear()
                    await self.subscribe(tickers)
                    
                msg = await asyncio.wait_for(
                    self._ws.recv(),
                    timeout=self.config.ping_timeout * 2
                )
                await self._handle_message(msg)
                
            except ConnectionClosed as e:
                logger.warning(f"WebSocket connection closed: {e}")
                self._ws = None
                self._reconnect_count += 1
                
                if self._reconnect_count > self.config.max_reconnect_attempts:
                    logger.error("Max reconnection attempts reached")
                    self._running = False
                    break
                    
                if self._on_disconnected:
                    await self._on_disconnected()
                    
                await asyncio.sleep(self.config.reconnect_delay)
                
            except asyncio.TimeoutError:
                logger.debug("WebSocket timeout - sending ping")
                if self._ws:
                    try:
                        await self._ws.ping()
                    except:
                        self._ws = None
                        
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                await asyncio.sleep(1)


# Simplified polling fallback for testing
class OrderbookPoller:
    """
    REST-based orderbook polling fallback.
    Use this when WebSocket is unavailable or for testing.
    """
    
    def __init__(
        self,
        book_manager: OrderbookManager,
        kalshi_client,
        poll_interval: float = 1.0
    ):
        self.books = book_manager
        self.kalshi = kalshi_client
        self.poll_interval = poll_interval
        self._tickers: Set[str] = set()
        self._running = False
        self._seq = 0
        
    def add_tickers(self, tickers: List[str]) -> None:
        self._tickers.update(tickers)
        
    def remove_tickers(self, tickers: List[str]) -> None:
        self._tickers -= set(tickers)
        
    async def poll_once(self) -> int:
        """Poll all tickers once, return number of successful updates"""
        updated = 0
        for ticker in list(self._tickers):
            try:
                orderbook = await self.kalshi.get_orderbook(ticker, depth=10)
                ob_data = orderbook.get("orderbook", {})
                
                yes_data = ob_data.get("yes", {})
                no_data = ob_data.get("no", {})
                
                # Convert to [[price, qty], ...] format
                yes_bids = [[int(p), q] for p, q in yes_data.items()] if isinstance(yes_data, dict) else yes_data
                no_bids = [[int(p), q] for p, q in no_data.items()] if isinstance(no_data, dict) else no_data
                
                self._seq += 1
                self.books.on_snapshot(ticker, yes_bids or [], no_bids or [], self._seq)
                updated += 1
                
            except Exception as e:
                logger.debug(f"Failed to poll {ticker}: {e}")
                
        return updated
        
    async def run(self) -> None:
        """Polling loop"""
        self._running = True
        while self._running:
            if self._tickers:
                updated = await self.poll_once()
                logger.debug(f"Polled {updated}/{len(self._tickers)} orderbooks")
            await asyncio.sleep(self.poll_interval)
            
    def stop(self) -> None:
        self._running = False


if __name__ == "__main__":
    import asyncio
    from core.orderbook import OrderbookManager
    
    async def test():
        print("=== KALSHI WEBSOCKET TEST ===")
        
        books = OrderbookManager()
        ws = KalshiWebSocket(books, use_auth=True)
        
        # Test connection
        connected = await ws.connect()
        print(f"Connected: {connected}")
        
        if connected:
            # Subscribe to test ticker
            await ws.subscribe(["KXBTC15M-26JAN170530-30"])
            
            # Listen for a few messages
            for i in range(10):
                try:
                    msg = await asyncio.wait_for(ws._ws.recv(), timeout=5.0)
                    print(f"Message {i}: {msg[:200]}...")
                except asyncio.TimeoutError:
                    print(f"Timeout {i}")
                except Exception as e:
                    print(f"Error: {e}")
                    break
                    
            await ws.disconnect()
            
    asyncio.run(test())
