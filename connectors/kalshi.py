"""
Kalshi API Connector with Series-Based Allowlist
Only trades 15-minute crypto up/down and hourly price markets
"""
from __future__ import annotations
import asyncio
import base64
import hashlib
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Set
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from aiohttp_socks import ProxyConnector
import aiohttp

from config import config
from core.models import NormalizedMarket, MarketCategory, Venue, OrderRequest, OrderResponse, OrderStatus

logger = logging.getLogger(__name__)

# === SERIES ALLOWLIST - Only these markets will be traded ===
ALLOWED_SERIES = [
    "KXBTC15M",    # Bitcoin 15-min up/down
    "KXETH15M",    # ETH 15-min up/down  
    "KXSOL15M",    # Solana 15-min up/down
    "KXBTC",       # Bitcoin hourly price ranges
    "KXETH",       # ETH hourly price ranges
    "KXSOL",       # Solana hourly price ranges
    "KXDOGE",      # Dogecoin price ranges
    "INXI",        # S&P500 hourly (bonus)
    "NASDAQ100I",  # Nasdaq hourly (bonus)
]

class KalshiAuthError(Exception):
    pass

class KalshiAPIError(Exception):
    def __init__(self, message: str, status_code: int = None):
        super().__init__(message)
        self.status_code = status_code

