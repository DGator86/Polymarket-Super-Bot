#!/usr/bin/env python3
"""
Kalshi 15-Minute Crypto Latency Arbitrage Bot

Exploits pricing inefficiencies between real-time crypto prices and Kalshi's
15-minute crypto prediction markets.

Strategy:
- Monitor real-time BTC/ETH prices from multiple exchanges (Binance, Coinbase, Kraken)
- Compare to Kalshi market implied probabilities
- When significant divergence detected, execute trades before market adjusts
- Focus on the final 5 minutes of each 15-minute window where edge is highest

Author: Built for FINAL_GNOSIS Trading System
"""

import os
import sys
import json
import time
import asyncio
import logging
import hashlib
import hmac
import base64
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Load environment variables from .env file if it exists
def load_dotenv():
    """Simple .env file loader"""
    env_paths = [
        Path(__file__).parent / '.env',
        Path.cwd() / '.env',
        Path('/opt/kalshi-latency-bot/.env'),
    ]
    for env_path in env_paths:
        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        os.environ.setdefault(key.strip(), value.strip())
            break

load_dotenv()
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple, Callable
from enum import Enum
from collections import deque
import statistics
import threading
from abc import ABC, abstractmethod

# Third-party imports (install with pip)
try:
    import aiohttp
    import websockets
    import numpy as np
    from scipy.stats import norm
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.backends import default_backend
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Install with: pip install aiohttp websockets numpy scipy cryptography")
    sys.exit(1)

# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class Config:
    """Bot configuration - modify these for your setup"""

    # Kalshi API credentials (set via environment variables)
    # API Key ID from Kalshi
    KALSHI_API_KEY: str = field(default_factory=lambda: os.getenv("KALSHI_API_KEY", ""))
    # Path to RSA private key file, or the key content itself
    KALSHI_PRIVATE_KEY_PATH: str = field(default_factory=lambda: os.getenv("KALSHI_PRIVATE_KEY_PATH", ""))
    # For demo/testing, use demo-api.kalshi.co; for production use trading-api.kalshi.com
    KALSHI_API_BASE: str = field(default_factory=lambda: os.getenv("KALSHI_API_BASE", "https://trading-api.kalshi.com/trade-api/v2"))
    KALSHI_WS_URL: str = field(default_factory=lambda: os.getenv("KALSHI_WS_URL", "wss://trading-api.kalshi.com/trade-api/ws/v2"))

    # Exchange API keys (optional - public endpoints work for price feeds)
    BINANCE_API_KEY: str = field(default_factory=lambda: os.getenv("BINANCE_API_KEY", ""))
    COINBASE_API_KEY: str = field(default_factory=lambda: os.getenv("COINBASE_API_KEY", ""))

    # Trading parameters
    MAX_POSITION_SIZE: int = 100  # Max contracts per position
    MIN_EDGE_THRESHOLD: float = 0.06  # 6% minimum edge to trade (balanced for safety + opportunity)
    MAX_SPREAD_COST: float = 0.02  # 2% max acceptable spread
    KELLY_FRACTION: float = 0.25  # Fraction of Kelly criterion to use

    # Latency parameters
    PRICE_STALE_MS: int = 500  # Price older than this is stale
    MIN_SOURCES_REQUIRED: int = 2  # Minimum price sources for trade
    LATENCY_WINDOW_SECONDS: int = 300  # Focus on last 5 minutes of each period

    # Risk limits
    MAX_DAILY_LOSS: float = 500.0  # Stop trading after this loss
    MAX_CONCURRENT_POSITIONS: int = 5
    MAX_SINGLE_TRADE_RISK: float = 100.0  # Max risk per trade in dollars

    # Market identifiers (Kalshi's hourly crypto price markets)
    # These are the series tickers for price-at-time markets
    CRYPTO_TICKERS: List[str] = field(default_factory=lambda: [
        "KXBTCD",   # Bitcoin price at time (e.g., "Bitcoin price on Jan 16, 2026 at 5pm EST?")
        "KXETHD",   # Ethereum price at time
        "KXSOLD",   # Solana price at time
        "KXXRPD",   # Ripple/XRP price at time
    ])
    
    # Mapping of Kalshi series to exchange symbols
    TICKER_TO_SYMBOL: Dict[str, str] = field(default_factory=lambda: {
        "KXBTCD": "BTC",
        "KXETHD": "ETH", 
        "KXSOLD": "SOL",
        "KXXRPD": "XRP",
        "KXBTC": "BTC",
        "KXETH": "ETH",
        "KXSOLE": "SOL",
        "KXXRP": "XRP",
    })

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "kalshi_latency_bot.log"

# =============================================================================
# LOGGING SETUP
# =============================================================================

def setup_logging(config: Config) -> logging.Logger:
    """Configure structured logging"""
    logger = logging.getLogger("KalshiLatencyBot")
    logger.setLevel(getattr(logging, config.LOG_LEVEL))

    # Console handler
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console_fmt = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%H:%M:%S'
    )
    console.setFormatter(console_fmt)

    # File handler
    file_handler = logging.FileHandler(config.LOG_FILE)
    file_handler.setLevel(logging.DEBUG)
    file_fmt = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'
    )
    file_handler.setFormatter(file_fmt)

    logger.addHandler(console)
    logger.addHandler(file_handler)

    return logger

# =============================================================================
# DATA STRUCTURES
# =============================================================================

class Side(Enum):
    YES = "yes"
    NO = "no"

@dataclass
class PriceUpdate:
    """Real-time price from an exchange"""
    source: str
    symbol: str
    price: float
    timestamp_ms: int
    bid: Optional[float] = None
    ask: Optional[float] = None
    volume_24h: Optional[float] = None

    @property
    def age_ms(self) -> int:
        return int(time.time() * 1000) - self.timestamp_ms

    @property
    def mid_price(self) -> float:
        if self.bid and self.ask:
            return (self.bid + self.ask) / 2
        return self.price

@dataclass
class KalshiMarket:
    """Kalshi market data"""
    ticker: str
    event_ticker: str
    title: str
    subtitle: str
    yes_bid: float
    yes_ask: float
    no_bid: float
    no_ask: float
    volume: int
    open_interest: int
    strike_price: Optional[float]  # For crypto: the price threshold
    expiration_time: datetime
    last_updated: datetime

    @property
    def yes_mid(self) -> float:
        return (self.yes_bid + self.yes_ask) / 2

    @property
    def no_mid(self) -> float:
        return (self.no_bid + self.no_ask) / 2

    @property
    def spread(self) -> float:
        return self.yes_ask - self.yes_bid

    @property
    def implied_prob_yes(self) -> float:
        return self.yes_mid

    @property
    def time_to_expiry_seconds(self) -> float:
        return (self.expiration_time - datetime.now(timezone.utc)).total_seconds()

@dataclass
class TradeSignal:
    """Generated trading signal"""
    market: KalshiMarket
    side: Side
    edge: float
    confidence: float
    fair_value: float
    market_price: float
    crypto_price: float
    recommended_size: int
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __str__(self):
        return (
            f"Signal: {self.market.ticker} {self.side.value.upper()} | "
            f"Edge: {self.edge:.2%} | Conf: {self.confidence:.2%} | "
            f"Fair: {self.fair_value:.3f} vs Market: {self.market_price:.3f}"
        )

@dataclass
class Position:
    """Active position tracking"""
    ticker: str
    side: Side
    quantity: int
    entry_price: float
    entry_time: datetime
    unrealized_pnl: float = 0.0

    @property
    def cost_basis(self) -> float:
        return self.quantity * self.entry_price

@dataclass
class TradeResult:
    """Executed trade result"""
    order_id: str
    ticker: str
    side: Side
    quantity: int
    price: float
    timestamp: datetime
    success: bool
    error: Optional[str] = None

# =============================================================================
# PRICE FEED AGGREGATOR
# =============================================================================

class PriceFeedManager:
    """
    Aggregates real-time prices from multiple exchanges.
    Uses websockets for minimal latency.
    """

    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.prices: Dict[str, Dict[str, PriceUpdate]] = {
            "BTC": {},
            "ETH": {},
            "SOL": {},
            "XRP": {},
        }
        self.callbacks: List[Callable[[PriceUpdate], None]] = []
        self._running = False
        self._tasks: List[asyncio.Task] = []

    def register_callback(self, callback: Callable[[PriceUpdate], None]):
        """Register callback for price updates"""
        self.callbacks.append(callback)

    async def start(self):
        """Start all price feeds"""
        self._running = True
        self._tasks = [
            asyncio.create_task(self._binance_feed()),
            asyncio.create_task(self._binance_us_feed()),
            asyncio.create_task(self._coinbase_feed()),
            asyncio.create_task(self._kraken_feed()),
            asyncio.create_task(self._bitstamp_feed()),
            asyncio.create_task(self._okx_feed()),
            asyncio.create_task(self._bybit_feed()),
            asyncio.create_task(self._gemini_feed()),
            asyncio.create_task(self._htx_feed()),
        ]
        self.logger.info("Price feeds started (9 exchanges: Binance, Binance US, Coinbase, Kraken, Bitstamp, OKX, Bybit, Gemini, HTX)")

    async def stop(self):
        """Stop all price feeds"""
        self._running = False
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self.logger.info("Price feeds stopped")

    def get_aggregated_price(self, symbol: str) -> Optional[Tuple[float, int]]:
        """
        Get volume-weighted average price from all sources.
        Returns (price, num_sources) or None if insufficient data.
        """
        symbol_prices = self.prices.get(symbol, {})
        valid_prices = []

        for source, update in symbol_prices.items():
            if update.age_ms < self.config.PRICE_STALE_MS:
                valid_prices.append(update)

        if len(valid_prices) < self.config.MIN_SOURCES_REQUIRED:
            return None

        # Volume-weighted average
        if all(p.volume_24h for p in valid_prices):
            total_volume = sum(p.volume_24h for p in valid_prices)
            vwap = sum(p.mid_price * p.volume_24h for p in valid_prices) / total_volume
        else:
            # Simple average if no volume data
            vwap = statistics.mean(p.mid_price for p in valid_prices)

        return (vwap, len(valid_prices))

    def _update_price(self, update: PriceUpdate):
        """Process incoming price update"""
        if update.symbol not in self.prices:
            self.prices[update.symbol] = {}
        self.prices[update.symbol][update.source] = update

        for callback in self.callbacks:
            try:
                callback(update)
            except Exception as e:
                self.logger.error(f"Callback error: {e}")

    async def _binance_feed(self):
        """Binance WebSocket price feed"""
        url = "wss://stream.binance.com:9443/ws"
        streams = ["btcusdt@bookTicker", "ethusdt@bookTicker"]
        subscribe_msg = {
            "method": "SUBSCRIBE",
            "params": streams,
            "id": 1
        }

        while self._running:
            try:
                async with websockets.connect(url) as ws:
                    await ws.send(json.dumps(subscribe_msg))
                    self.logger.debug("Binance feed connected")

                    async for msg in ws:
                        if not self._running:
                            break
                        data = json.loads(msg)
                        if "s" in data:  # Book ticker update
                            symbol = "BTC" if "BTC" in data["s"] else "ETH"
                            update = PriceUpdate(
                                source="binance",
                                symbol=symbol,
                                price=(float(data["b"]) + float(data["a"])) / 2,
                                bid=float(data["b"]),
                                ask=float(data["a"]),
                                timestamp_ms=int(time.time() * 1000),
                            )
                            self._update_price(update)
            except Exception as e:
                # Binance global is often blocked in US (HTTP 451) - silently retry
                if "451" not in str(e):
                    self.logger.warning(f"Binance feed error: {e}")
                await asyncio.sleep(30)  # Longer retry for blocked feed

    async def _coinbase_feed(self):
        """Coinbase WebSocket price feed"""
        url = "wss://ws-feed.exchange.coinbase.com"
        subscribe_msg = {
            "type": "subscribe",
            "product_ids": ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD"],
            "channels": ["ticker"]
        }

        while self._running:
            try:
                async with websockets.connect(url) as ws:
                    await ws.send(json.dumps(subscribe_msg))
                    self.logger.debug("Coinbase feed connected")

                    async for msg in ws:
                        if not self._running:
                            break
                        data = json.loads(msg)
                        if data.get("type") == "ticker":
                            product_id = data.get("product_id", "")
                            if "BTC" in product_id:
                                symbol = "BTC"
                            elif "ETH" in product_id:
                                symbol = "ETH"
                            elif "SOL" in product_id:
                                symbol = "SOL"
                            elif "XRP" in product_id:
                                symbol = "XRP"
                            else:
                                continue
                            update = PriceUpdate(
                                source="coinbase",
                                symbol=symbol,
                                price=float(data["price"]),
                                bid=float(data.get("best_bid", data["price"])),
                                ask=float(data.get("best_ask", data["price"])),
                                timestamp_ms=int(time.time() * 1000),
                                volume_24h=float(data.get("volume_24h", 0)),
                            )
                            self._update_price(update)
            except Exception as e:
                self.logger.warning(f"Coinbase feed error: {e}")
                await asyncio.sleep(1)

    async def _kraken_feed(self):
        """Kraken WebSocket price feed"""
        url = "wss://ws.kraken.com"
        subscribe_msg = {
            "event": "subscribe",
            "pair": ["XBT/USD", "ETH/USD", "SOL/USD", "XRP/USD"],
            "subscription": {"name": "ticker"}
        }

        while self._running:
            try:
                async with websockets.connect(url) as ws:
                    await ws.send(json.dumps(subscribe_msg))
                    self.logger.debug("Kraken feed connected")

                    async for msg in ws:
                        if not self._running:
                            break
                        data = json.loads(msg)
                        if isinstance(data, list) and len(data) >= 4:
                            ticker_data = data[1]
                            pair = data[3]
                            if "XBT" in pair:
                                symbol = "BTC"
                            elif "ETH" in pair:
                                symbol = "ETH"
                            elif "SOL" in pair:
                                symbol = "SOL"
                            elif "XRP" in pair:
                                symbol = "XRP"
                            else:
                                continue

                            # Kraken ticker format: [ask, bid, close, volume, vwap, ...]
                            if isinstance(ticker_data, dict):
                                update = PriceUpdate(
                                    source="kraken",
                                    symbol=symbol,
                                    price=float(ticker_data["c"][0]),
                                    bid=float(ticker_data["b"][0]),
                                    ask=float(ticker_data["a"][0]),
                                    timestamp_ms=int(time.time() * 1000),
                                    volume_24h=float(ticker_data["v"][1]),
                                )
                                self._update_price(update)
            except Exception as e:
                self.logger.warning(f"Kraken feed error: {e}")
                await asyncio.sleep(1)

    async def _binance_us_feed(self):
        """Binance.US WebSocket price feed (US-accessible)"""
        url = "wss://stream.binance.us:9443/ws"
        streams = ["btcusd@bookTicker", "ethusd@bookTicker", "solusd@bookTicker", "xrpusd@bookTicker"]
        subscribe_msg = {
            "method": "SUBSCRIBE",
            "params": streams,
            "id": 1
        }

        while self._running:
            try:
                async with websockets.connect(url) as ws:
                    await ws.send(json.dumps(subscribe_msg))
                    self.logger.debug("Binance.US feed connected")

                    async for msg in ws:
                        if not self._running:
                            break
                        data = json.loads(msg)
                        if "s" in data:  # Book ticker update
                            ticker = data["s"].upper()
                            if "BTC" in ticker:
                                symbol = "BTC"
                            elif "ETH" in ticker:
                                symbol = "ETH"
                            elif "SOL" in ticker:
                                symbol = "SOL"
                            elif "XRP" in ticker:
                                symbol = "XRP"
                            else:
                                continue
                            update = PriceUpdate(
                                source="binance_us",
                                symbol=symbol,
                                price=(float(data["b"]) + float(data["a"])) / 2,
                                bid=float(data["b"]),
                                ask=float(data["a"]),
                                timestamp_ms=int(time.time() * 1000),
                            )
                            self._update_price(update)
            except Exception as e:
                self.logger.warning(f"Binance.US feed error: {e}")
                await asyncio.sleep(5)

    async def _bitstamp_feed(self):
        """Bitstamp WebSocket price feed"""
        url = "wss://ws.bitstamp.net"

        while self._running:
            try:
                async with websockets.connect(url) as ws:
                    # Subscribe to BTC, ETH, SOL, XRP live trades
                    for channel in ["live_trades_btcusd", "live_trades_ethusd", "live_trades_solusd", "live_trades_xrpusd"]:
                        subscribe_msg = {
                            "event": "bts:subscribe",
                            "data": {"channel": channel}
                        }
                        await ws.send(json.dumps(subscribe_msg))
                    self.logger.debug("Bitstamp feed connected")

                    async for msg in ws:
                        if not self._running:
                            break
                        data = json.loads(msg)
                        if data.get("event") == "trade":
                            channel = data.get("channel", "").lower()
                            if "btc" in channel:
                                symbol = "BTC"
                            elif "eth" in channel:
                                symbol = "ETH"
                            elif "sol" in channel:
                                symbol = "SOL"
                            elif "xrp" in channel:
                                symbol = "XRP"
                            else:
                                continue
                            trade_data = data.get("data", {})
                            update = PriceUpdate(
                                source="bitstamp",
                                symbol=symbol,
                                price=float(trade_data.get("price", 0)),
                                timestamp_ms=int(time.time() * 1000),
                            )
                            self._update_price(update)
            except Exception as e:
                self.logger.warning(f"Bitstamp feed error: {e}")
                await asyncio.sleep(5)

    async def _okx_feed(self):
        """OKX WebSocket price feed"""
        url = "wss://ws.okx.com:8443/ws/v5/public"
        subscribe_msg = {
            "op": "subscribe",
            "args": [
                {"channel": "tickers", "instId": "BTC-USDT"},
                {"channel": "tickers", "instId": "ETH-USDT"},
                {"channel": "tickers", "instId": "SOL-USDT"},
                {"channel": "tickers", "instId": "XRP-USDT"},
            ]
        }

        while self._running:
            try:
                async with websockets.connect(url) as ws:
                    await ws.send(json.dumps(subscribe_msg))
                    self.logger.debug("OKX feed connected")

                    async for msg in ws:
                        if not self._running:
                            break
                        data = json.loads(msg)
                        if "data" in data and data["data"]:
                            ticker = data["data"][0]
                            inst_id = ticker.get("instId", "")
                            if "BTC" in inst_id:
                                symbol = "BTC"
                            elif "ETH" in inst_id:
                                symbol = "ETH"
                            elif "SOL" in inst_id:
                                symbol = "SOL"
                            elif "XRP" in inst_id:
                                symbol = "XRP"
                            else:
                                continue
                            update = PriceUpdate(
                                source="okx",
                                symbol=symbol,
                                price=float(ticker.get("last", 0)),
                                bid=float(ticker.get("bidPx", 0)),
                                ask=float(ticker.get("askPx", 0)),
                                timestamp_ms=int(time.time() * 1000),
                                volume_24h=float(ticker.get("vol24h", 0)),
                            )
                            self._update_price(update)
            except Exception as e:
                self.logger.warning(f"OKX feed error: {e}")
                await asyncio.sleep(5)

    async def _bybit_feed(self):
        """Bybit WebSocket price feed"""
        url = "wss://stream.bybit.com/v5/public/spot"
        subscribe_msg = {
            "op": "subscribe",
            "args": ["tickers.BTCUSDT", "tickers.ETHUSDT", "tickers.SOLUSDT", "tickers.XRPUSDT"]
        }

        while self._running:
            try:
                async with websockets.connect(url) as ws:
                    await ws.send(json.dumps(subscribe_msg))
                    self.logger.debug("Bybit feed connected")

                    async for msg in ws:
                        if not self._running:
                            break
                        data = json.loads(msg)
                        if data.get("topic", "").startswith("tickers."):
                            ticker_data = data.get("data", {})
                            symbol_raw = ticker_data.get("symbol", "")
                            if "BTC" in symbol_raw:
                                symbol = "BTC"
                            elif "ETH" in symbol_raw:
                                symbol = "ETH"
                            elif "SOL" in symbol_raw:
                                symbol = "SOL"
                            elif "XRP" in symbol_raw:
                                symbol = "XRP"
                            else:
                                continue
                            update = PriceUpdate(
                                source="bybit",
                                symbol=symbol,
                                price=float(ticker_data.get("lastPrice", 0)),
                                bid=float(ticker_data.get("bid1Price", 0)),
                                ask=float(ticker_data.get("ask1Price", 0)),
                                timestamp_ms=int(time.time() * 1000),
                                volume_24h=float(ticker_data.get("volume24h", 0)),
                            )
                            self._update_price(update)
            except Exception as e:
                self.logger.warning(f"Bybit feed error: {e}")
                await asyncio.sleep(5)

    async def _gemini_feed(self):
        """Gemini WebSocket price feed (US-based exchange)"""
        # Gemini uses separate connections per symbol
        symbols = [("btcusd", "BTC"), ("ethusd", "ETH"), ("solusd", "SOL")]
        
        async def connect_symbol(pair: str, symbol: str):
            url = f"wss://api.gemini.com/v1/marketdata/{pair}"
            while self._running:
                try:
                    async with websockets.connect(url) as ws:
                        self.logger.debug(f"Gemini {symbol} feed connected")
                        
                        async for msg in ws:
                            if not self._running:
                                break
                            data = json.loads(msg)
                            if data.get("type") == "update":
                                events = data.get("events", [])
                                for event in events:
                                    if event.get("type") == "trade":
                                        update = PriceUpdate(
                                            source="gemini",
                                            symbol=symbol,
                                            price=float(event.get("price", 0)),
                                            timestamp_ms=int(time.time() * 1000),
                                        )
                                        self._update_price(update)
                except Exception as e:
                    self.logger.warning(f"Gemini {symbol} feed error: {e}")
                    await asyncio.sleep(5)
        
        # Connect to all symbols concurrently
        tasks = [connect_symbol(pair, sym) for pair, sym in symbols]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _htx_feed(self):
        """HTX (Huobi) WebSocket price feed"""
        url = "wss://api.huobi.pro/ws"
        
        while self._running:
            try:
                async with websockets.connect(url) as ws:
                    # Subscribe to ticker for each symbol
                    for pair in ["btcusdt", "ethusdt", "solusdt", "xrpusdt"]:
                        subscribe_msg = {
                            "sub": f"market.{pair}.ticker",
                            "id": f"ticker_{pair}"
                        }
                        await ws.send(json.dumps(subscribe_msg))
                    self.logger.debug("HTX feed connected")

                    async for msg in ws:
                        if not self._running:
                            break
                        # HTX sends gzipped data
                        import gzip
                        try:
                            data = json.loads(gzip.decompress(msg).decode('utf-8'))
                        except:
                            data = json.loads(msg) if isinstance(msg, str) else {}
                        
                        # Handle ping/pong
                        if "ping" in data:
                            await ws.send(json.dumps({"pong": data["ping"]}))
                            continue
                        
                        ch = data.get("ch", "")
                        if "ticker" in ch and "tick" in data:
                            tick = data["tick"]
                            if "btc" in ch:
                                symbol = "BTC"
                            elif "eth" in ch:
                                symbol = "ETH"
                            elif "sol" in ch:
                                symbol = "SOL"
                            elif "xrp" in ch:
                                symbol = "XRP"
                            else:
                                continue
                            update = PriceUpdate(
                                source="htx",
                                symbol=symbol,
                                price=float(tick.get("close", 0)),
                                bid=float(tick.get("bid", 0)),
                                ask=float(tick.get("ask", 0)),
                                timestamp_ms=int(time.time() * 1000),
                                volume_24h=float(tick.get("vol", 0)),
                            )
                            self._update_price(update)
            except Exception as e:
                self.logger.warning(f"HTX feed error: {e}")
                await asyncio.sleep(5)