class KalshiClient:
    """Async Kalshi API client with Tor support and series-based allowlist"""
    
    BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
    WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"
    TOR_PROXY = "socks5://127.0.0.1:9050"
    
    def __init__(self, use_tor: bool = True):
        self.use_tor = use_tor
        self._session: Optional[aiohttp.ClientSession] = None
        self._private_key = None
        self._api_key = config.kalshi.api_key
        
        # Allowlist state
        self._allowed_series: Set[str] = set(ALLOWED_SERIES)
        self._allowed_market_tickers: Set[str] = set()
        self._allowlist_refreshed_at: Optional[datetime] = None
        
    async def connect(self) -> None:
        """Initialize connection and load credentials"""
        connector = None
        if self.use_tor:
            connector = ProxyConnector.from_url(self.TOR_PROXY)
            logger.info("Kalshi client using Tor proxy")
        
        self._session = aiohttp.ClientSession(connector=connector)
        self._load_private_key()
        
        # Refresh allowlist on connect
        await self._refresh_allowlist()
        
    async def close(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None
            
    def _load_private_key(self) -> None:
        try:
            key_path = config.kalshi.private_key_path
            with open(key_path, 'rb') as f:
                self._private_key = serialization.load_pem_private_key(f.read(), password=None)
            logger.info("Loaded Kalshi private key")
        except Exception as e:
            logger.warning(f"Failed to load private key: {e}")
            
    def _sign(self, timestamp_ms: int, method: str, path: str) -> str:
        if not self._private_key:
            raise KalshiAuthError("No private key loaded")
        message = f"{timestamp_ms}{method}{path}".encode()
        signature = self._private_key.sign(
            message,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode()
        
    def _auth_headers(self, method: str, path: str) -> Dict[str, str]:
        timestamp_ms = int(time.time() * 1000)
        signature = self._sign(timestamp_ms, method, path)
        return {
            "KALSHI-ACCESS-KEY": self._api_key,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": str(timestamp_ms),
            "Content-Type": "application/json"
        }
        
    async def _request(self, method: str, endpoint: str, params: Dict = None, json_data: Dict = None) -> Dict:
        path = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        url = f"{self.BASE_URL}{path}"
        
        headers = self._auth_headers(method, f"/trade-api/v2{path}")
        
        async with self._session.request(method, url, headers=headers, params=params, json=json_data) as resp:
            if resp.status == 401:
                raise KalshiAuthError("Authentication failed")
            if resp.status != 200:
                text = await resp.text()
                raise KalshiAPIError(f"API error: {text}", resp.status)
            return await resp.json()
            
    # === ALLOWLIST MANAGEMENT ===
    
    async def _refresh_allowlist(self) -> None:
        """Refresh the set of allowed market tickers from allowed series"""
        self._allowed_market_tickers.clear()
        
        for series_ticker in self._allowed_series:
            try:
                params = {"series_ticker": series_ticker, "status": "open", "limit": 200}
                data = await self._request("GET", "/markets", params=params)
                markets = data.get("markets", [])
                
                for m in markets:
                    ticker = m.get("ticker", "")
                    # Skip MVE parlays even if they sneak in
                    if m.get("mve_collection_ticker") or "KXMVE" in ticker:
                        continue
                    self._allowed_market_tickers.add(ticker)
                    
            except Exception as e:
                logger.warning(f"Failed to fetch markets for series {series_ticker}: {e}")
                
        self._allowlist_refreshed_at = datetime.now(timezone.utc)
        logger.info(f"Allowlist refreshed: {len(self._allowed_market_tickers)} markets from {len(self._allowed_series)} series")
        
    def is_market_allowed(self, ticker: str) -> bool:
        """Check if a market ticker is in the allowlist"""
        return ticker in self._allowed_market_tickers
        
    def assert_allowed(self, ticker: str) -> None:
        """Raise error if market is not allowed"""
        if not self.is_market_allowed(ticker):
            raise PermissionError(f"Market {ticker} not in allowlist - trading blocked")
            
    # === MARKET DATA ===
    
    async def get_balance(self) -> Decimal:
        data = await self._request("GET", "/portfolio/balance")
        return Decimal(str(data.get("balance", 0))) / 100
        
    async def get_markets(self, status: str = "open", limit: int = 200) -> List[Dict]:
        """Get markets - ONLY from allowed series"""
        all_markets = []
        
        for series_ticker in self._allowed_series:
            try:
                params = {"series_ticker": series_ticker, "status": status, "limit": limit}
                data = await self._request("GET", "/markets", params=params)
                markets = data.get("markets", [])
                
                # Filter out MVE
                for m in markets:
                    if not m.get("mve_collection_ticker") and "KXMVE" not in m.get("ticker", ""):
                        all_markets.append(m)
                        
            except Exception as e:
                logger.debug(f"Error fetching {series_ticker}: {e}")
                
        return all_markets
        
    async def get_markets_by_series(self, series_tickers: List[str] = None, status: str = "open", limit: int = 200) -> List[Dict]:
        """Get markets from specific series - enforces allowlist"""
        if series_tickers is None:
            series_tickers = list(self._allowed_series)
        else:
            # Filter to only allowed series
            series_tickers = [s for s in series_tickers if s in self._allowed_series]
            
        all_markets = []
        for series in series_tickers:
            try:
                params = {"series_ticker": series, "status": status, "limit": limit}
                data = await self._request("GET", "/markets", params=params)
                markets = data.get("markets", [])
                for m in markets:
                    if not m.get("mve_collection_ticker") and "KXMVE" not in m.get("ticker", ""):
                        all_markets.append(m)
            except Exception as e:
                logger.debug(f"Error fetching series {series}: {e}")
                
        return all_markets
        
    async def get_market(self, ticker: str) -> Dict:
        self.assert_allowed(ticker)
        data = await self._request("GET", f"/markets/{ticker}")
        return data.get("market", data)
        
    async def get_orderbook(self, ticker: str, depth: int = 10) -> Dict:
        # No allowlist check for orderbook - needed for scanning
        data = await self._request("GET", f"/markets/{ticker}/orderbook", params={"depth": depth})
        return data
        
    async def get_positions(self) -> List[Dict]:
        data = await self._request("GET", "/portfolio/positions")
        return data.get("market_positions", [])
        
    # === TRADING (with allowlist enforcement) ===
        
    async def place_order(self, ticker: str, side: str, quantity: int, price_cents: int) -> OrderResponse:
        """Place order - ENFORCES ALLOWLIST"""
        self.assert_allowed(ticker)
        
        order_data = {
            "ticker": ticker,
            "action": "buy" if side.lower() in ["buy", "yes"] else "sell",
            "side": "yes",
            "type": "limit",
            "count": quantity,
            "yes_price": price_cents
        }
        
        data = await self._request("POST", "/portfolio/orders", json_data=order_data)
        return self._parse_order_response(data.get("order", data))
        
    async def cancel_order(self, order_id: str) -> bool:
        await self._request("DELETE", f"/portfolio/orders/{order_id}")
        return True
        
    def _parse_order_response(self, data: Dict) -> OrderResponse:
        return OrderResponse(
            order_id=data.get("order_id", ""),
            ticker=data.get("ticker", ""),
            side=Side.YES if data.get("side") == "yes" else Side.NO,
            status=OrderStatus.OPEN,
            requested_count=data.get("count", 0),
            filled_count=data.get("count", 0) - data.get("remaining_count", 0),
            remaining_count=data.get("remaining_count", 0),
            price=data.get("yes_price"),
            avg_fill_price=Decimal(str(data.get("avg_fill_price", 0))) / 100 if data.get("avg_fill_price") else None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        
    @staticmethod
    @staticmethod
    def normalize_market(raw: Dict, orderbook: Dict = None) -> NormalizedMarket:
        """Convert Kalshi API response to NormalizedMarket"""
        # Parse orderbook - Kalshi has yes/no sides, each can be None or list of [price, quantity]
        yes_bids = []
        no_bids = []
        
        if orderbook and isinstance(orderbook, dict):
            ob = orderbook.get("orderbook", {})
            if ob:
                yes_data = ob.get("yes")
                if yes_data and isinstance(yes_data, list):
                    yes_bids = yes_data
                no_data = ob.get("no")
                if no_data and isinstance(no_data, list):
                    no_bids = no_data
        
        # Best bid is highest YES bid (if any)
        best_bid = Decimal(str(yes_bids[0][0])) / 100 if yes_bids else Decimal("0")
        bid_size = yes_bids[0][1] if yes_bids else 0
        
        # Best ask comes from NO bids (100 - no_bid = yes_ask) or default to 1
        if no_bids:
            best_ask = (100 - no_bids[0][0]) / Decimal("100")
            ask_size = no_bids[0][1]
        else:
            best_ask = Decimal("1")
            ask_size = 0
        
        # Determine category from ticker
        category = MarketCategory.CRYPTO
        ticker = raw.get("ticker", "").upper()
        if "INX" in ticker or "NASDAQ" in ticker:
            category = MarketCategory.ECONOMICS
            
        expiry_str = raw.get("expiration_time", raw.get("close_time", "2099-12-31T23:59:59Z"))
        expiry = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
        
        return NormalizedMarket(
            venue=Venue.KALSHI,
            ticker=raw.get("ticker", ""),
            question=raw.get("title", raw.get("subtitle", "")),
            category=category,
            expiry=expiry,
            best_bid=best_bid,
            best_ask=best_ask,
            bid_size=bid_size,
            ask_size=ask_size,
            last_price=Decimal(str(raw.get("last_price", 50))) / 100 if raw.get("last_price") else None,
            volume_24h=raw.get("volume_24h", raw.get("volume", 0)),
            open_interest=raw.get("open_interest")
        )

async def create_kalshi_client(use_tor: bool = True) -> KalshiClient:
    """Create and connect a Kalshi client"""
    client = KalshiClient(use_tor=use_tor)
    await client.connect()
    return client