# =============================================================================
# KALSHI API CLIENT
# =============================================================================

class KalshiClient:
    """
    Kalshi API client for market data and trading.
    Handles RSA-PSS authentication as per Kalshi API v2.
    """

    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self._session: Optional[aiohttp.ClientSession] = None
        self._private_key = None
        self._authenticated = False

    def _load_private_key(self):
        """Load RSA private key from file or environment"""
        key_path = self.config.KALSHI_PRIVATE_KEY_PATH
        
        if not key_path:
            self.logger.warning("No Kalshi private key path - running in read-only mode")
            return None
        
        try:
            # Check if key_path is a file path or the key content itself
            if os.path.isfile(key_path):
                with open(key_path, "rb") as key_file:
                    private_key = serialization.load_pem_private_key(
                        key_file.read(),
                        password=None,
                        backend=default_backend()
                    )
            else:
                # Assume it's the key content itself (from environment variable)
                key_content = key_path
                if not key_content.startswith("-----BEGIN"):
                    self.logger.error("Invalid private key format")
                    return None
                private_key = serialization.load_pem_private_key(
                    key_content.encode(),
                    password=None,
                    backend=default_backend()
                )
            return private_key
        except Exception as e:
            self.logger.error(f"Failed to load private key: {e}")
            return None

    def _sign_pss(self, message: str) -> str:
        """Sign a message using RSA-PSS with SHA256"""
        if not self._private_key:
            raise ValueError("Private key not loaded")
        
        signature = self._private_key.sign(
            message.encode('utf-8'),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH  # Must match Kalshi's expected salt length
            ),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode('utf-8')

    async def initialize(self):
        """Initialize session and load credentials"""
        self._session = aiohttp.ClientSession()
        self._private_key = self._load_private_key()
        
        if self._private_key and self.config.KALSHI_API_KEY:
            # Test authentication by fetching balance
            try:
                balance = await self.get_balance()
                self._authenticated = True
                self.logger.info(f"Authenticated with Kalshi (balance: ${balance:.2f})")
            except Exception as e:
                self.logger.error(f"Authentication test failed: {e}")
                self._authenticated = False
        else:
            self.logger.warning("Running in read-only mode (no credentials)")

    async def close(self):
        """Close session"""
        if self._session:
            await self._session.close()

    def _get_auth_headers(self, method: str, path: str) -> Dict[str, str]:
        """Generate RSA-PSS authentication headers for a request"""
        timestamp = str(int(time.time() * 1000))
        
        # Build full path for signing (must include /trade-api/v2 prefix)
        # The path parameter is relative to the API base, so we need to include the API path prefix
        full_path = f"/trade-api/v2{path}"
        path_without_query = full_path.split('?')[0]
        msg_string = f"{timestamp}{method}{path_without_query}"
        
        headers = {
            "Content-Type": "application/json",
        }
        
        if self._private_key and self.config.KALSHI_API_KEY:
            signature = self._sign_pss(msg_string)
            headers.update({
                "KALSHI-ACCESS-KEY": self.config.KALSHI_API_KEY,
                "KALSHI-ACCESS-SIGNATURE": signature,
                "KALSHI-ACCESS-TIMESTAMP": timestamp,
            })
        
        return headers

    async def get_markets(self, series_ticker: str) -> List[KalshiMarket]:
        """Fetch current markets for a crypto series ticker (e.g., KXBTCD for Bitcoin hourly)"""
        # First get events for this series to find currently active ones
        events_path = f"/events?series_ticker={series_ticker}&status=open"
        headers = self._get_auth_headers("GET", events_path)
        
        async with self._session.get(
            f"{self.config.KALSHI_API_BASE}{events_path}",
            headers=headers
        ) as resp:
            if resp.status != 200:
                self.logger.debug(f"Failed to get events: {await resp.text()}")
                # Fall back to direct market search
                return await self._get_markets_direct(series_ticker)
            
            events_data = await resp.json()
            events = events_data.get("events", [])
            
            if not events:
                # Fall back to direct market search
                return await self._get_markets_direct(series_ticker)
        
        # Get markets for the most relevant events (soonest expiring)
        all_markets = []
        for event in events[:3]:  # Check up to 3 events
            event_ticker = event.get("event_ticker")
            if not event_ticker:
                continue
                
            markets_path = f"/markets?event_ticker={event_ticker}&status=open"
            headers = self._get_auth_headers("GET", markets_path)
            
            async with self._session.get(
                f"{self.config.KALSHI_API_BASE}{markets_path}",
                headers=headers
            ) as resp:
                if resp.status != 200:
                    continue
                    
                data = await resp.json()
                
                for m in data.get("markets", []):
                    try:
                        market = self._parse_market(m)
                        if market:
                            all_markets.append(market)
                    except Exception as e:
                        self.logger.warning(f"Failed to parse market: {e}")
        
        return all_markets
    
    async def _get_markets_direct(self, ticker_prefix: str) -> List[KalshiMarket]:
        """Direct market search by ticker prefix"""
        path = f"/markets?ticker={ticker_prefix}&status=open&limit=100"
        headers = self._get_auth_headers("GET", path)

        try:
            async with self._session.get(
                f"{self.config.KALSHI_API_BASE}{path}",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                # Check for rate limiting (CloudFront 403)
                if resp.status == 403 or "text/html" in resp.content_type:
                    self.logger.warning(f"Rate limited by Kalshi/CloudFront (status {resp.status}) - waiting 60 seconds")
                    await asyncio.sleep(60)
                    return []
                if resp.status != 200:
                    self.logger.warning(f"Failed to get markets (status {resp.status})")
                    return []

                data = await resp.json()
                
                markets = []
                for m in data.get("markets", []):
                    try:
                        market = self._parse_market(m)
                        if market:
                            markets.append(market)
                    except Exception as e:
                        self.logger.warning(f"Failed to parse market: {e}")

                return markets
        except Exception as e:
            self.logger.error(f"Error fetching markets: {e}")
            return []
    
    def _parse_market(self, m: dict) -> Optional[KalshiMarket]:
        """Parse a market from API response"""
        # Parse strike price from subtitle (e.g., "$95,000 or above" or "$3,330 to 3,369.99")
        strike = None
        subtitle = m.get("subtitle", "")
        
        if "$" in subtitle:
            try:
                # Extract the first dollar amount
                price_str = subtitle.split("$")[1].replace(",", "").split()[0]
                # Remove trailing non-numeric characters
                price_str = ''.join(c for c in price_str if c.isdigit() or c == '.')
                if price_str:
                    strike = float(price_str)
            except (ValueError, IndexError):
                pass
        
        # Also try to extract from ticker (e.g., KXBTCD-26JAN1617-T95999.99)
        if strike is None:
            ticker = m.get("ticker", "")
            if "-T" in ticker or "-B" in ticker:
                try:
                    # Extract number after -T or -B
                    parts = ticker.split("-")
                    for part in parts:
                        if part.startswith("T") or part.startswith("B"):
                            num_str = part[1:]
                            strike = float(num_str)
                            break
                except (ValueError, IndexError):
                    pass
        
        # Get expiration time
        close_time = m.get("close_time") or m.get("expiration_time")
        if close_time:
            expiration = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
        else:
            expiration = datetime.now(timezone.utc) + timedelta(hours=1)

        return KalshiMarket(
            ticker=m["ticker"],
            event_ticker=m.get("event_ticker", ""),
            title=m.get("title", ""),
            subtitle=subtitle,
            yes_bid=(m.get("yes_bid") or 0) / 100,  # Convert from cents
            yes_ask=(m.get("yes_ask") or 0) / 100,
            no_bid=(m.get("no_bid") or 0) / 100,
            no_ask=(m.get("no_ask") or 0) / 100,
            volume=m.get("volume", 0),
            open_interest=m.get("open_interest", 0),
            strike_price=strike,
            expiration_time=expiration,
            last_updated=datetime.now(timezone.utc),
        )

    async def place_order(
        self,
        ticker: str,
        side: Side,
        quantity: int,
        price: float,
    ) -> TradeResult:
        """Place a limit order"""
        if not self._authenticated:
            return TradeResult(
                order_id="",
                ticker=ticker,
                side=side,
                quantity=quantity,
                price=price,
                timestamp=datetime.now(timezone.utc),
                success=False,
                error="Not authenticated",
            )

        path = "/portfolio/orders"
        headers = self._get_auth_headers("POST", path)

        # Build order data - Kalshi API requires exactly one price field
        order_data = {
            "ticker": ticker,
            "type": "limit",
            "action": "buy",
            "side": side.value.lower(),  # 'yes' or 'no'
            "count": quantity,
        }
        
        # Add the correct price field based on side
        price_cents = int(price * 100)
        if side == Side.YES:
            order_data["yes_price"] = price_cents
        else:
            order_data["no_price"] = price_cents

        async with self._session.post(
            f"{self.config.KALSHI_API_BASE}{path}",
            headers=headers,
            json=order_data,
        ) as resp:
            data = await resp.json()

            if resp.status in [200, 201]:  # 201 Created is success for orders!
                order_data = data.get("order", {})
                self.logger.info(f"ORDER PLACED: {order_data.get('order_id', 'unknown')} status={order_data.get('status', 'unknown')}")
                return TradeResult(
                    order_id=order_data.get("order_id", ""),
                    ticker=ticker,
                    side=side,
                    quantity=quantity,
                    price=price,
                    timestamp=datetime.now(timezone.utc),
                    success=True,
                )
            else:
                self.logger.warning(f"Order API error: status={resp.status} data={data}")
                return TradeResult(
                    order_id="",
                    ticker=ticker,
                    side=side,
                    quantity=quantity,
                    price=price,
                    timestamp=datetime.now(timezone.utc),
                    success=False,
                    error=data.get("error", {}).get("message", str(resp.status)),
                )

    async def sell_position(
        self,
        ticker: str,
        side: Side,
        quantity: int,
        price: float,
    ) -> TradeResult:
        """Sell/close a position"""
        if not self._authenticated:
            return TradeResult(
                order_id="",
                ticker=ticker,
                side=side,
                quantity=quantity,
                price=price,
                timestamp=datetime.now(timezone.utc),
                success=False,
                error="Not authenticated",
            )

        path = "/portfolio/orders"
        headers = self._get_auth_headers("POST", path)

        # Build SELL order data
        order_data = {
            "ticker": ticker,
            "type": "limit",
            "action": "sell",  # SELL instead of buy
            "side": side.value.lower(),
            "count": quantity,
        }
        
        price_cents = int(price * 100)
        if side == Side.YES:
            order_data["yes_price"] = price_cents
        else:
            order_data["no_price"] = price_cents

        self.logger.info(f"SELLING: {ticker} {side.value} x{quantity} @ ${price:.2f}")

        async with self._session.post(
            f"{self.config.KALSHI_API_BASE}{path}",
            headers=headers,
            json=order_data,
        ) as resp:
            data = await resp.json()

            if resp.status in [200, 201]:
                order_data = data.get("order", {})
                self.logger.info(f"SELL ORDER PLACED: {order_data.get('order_id', 'unknown')}")
                return TradeResult(
                    order_id=order_data.get("order_id", ""),
                    ticker=ticker,
                    side=side,
                    quantity=quantity,
                    price=price,
                    timestamp=datetime.now(timezone.utc),
                    success=True,
                )
            else:
                self.logger.warning(f"Sell failed: {data}")
                return TradeResult(
                    order_id="",
                    ticker=ticker,
                    side=side,
                    quantity=quantity,
                    price=price,
                    timestamp=datetime.now(timezone.utc),
                    success=False,
                    error=data.get("error", {}).get("message", str(resp.status)),
                )

    async def get_market_orderbook(self, ticker: str) -> dict:
        """Get current orderbook/prices for a market"""
        path = f"/markets/{ticker}"
        headers = self._get_auth_headers("GET", path)

        async with self._session.get(
            f"{self.config.KALSHI_API_BASE}{path}",
            headers=headers,
        ) as resp:
            if resp.status == 200:
                return await resp.json()
            return {}

    async def get_positions(self) -> List[Position]:
        """Get current positions"""
        if not self._authenticated:
            return []

        path = "/portfolio/positions"
        headers = self._get_auth_headers("GET", path)

        async with self._session.get(
            f"{self.config.KALSHI_API_BASE}{path}",
            headers=headers,
        ) as resp:
            if resp.status != 200:
                return []

            data = await resp.json()
            positions = []

            for p in data.get("market_positions", []):
                pos = Position(
                    ticker=p["ticker"],
                    side=Side.YES if p.get("position", 0) > 0 else Side.NO,
                    quantity=abs(p.get("position", 0)),
                    entry_price=p.get("total_cost", 0) / max(abs(p.get("position", 1)), 1) / 100,
                    entry_time=datetime.fromisoformat(
                        p.get("created_time", datetime.now(timezone.utc).isoformat())
                        .replace("Z", "+00:00")
                    ),
                )
                positions.append(pos)

        return positions

    async def get_balance(self) -> float:
        """Get account balance"""
        if not self._private_key:
            return 0.0

        path = "/portfolio/balance"
        headers = self._get_auth_headers("GET", path)

        async with self._session.get(
            f"{self.config.KALSHI_API_BASE}{path}",
            headers=headers,
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("balance", 0) / 100  # Convert from cents
        return 0.0

# =============================================================================
# PROBABILITY CALCULATOR
# =============================================================================

class ProbabilityEngine:
    """
    Calculates fair value probabilities for crypto prediction markets.
    Uses real-time price data, volatility estimates, AND momentum detection.
    
    CRITICAL FIX: Added price trend/momentum analysis to avoid betting against
    clear directional moves. Pure random-walk models fail in trending markets.
    """

    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger

        # Rolling price history (timestamp_ms, price)
        self.price_history: Dict[str, deque] = {
            "BTC": deque(maxlen=300),  # ~5 min of data at 1/sec
            "ETH": deque(maxlen=300),
            "SOL": deque(maxlen=300),
            "XRP": deque(maxlen=300),
        }

        # Base annualized volatility estimates
        self.base_volatility = {
            "BTC": 0.60,   # 60% annualized - most stable
            "ETH": 0.75,   # 75% annualized
            "SOL": 0.95,   # 95% annualized - higher volatility
            "XRP": 0.85,   # 85% annualized
        }

    def update_price(self, symbol: str, price: float, timestamp_ms: int):
        """Update price history for volatility and momentum calculation"""
        self.price_history[symbol].append((timestamp_ms, price))

    def _calculate_momentum(self, symbol: str) -> Tuple[float, float]:
        """
        Calculate price momentum over multiple timeframes.
        Returns (short_term_change_pct, medium_term_change_pct)
        
        Positive = price going UP
        Negative = price going DOWN
        """
        history = list(self.price_history.get(symbol, []))
        if len(history) < 30:
            return (0.0, 0.0)
        
        current_price = history[-1][1]
        
        # Short-term: last 30 seconds
        short_idx = max(0, len(history) - 30)
        short_price = history[short_idx][1]
        short_change = (current_price - short_price) / short_price if short_price > 0 else 0
        
        # Medium-term: last 2 minutes (120 samples)
        med_idx = max(0, len(history) - 120)
        med_price = history[med_idx][1]
        med_change = (current_price - med_price) / med_price if med_price > 0 else 0
        
        return (short_change, med_change)

    def _estimate_realized_volatility(self, symbol: str) -> float:
        """Estimate short-term realized volatility from recent prices"""
        history = list(self.price_history.get(symbol, []))
        if len(history) < 10:
            return self.base_volatility.get(symbol, 0.65)

        # Calculate 1-minute log returns
        prices = [p[1] for p in history]
        returns = [np.log(prices[i] / prices[i-1]) for i in range(1, len(prices))]

        if not returns:
            return self.base_volatility.get(symbol, 0.65)

        # Annualize (assuming ~1 sample per second, 525,600 minutes per year)
        std_dev = np.std(returns)
        annualized = std_dev * np.sqrt(525600)

        # Blend with base estimate
        base = self.base_volatility.get(symbol, 0.65)
        return 0.7 * annualized + 0.3 * base if annualized > 0 else base

    def calculate_fair_probability(
        self,
        current_price: float,
        strike_price: float,
        time_to_expiry_seconds: float,
        symbol: str = "BTC",
    ) -> Tuple[float, float, str]:
        """
        Calculate fair probability of price being above strike at expiration.
        
        Returns: (probability, confidence, trend_direction)
        - probability: 0-1 fair value
        - confidence: 0-1 how confident we are (low if conflicting signals)
        - trend_direction: 'UP', 'DOWN', or 'NEUTRAL'

        Uses:
        - Black-Scholes base probability
        - Momentum adjustment (trending prices continue short-term)
        - Reduced confidence when model and market disagree significantly
        """
        if time_to_expiry_seconds <= 0:
            return (1.0 if current_price >= strike_price else 0.0, 1.0, 'NEUTRAL')

        # Convert to years
        T = time_to_expiry_seconds / (365.25 * 24 * 3600)

        # Get volatility estimate
        sigma = self._estimate_realized_volatility(symbol)

        # Log moneyness
        if current_price <= 0 or strike_price <= 0:
            return (0.5, 0.0, 'NEUTRAL')
        log_moneyness = np.log(current_price / strike_price)

        # Get momentum
        short_momentum, med_momentum = self._calculate_momentum(symbol)
        
        # Determine trend direction
        if short_momentum > 0.001 and med_momentum > 0.001:
            trend = 'UP'
            # If trending up, add positive drift
            drift_adjustment = min(short_momentum * 50, 0.05)  # Cap at 5% drift
        elif short_momentum < -0.001 and med_momentum < -0.001:
            trend = 'DOWN'
            # If trending down, add negative drift
            drift_adjustment = max(short_momentum * 50, -0.05)  # Cap at -5% drift
        else:
            trend = 'NEUTRAL'
            drift_adjustment = 0.0

        # Base drift (near zero for short-term)
        drift = drift_adjustment

        # d2 from Black-Scholes (probability under risk-neutral measure)
        vol_sqrt_t = sigma * np.sqrt(T)
        if vol_sqrt_t < 0.0001:
            return (1.0 if current_price >= strike_price else 0.0, 1.0, trend)

        d2 = (log_moneyness + (drift - 0.5 * sigma**2) * T) / vol_sqrt_t

        # N(d2) = probability of finishing above strike
        prob = norm.cdf(d2)

        # Apply conservative adjustment - reduce extreme probabilities
        # This prevents overconfidence when price is near strike
        if T < 1/365:  # Less than 1 day
            # Stronger mean-reversion for uncertain markets
            mean_reversion_factor = 0.70  # MORE conservative than before
            prob = 0.5 + (prob - 0.5) * mean_reversion_factor

        # Calculate confidence based on:
        # 1. Distance from strike (very close = uncertain)
        # 2. Agreement of momentum signals
        # 3. Number of price samples
        
        distance_ratio = abs(current_price - strike_price) / strike_price
        distance_confidence = min(distance_ratio * 20, 1.0)  # Max confidence at 5% away
        
        # Momentum agreement
        if (short_momentum > 0 and med_momentum > 0) or (short_momentum < 0 and med_momentum < 0):
            momentum_confidence = 0.8
        else:
            momentum_confidence = 0.4  # Conflicting signals = low confidence
        
        confidence = distance_confidence * momentum_confidence

        return (np.clip(prob, 0.001, 0.999), confidence, trend)

    def calculate_edge(
        self,
        fair_prob: float,
        market_price: float,
        side: Side,
    ) -> float:
        """Calculate edge for a potential trade"""
        if side == Side.YES:
            # Buying YES: we profit if YES wins
            # Fair value of YES = fair_prob
            # Edge = fair value - market price
            return fair_prob - market_price
        else:
            # Buying NO: we profit if NO wins
            # Fair value of NO = 1 - fair_prob
            return (1 - fair_prob) - market_price

# =============================================================================
# SIGNAL GENERATOR
# =============================================================================

class SignalGenerator:
    """
    Generates trading signals by comparing real-time prices to Kalshi markets.
    """

    def __init__(
        self,
        config: Config,
        logger: logging.Logger,
        price_feed: PriceFeedManager,
        prob_engine: ProbabilityEngine,
    ):
        self.config = config
        self.logger = logger
        self.price_feed = price_feed
        self.prob_engine = prob_engine

    def generate_signals(
        self,
        markets: List[KalshiMarket],
    ) -> List[TradeSignal]:
        """Generate signals for all available markets"""
        signals = []

        for market in markets:
            signal = self._evaluate_market(market)
            if signal:
                signals.append(signal)

        # Sort by EXPECTED VALUE (edge * fair_value * confidence)
        # This prioritizes trades that are:
        # 1. High probability of winning (fair_value close to 1)
        # 2. Good edge (mispricing)
        # 3. High confidence (trend alignment, multiple sources)
        def expected_value(s: TradeSignal) -> float:
            # EV = probability of winning * potential profit - probability of losing * cost
            # Simplified: edge * confidence * (1 if high prob else discount)
            prob_bonus = 1.0 + (s.fair_value - 0.5) * 0.5  # Bonus for high probability trades
            return abs(s.edge) * s.confidence * prob_bonus
        
        signals.sort(key=expected_value, reverse=True)
        return signals

    def _evaluate_market(self, market: KalshiMarket) -> Optional[TradeSignal]:
        """Evaluate a single market for trading opportunity"""

        # Determine which crypto this market is for based on ticker
        ticker_upper = market.ticker.upper()
        if "BTC" in ticker_upper:
            symbol = "BTC"
        elif "ETH" in ticker_upper:
            symbol = "ETH"
        elif "SOL" in ticker_upper:
            symbol = "SOL"
        elif "XRP" in ticker_upper:
            symbol = "XRP"
        else:
            self.logger.debug(f"Unknown crypto in ticker: {market.ticker}")
            return None

        # Get current aggregated price
        price_data = self.price_feed.get_aggregated_price(symbol)
        if not price_data:
            return None
        crypto_price, num_sources = price_data

        # Need strike price to calculate probability
        if not market.strike_price:
            return None

        # Focus on final minutes where latency edge is highest
        time_to_expiry = market.time_to_expiry_seconds
        if time_to_expiry <= 0:
            return None

        # Calculate fair probability with momentum analysis
        fair_prob, model_confidence, trend = self.prob_engine.calculate_fair_probability(
            current_price=crypto_price,
            strike_price=market.strike_price,
            time_to_expiry_seconds=time_to_expiry,
            symbol=symbol,
        )

        # Check both YES and NO sides - but only if prices are valid (not 0 or None)
        yes_price = market.yes_ask or 0
        no_price = market.no_ask or 0
        
        # Skip markets with no liquidity (price is 0 or very close to extremes)
        if yes_price <= 0.01 and no_price <= 0.01:
            return None
        
        yes_edge = self.prob_engine.calculate_edge(fair_prob, yes_price, Side.YES) if yes_price > 0.01 else -1
        no_edge = self.prob_engine.calculate_edge(fair_prob, no_price, Side.NO) if no_price > 0.01 else -1

        # ================================================================
        # CRITICAL TREND CHECK: Don't bet against clear price trends!
        # If price is trending DOWN, don't bet YES (above strike)
        # If price is trending UP, don't bet NO (below strike)
        # ================================================================
        if trend == 'DOWN' and yes_edge > no_edge:
            # Price trending down but model says buy YES? Skip or reduce confidence
            self.logger.debug(f"Trend mismatch {market.ticker}: DOWN trend but YES signal - skipping")
            yes_edge = -1  # Disqualify YES
        elif trend == 'UP' and no_edge > yes_edge:
            # Price trending up but model says buy NO? Skip or reduce confidence
            self.logger.debug(f"Trend mismatch {market.ticker}: UP trend but NO signal - skipping")
            no_edge = -1  # Disqualify NO

        # Choose better side - only consider sides with valid prices
        if yes_edge > no_edge and yes_edge > self.config.MIN_EDGE_THRESHOLD and yes_price > 0.01:
            side = Side.YES
            edge = yes_edge
            market_price = yes_price
        elif no_edge > self.config.MIN_EDGE_THRESHOLD and no_price > 0.01:
            side = Side.NO
            edge = no_edge
            market_price = no_price
        else:
            return None
        
        # Skip if edge is unrealistically high (likely illiquid market)
        if edge > 0.40:  # Reduced from 50% - 40% edge is suspicious
            self.logger.debug(f"Skipping {market.ticker}: edge too high ({edge:.1%}) - likely illiquid")
            return None

        # Check spread isn't too wide
        if market.spread > self.config.MAX_SPREAD_COST:
            self.logger.debug(f"Skipping {market.ticker}: spread too wide ({market.spread:.2%})")
            return None
        
        # ================================================================
        # PREFER HIGHER PROBABILITY TRADES
        # Skip low-probability gambles (fair_value < 0.35 or > 0.95)
        # These are either unlikely to win or have minimal upside
        # ================================================================
        fair_value_for_side = fair_prob if side == Side.YES else (1 - fair_prob)
        if fair_value_for_side < 0.35:
            self.logger.debug(f"Skipping {market.ticker}: low probability ({fair_value_for_side:.1%})")
            return None
        if fair_value_for_side > 0.95:
            self.logger.debug(f"Skipping {market.ticker}: minimal upside ({fair_value_for_side:.1%})")
            return None

        # Calculate confidence based on:
        # 1. Number of price sources
        # 2. Time to expiry (more confident closer to expiry)
        # 3. Edge magnitude
        # 4. Model confidence (from momentum agreement)
        # 5. Trend alignment
        source_confidence = min(num_sources / 3, 1.0)
        time_confidence = 1.0 if time_to_expiry < self.config.LATENCY_WINDOW_SECONDS else 0.7
        edge_confidence = min(abs(edge) / 0.10, 1.0)  # Max at 10% edge
        
        # Bonus confidence if trend aligns with our bet
        trend_bonus = 1.0
        if (trend == 'UP' and side == Side.YES) or (trend == 'DOWN' and side == Side.NO):
            trend_bonus = 1.2  # 20% confidence boost for trend alignment
        
        confidence = source_confidence * time_confidence * edge_confidence * model_confidence * trend_bonus
        confidence = min(confidence, 1.0)  # Cap at 100%

        # Calculate position size using fractional Kelly with confidence scaling
        kelly_fraction = self._kelly_criterion(edge, market_price, fair_prob)
        
        # CRITICAL: Scale position size by confidence AND fair value
        # Higher confidence + higher probability = MORE contracts
        # This ensures we "bet big when we're confident and likely to win"
        confidence_multiplier = confidence  # 0 to 1
        prob_multiplier = 0.5 + fair_prob * 0.5  # 0.5 to 1.0 (favor high prob trades)
        
        base_size = kelly_fraction * self.config.KELLY_FRACTION * self.config.MAX_POSITION_SIZE
        recommended_size = int(base_size * confidence_multiplier * prob_multiplier)
        recommended_size = max(1, min(recommended_size, self.config.MAX_POSITION_SIZE))

        return TradeSignal(
            market=market,
            side=side,
            edge=edge,
            confidence=confidence,
            fair_value=fair_prob if side == Side.YES else (1 - fair_prob),
            market_price=market_price,
            crypto_price=crypto_price,
            recommended_size=recommended_size,
        )

    def _kelly_criterion(
        self,
        edge: float,
        market_price: float,
        fair_prob: float,
    ) -> float:
        """
        Calculate Kelly criterion fraction.
        Kelly = (bp - q) / b where:
        - b = odds offered (payout ratio)
        - p = probability of winning
        - q = 1 - p
        """
        if market_price >= 1 or market_price <= 0:
            return 0

        # Payout ratio (what we win relative to what we risk)
        b = (1 - market_price) / market_price

        p = fair_prob
        q = 1 - p

        kelly = (b * p - q) / b if b > 0 else 0
        return max(0, kelly)

# =============================================================================
# RISK MANAGER
# =============================================================================

class RiskManager:
    """
    Manages position risk, P&L tracking, and trade limits.
    """

    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger

        self.daily_pnl = 0.0
        self.positions: Dict[str, Position] = {}
        self.trade_count = 0
        self.last_reset = datetime.now(timezone.utc).date()

    def _check_daily_reset(self):
        """Reset daily counters if new day"""
        today = datetime.now(timezone.utc).date()
        if today > self.last_reset:
            self.logger.info(f"Daily reset: PnL was {self.daily_pnl:.2f}")
            self.daily_pnl = 0.0
            self.trade_count = 0
            self.last_reset = today

    def can_trade(self, signal: TradeSignal) -> Tuple[bool, str]:
        """Check if a trade is allowed under risk limits"""
        self._check_daily_reset()

        # Check daily loss limit
        if self.daily_pnl <= -self.config.MAX_DAILY_LOSS:
            return False, f"Daily loss limit reached: {self.daily_pnl:.2f}"

        # Check concurrent positions
        if len(self.positions) >= self.config.MAX_CONCURRENT_POSITIONS:
            return False, f"Max positions reached: {len(self.positions)}"

        # Check if already have position in this market
        if signal.market.ticker in self.positions:
            return False, f"Already have position in {signal.market.ticker}"

        # Check single trade risk
        trade_risk = signal.recommended_size * signal.market_price
        if trade_risk > self.config.MAX_SINGLE_TRADE_RISK:
            return False, f"Trade risk too high: ${trade_risk:.2f}"

        # Check minimum confidence (lowered to 0.05 = 5% since we have trend protection)
        if signal.confidence < 0.05:
            return False, f"Confidence too low: {signal.confidence:.2%}"

        return True, "OK"

    def record_trade(self, result: TradeResult, signal: TradeSignal):
        """Record executed trade"""
        if result.success:
            self.positions[result.ticker] = Position(
                ticker=result.ticker,
                side=result.side,
                quantity=result.quantity,
                entry_price=result.price,
                entry_time=result.timestamp,
            )
            self.trade_count += 1
            self.logger.info(
                f"Trade recorded: {result.ticker} {result.side.value} "
                f"x{result.quantity} @ {result.price:.3f}"
            )

    def update_pnl(self, ticker: str, settlement_price: float):
        """Update P&L when market settles"""
        if ticker not in self.positions:
            return

        pos = self.positions[ticker]

        # Binary settlement: 1.0 if YES wins, 0.0 if NO wins
        if pos.side == Side.YES:
            pnl = pos.quantity * (settlement_price - pos.entry_price)
        else:
            pnl = pos.quantity * ((1 - settlement_price) - pos.entry_price)

        self.daily_pnl += pnl
        self.logger.info(
            f"Position settled: {ticker} PnL: ${pnl:.2f} | Daily: ${self.daily_pnl:.2f}"
        )
        del self.positions[ticker]

# =============================================================================
# EXECUTION ENGINE
# =============================================================================

class ExecutionEngine:
    """
    Handles order execution with smart order routing and latency optimization.
    """

    def __init__(
        self,
        config: Config,
        logger: logging.Logger,
        kalshi_client: KalshiClient,
        risk_manager: RiskManager,
    ):
        self.config = config
        self.logger = logger
        self.kalshi = kalshi_client
        self.risk = risk_manager

        self.pending_orders: Dict[str, TradeSignal] = {}

    async def execute_signal(self, signal: TradeSignal) -> Optional[TradeResult]:
        """Execute a trading signal"""

        # Risk check
        can_trade, reason = self.risk.can_trade(signal)
        if not can_trade:
            self.logger.warning(f"Trade BLOCKED: {reason}")
            return None
        
        self.logger.info(f"Risk check PASSED for {signal.market.ticker}")

        # Determine execution price
        # For latency arb, we want to be aggressive - use the ask price
        if signal.side == Side.YES:
            exec_price = signal.market.yes_ask
        else:
            exec_price = signal.market.no_ask
        
        # Skip if no valid price (market has no liquidity)
        if exec_price is None or exec_price <= 0.01:
            self.logger.info(f"Trade SKIP: no valid price (${exec_price}) for {signal.market.ticker}")
            return None
        
        # Skip if price is too high (would risk too much)
        if exec_price > 0.95:
            self.logger.info(f"Trade SKIP: price too high (${exec_price}) for {signal.market.ticker}")
            return None

        self.logger.info(f"EXECUTING TRADE: {signal.market.ticker} {signal.side.value} @ ${exec_price:.2f}")

        # ================================================================
        # SMART POSITION SIZING: More capital on higher confidence trades
        # ================================================================
        # Base risk scales with confidence:
        # - Low confidence (0.3): $3 max risk
        # - Medium confidence (0.5): $5 max risk  
        # - High confidence (0.7+): $7-10 max risk
        # 
        # With $20 balance, max single trade = 50% = $10
        base_max_risk = 10.0  # Absolute max per trade
        confidence_scaled_risk = base_max_risk * signal.confidence
        max_risk_per_trade = max(2.0, min(confidence_scaled_risk, base_max_risk))
        
        # Additional bonus for high probability trades (fair_value > 0.7)
        # These are "likely to win" so we can size up slightly
        if signal.fair_value > 0.75:
            max_risk_per_trade = min(max_risk_per_trade * 1.25, base_max_risk)
        
        max_contracts = int(max_risk_per_trade / exec_price) if exec_price > 0 else 0
        size = min(signal.recommended_size, max_contracts, 25)  # Cap at 25 contracts
        
        if size < 1:
            self.logger.debug(f"Skipping: calculated size too small")
            return None
        
        # Log the sizing decision
        self.logger.debug(f"Sizing: conf={signal.confidence:.2f} fair={signal.fair_value:.2f} risk=${max_risk_per_trade:.2f} size={size}")

        # Place order
        result = await self.kalshi.place_order(
            ticker=signal.market.ticker,
            side=signal.side,
            quantity=size,
            price=exec_price,
        )

        if result.success:
            self.risk.record_trade(result, signal)
            self.logger.info(f"Order filled: {result.order_id}")
        else:
            self.logger.warning(f"Order failed: {result.error}")

        return result

# =============================================================================
# POSITION GUARDIAN - Auto-Exit Protection
# =============================================================================

@dataclass
class GuardedPosition:
    """A position being monitored for auto-exit"""
    ticker: str
    side: Side
    qty: int
    strike: float
    cost_basis: float
    asset: str  # BTC or ETH
    exit_trigger: float


class PositionGuardian:
    """
    Monitors positions and auto-sells when price approaches strike.
    Protects winning positions from turning into losses.
    """
    
    # How close price can get to strike before auto-selling (as % of strike)
    EXIT_BUFFER_PERCENT = 0.005  # 0.5% buffer
    
    def __init__(
        self,
        config: Config,
        logger: logging.Logger,
        kalshi_client: KalshiClient,
        price_feed: PriceFeedManager,
    ):
        self.config = config
        self.logger = logger
        self.kalshi = kalshi_client
        self.price_feed = price_feed
        self.guarded_positions: Dict[str, GuardedPosition] = {}
        self.sold_tickers: set = set()
    
    def parse_ticker(self, ticker: str) -> tuple:
        """Parse ticker to get asset, strike"""
        # Format: KXBTCD-26JAN1617-T97499.99
        parts = ticker.split("-")
        if len(parts) < 3:
            return None, None
        
        asset_code = parts[0]
        strike_str = parts[2]
        
        if "BTC" in asset_code:
            asset = "BTC"
        elif "ETH" in asset_code:
            asset = "ETH"
        else:
            return None, None
        
        if strike_str.startswith("T") or strike_str.startswith("B"):
            try:
                strike = float(strike_str[1:])
            except:
                return None, None
        else:
            return None, None
        
        return asset, strike
    
    async def load_positions(self):
        """Load current positions from Kalshi"""
        try:
            positions = await self.kalshi.get_positions()
        except Exception as e:
            self.logger.error(f"Error loading positions for guardian: {e}")
            return
        
        self.guarded_positions = {}
        
        for pos in positions:
            if pos.quantity == 0:
                continue
            if pos.ticker in self.sold_tickers:
                continue
            
            asset, strike = self.parse_ticker(pos.ticker)
            if not asset or not strike:
                continue
            
            # Calculate exit trigger
            buffer = strike * self.EXIT_BUFFER_PERCENT
            
            if pos.side == Side.NO:
                # Betting price stays BELOW strike - exit if price rises toward strike
                exit_trigger = strike - buffer
            else:
                # Betting price stays ABOVE strike - exit if price falls toward strike
                exit_trigger = strike + buffer
            
            guarded = GuardedPosition(
                ticker=pos.ticker,
                side=pos.side,
                qty=pos.quantity,
                strike=strike,
                cost_basis=pos.entry_price,
                asset=asset,
                exit_trigger=exit_trigger,
            )
            
            self.guarded_positions[pos.ticker] = guarded
            self.logger.info(
                f"GUARDIAN: Monitoring {pos.ticker} | {pos.quantity} {pos.side.value.upper()} @ ${strike:,.0f} | "
                f"Exit if {asset} {'rises above' if pos.side == Side.NO else 'falls below'} ${exit_trigger:,.0f}"
            )
        
        self.logger.info(f"GUARDIAN: Monitoring {len(self.guarded_positions)} positions")
    
    async def check_and_protect(self) -> List[str]:
        """Check prices and sell if needed - returns list of actions taken"""
        actions = []
        
        for ticker, pos in list(self.guarded_positions.items()):
            # Get current price from our price feed
            price_data = self.price_feed.get_aggregated_price(pos.asset)
            if not price_data:
                continue
            
            current_price, _ = price_data
            
            should_exit = False
            
            if pos.side == Side.NO:
                # Betting price stays BELOW strike - exit if price rises above trigger
                if current_price >= pos.exit_trigger:
                    should_exit = True
            else:
                # Betting price stays ABOVE strike - exit if price falls below trigger
                if current_price <= pos.exit_trigger:
                    should_exit = True
            
            if should_exit:
                self.logger.warning(f"{'!'*60}")
                self.logger.warning(f"GUARDIAN AUTO-EXIT TRIGGERED!")
                self.logger.warning(f"Position: {ticker}")
                self.logger.warning(f"{pos.asset}: ${current_price:,.2f} | Strike: ${pos.strike:,.2f} | Trigger: ${pos.exit_trigger:,.2f}")
                
                # Get current bid price
                try:
                    market_data = await self.kalshi.get_market_orderbook(ticker)
                    market = market_data.get("market", {})
                    
                    if pos.side == Side.YES:
                        sell_price = market.get("yes_bid", 0) / 100
                    else:
                        sell_price = market.get("no_bid", 0) / 100
                    
                    if sell_price > 0.01:
                        self.logger.warning(f"Selling {pos.qty} {pos.side.value.upper()} @ ${sell_price:.2f}")
                        
                        result = await self.kalshi.sell_position(
                            ticker, pos.side, pos.qty, sell_price
                        )
                        
                        if result.success:
                            self.logger.warning(f"GUARDIAN SOLD! Order: {result.order_id}")
                            self.sold_tickers.add(ticker)
                            del self.guarded_positions[ticker]
                            actions.append(f"SOLD {ticker} @ ${sell_price:.2f}")
                        else:
                            self.logger.error(f"GUARDIAN SELL FAILED: {result.error}")
                            actions.append(f"SELL FAILED {ticker}: {result.error}")
                    else:
                        self.logger.warning(f"No bid available to sell {ticker}")
                        
                except Exception as e:
                    self.logger.error(f"Error selling {ticker}: {e}")
                    actions.append(f"ERROR {ticker}: {e}")
        
        return actions


# =============================================================================
# MAIN BOT ORCHESTRATOR
# =============================================================================

class KalshiLatencyBot:
    """
    Main orchestrator that coordinates all components.
    """

    def __init__(self, config: Optional[Config] = None, dry_run: bool = False):
        self.config = config or Config()
        self.dry_run = dry_run
        self.logger = setup_logging(self.config)

        # Initialize components
        self.price_feed = PriceFeedManager(self.config, self.logger)
        self.prob_engine = ProbabilityEngine(self.config, self.logger)
        self.kalshi = KalshiClient(self.config, self.logger)
        self.risk_manager = RiskManager(self.config, self.logger)
        self.execution = ExecutionEngine(
            self.config, self.logger, self.kalshi, self.risk_manager
        )
        self.signal_gen = SignalGenerator(
            self.config, self.logger, self.price_feed, self.prob_engine
        )
        
        # Position guardian for auto-exit protection
        self.guardian = PositionGuardian(
            self.config, self.logger, self.kalshi, self.price_feed
        )

        # Register price callback for volatility updates
        self.price_feed.register_callback(self._on_price_update)

        self._running = False
        self._guardian_check_counter = 0
        self._insufficient_balance_count = 0  # Track consecutive balance failures
        self._last_trade_error = None

    def _on_price_update(self, update: PriceUpdate):
        """Handle incoming price updates"""
        self.prob_engine.update_price(
            update.symbol, update.price, update.timestamp_ms
        )

    async def start(self):
        """Start the trading bot"""
        self.logger.info("=" * 60)
        self.logger.info("KALSHI LATENCY ARBITRAGE BOT")
        self.logger.info("=" * 60)

        self._running = True

        # Initialize components
        await self.kalshi.initialize()
        await self.price_feed.start()

        # Wait for price feeds to populate
        self.logger.info("Waiting for price feeds...")
        await asyncio.sleep(3)
        
        # Load positions for guardian auto-exit protection
        self.logger.info("Loading positions for guardian...")
        await self.guardian.load_positions()

        # Main trading loop
        try:
            await self._trading_loop()
        except asyncio.CancelledError:
            self.logger.info("Bot cancelled")
        except Exception as e:
            self.logger.error(f"Bot error: {e}", exc_info=True)
        finally:
            await self.stop()

    async def stop(self):
        """Stop the trading bot"""
        self._running = False
        await self.price_feed.stop()
        await self.kalshi.close()
        self.logger.info("Bot stopped")

    async def _trading_loop(self):
        """Main trading loop"""
        self.logger.info("Starting trading loop")

        while self._running:
            try:
                # Fetch current markets
                all_markets = []
                for ticker in self.config.CRYPTO_TICKERS:
                    markets = await self.kalshi.get_markets(ticker)
                    all_markets.extend(markets)

                if not all_markets:
                    self.logger.debug("No markets available")
                    await asyncio.sleep(1)
                    continue

                # Generate signals
                signals = self.signal_gen.generate_signals(all_markets)

                if signals:
                    self.logger.info(f"Generated {len(signals)} signals")
                    
                    # Show the best signal details periodically
                    best_signal = signals[0]
                    import random
                    if random.random() < 0.20:  # ~20% of cycles, show details
                        self.logger.info(
                            f"BEST: {best_signal.market.ticker} {best_signal.side.value.upper()} | "
                            f"Edge: {best_signal.edge:.1%} | Conf: {best_signal.confidence:.1%} | "
                            f"Fair: {best_signal.fair_value:.1%} vs Mkt: ${best_signal.market_price:.2f} | "
                            f"Size: {best_signal.recommended_size}"
                        )

                    # Execute best signal (unless in dry-run mode or no balance)
                    if best_signal.edge >= self.config.MIN_EDGE_THRESHOLD:
                        # Skip if we've had too many balance failures (likely no cash)
                        if self._insufficient_balance_count >= 3:
                            if self._guardian_check_counter == 0:  # Log occasionally
                                self.logger.info(f"Skipping trade - insufficient balance (protecting positions)")
                        elif self.dry_run:
                            self.logger.info(f"[DRY RUN] Would execute: {best_signal}")
                        else:
                            self.logger.info(f"TRADE TRIGGER: Edge {best_signal.edge:.1%} >= threshold {self.config.MIN_EDGE_THRESHOLD:.1%}")
                            result = await self.execution.execute_signal(best_signal)
                            if result:
                                self.logger.info(f"EXECUTION RESULT: {result}")
                                # Track balance failures
                                if not result.success and "insufficient_balance" in str(result.error):
                                    self._insufficient_balance_count += 1
                                else:
                                    self._insufficient_balance_count = 0

                # GUARDIAN: Check for auto-exit triggers every 4 loops (~4 seconds)
                self._guardian_check_counter += 1
                if self._guardian_check_counter >= 4:
                    self._guardian_check_counter = 0
                    actions = await self.guardian.check_and_protect()
                    # Reload positions periodically (every ~60 seconds)
                    if len(self.guardian.guarded_positions) == 0:
                        await self.guardian.load_positions()

                # Rate limit: check every 2 seconds to avoid API rate limits
                await asyncio.sleep(2.0)

            except Exception as e:
                self.logger.error(f"Loop error: {e}")
                # Check if it's a rate limit error (403)
                if "403" in str(e) or "blocked" in str(e).lower():
                    self.logger.warning("Rate limit detected - backing off for 60 seconds")
                    await asyncio.sleep(60)
                else:
                    await asyncio.sleep(10)  # Longer backoff on errors

    def run(self):
        """Synchronous entry point"""
        try:
            asyncio.run(self.start())
        except KeyboardInterrupt:
            self.logger.info("Interrupted by user")

# =============================================================================
# CLI INTERFACE
# =============================================================================

def main():
    """CLI entry point"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Kalshi 15-Minute Crypto Latency Arbitrage Bot"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without executing trades",
    )
    parser.add_argument(
        "--min-edge",
        type=float,
        default=0.03,
        help="Minimum edge threshold (default: 0.03)",
    )
    parser.add_argument(
        "--max-position",
        type=int,
        default=100,
        help="Maximum position size (default: 100)",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level",
    )

    args = parser.parse_args()

    # Build config
    config = Config()
    config.MIN_EDGE_THRESHOLD = args.min_edge
    config.MAX_POSITION_SIZE = args.max_position
    config.LOG_LEVEL = args.log_level

    if args.dry_run:
        print("Running in DRY RUN mode - signals will be generated but no trades executed")

    # Run bot
    bot = KalshiLatencyBot(config, dry_run=args.dry_run)
    bot.run()

if __name__ == "__main__":
    main()
