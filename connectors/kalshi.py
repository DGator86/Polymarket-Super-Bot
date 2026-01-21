"""
Kalshi API Connector

Handles authentication (RSA signing), REST API calls, and WebSocket streaming.
This is the primary execution venue.

API Documentation: https://trading-api.readme.io/reference/getting-started
"""

import asyncio
import aiohttp
import websockets
import json
import base64
import time
import logging
from aiohttp_socks import ProxyConnector
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, List, Dict, Any, Callable, Awaitable
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

from config import config
from core.models import (
    Venue, Side, OrderType, OrderStatus, MarketCategory,
    NormalizedMarket, Orderbook, OrderbookLevel,
    OrderRequest, OrderResponse, Position, AccountBalance
)

logger = logging.getLogger(__name__)


class KalshiAuthError(Exception):
    """Authentication failed"""
    pass


class KalshiAPIError(Exception):
    """API request failed"""
    def __init__(self, message: str, status_code: int = 0, response: Dict = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response or {}


class KalshiClient:
    """
    Low-level Kalshi API client with RSA authentication.
    
    Usage:
        client = KalshiClient(api_key, private_key_path)
        await client.connect()
        markets = await client.get_markets()
        await client.close()
    """
    
    def __init__(self, api_key: str = None, private_key_path: str = None):
        self.api_key = api_key or config.kalshi.api_key
        self.private_key_path = private_key_path or config.kalshi.private_key_path
        
        # Select production or demo environment
        if config.kalshi.use_demo:
            self.base_url = config.kalshi.demo_base_url
            self.ws_url = config.kalshi.demo_ws_url
        else:
            self.base_url = config.kalshi.base_url
            self.ws_url = config.kalshi.ws_url
        
        self.private_key = None
        self.token: Optional[str] = None
        self.token_expiry: float = 0
        self.session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        
    async def connect(self):
        """Initialize client: load key and create session"""
        self._load_private_key()
        
        try:
            # Try to use local SOCKS5 proxy if available (fixes 403 blocks)
            connector = ProxyConnector.from_url("socks5://127.0.0.1:9050")
            self.session = aiohttp.ClientSession(connector=connector)
            logger.info("Using SOCKS5 proxy at 127.0.0.1:9050")
        except Exception as e:
            logger.warning(f"Proxy connection failed: {e}. Falling back to direct connection.")
            self.session = aiohttp.ClientSession()

        await self._ensure_token()
        logger.info(f"Kalshi client connected to {self.base_url}")
        
    async def close(self):
        """Clean up resources"""
        if self._ws:
            await self._ws.close()
        if self.session:
            await self.session.close()
        logger.info("Kalshi client disconnected")
    
    def _load_private_key(self):
        """Load RSA private key from file"""
        try:
            with open(self.private_key_path, "rb") as f:
                self.private_key = serialization.load_pem_private_key(
                    f.read(), 
                    password=None,
                    backend=default_backend()
                )
        except FileNotFoundError:
            raise KalshiAuthError(f"Private key not found: {self.private_key_path}")
        except Exception as e:
            raise KalshiAuthError(f"Failed to load private key: {e}")
    
    def _sign(self, timestamp_ms: int, method: str, path: str) -> str:
        """
        Create RSA-PSS signature for request authentication.
        
        Kalshi requires: sign(timestamp_ms + method + path) using PSS padding
        Note: Path should have query params stripped before signing
        """
        # Strip query parameters for signing
        path_without_query = path.split('?')[0]
        message = f"{timestamp_ms}{method}{path_without_query}".encode('utf-8')
        signature = self.private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode('utf-8')
    
    async def _ensure_token(self):
        """
        Legacy method - Kalshi no longer uses login tokens.
        Authentication is now done per-request using RSA-PSS signatures.
        This method is kept for backwards compatibility but is a no-op.
        """
        pass  # No longer needed - per-request PSS signing is used instead
    
    def _auth_headers(self, method: str, path: str) -> Dict[str, str]:
        """
        Generate authentication headers for a request using RSA-PSS.
        
        Kalshi API now requires per-request signing with:
        - KALSHI-ACCESS-KEY: Your API key ID
        - KALSHI-ACCESS-SIGNATURE: RSA-PSS signature of (timestamp + method + path)
        - KALSHI-ACCESS-TIMESTAMP: Current timestamp in milliseconds
        """
        timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        full_path = f"/trade-api/v2{path}"
        signature = self._sign(timestamp_ms, method, full_path)
        
        return {
            "KALSHI-ACCESS-KEY": self.api_key,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": str(timestamp_ms),
            "Content-Type": "application/json"
        }
    
    async def _request(
        self, 
        method: str, 
        path: str, 
        params: Dict = None, 
        json_data: Dict = None
    ) -> Dict[str, Any]:
        """Make authenticated API request with retry logic using per-request PSS signing"""
        url = f"{self.base_url}{path}"
        
        for attempt in range(config.execution.retry_attempts):
            try:
                # Generate fresh auth headers for each attempt
                headers = self._auth_headers(method, path)
                
                async with self.session.request(
                    method, 
                    url, 
                    headers=headers, 
                    params=params,
                    json=json_data
                ) as resp:
                    # Handle non-JSON responses (like CloudFront errors)
                    content_type = resp.headers.get('Content-Type', '')
                    if 'application/json' not in content_type:
                        text = await resp.text()
                        if resp.status != 200:
                            raise KalshiAPIError(
                                f"API error (non-JSON): {resp.status}",
                                status_code=resp.status,
                                response={"error": text[:500]}
                            )
                        return {}
                    
                    data = await resp.json()
                    
                    if resp.status == 200:
                        return data
                    elif resp.status == 401:
                        # Invalid signature - regenerate and retry
                        logger.warning(f"401 Unauthorized - attempt {attempt + 1}")
                        await asyncio.sleep(config.execution.retry_delay_seconds)
                        continue
                    elif resp.status == 403:
                        # CloudFront or access denied
                        raise KalshiAPIError(
                            f"Access denied (403) - possible geo-blocking or IP restriction",
                            status_code=resp.status,
                            response=data
                        )
                    else:
                        raise KalshiAPIError(
                            f"API error: {resp.status}",
                            status_code=resp.status,
                            response=data
                        )
            except aiohttp.ClientError as e:
                if attempt == config.execution.retry_attempts - 1:
                    raise
                await asyncio.sleep(config.execution.retry_delay_seconds)
        
        raise KalshiAPIError("Max retries exceeded")

    # =========================================================================
    # MARKET DATA ENDPOINTS
    # =========================================================================
    
    async def get_markets(
        self, 
        status: str = "open",
        limit: int = 100,
        cursor: str = None,
        series_ticker: str = None,
        event_ticker: str = None
    ) -> List[Dict]:
        """
        Fetch available markets.
        
        Args:
            status: "open", "closed", "settled"
            limit: Max markets to return (1-1000)
            cursor: Pagination cursor
            series_ticker: Filter by series
            event_ticker: Filter by event
        
        Returns:
            List of market dictionaries
        """
        params = {"status": status, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        if series_ticker:
            params["series_ticker"] = series_ticker
        if event_ticker:
            params["event_ticker"] = event_ticker
        
        data = await self._request("GET", "/markets", params=params)
        return data.get("markets", [])
    
    async def get_market(self, ticker: str) -> Dict:
        """Get single market by ticker"""
        data = await self._request("GET", f"/markets/{ticker}")
        return data.get("market", {})
    
    async def get_orderbook(self, ticker: str, depth: int = 10) -> Dict:
        """
        Get orderbook for a market.
        
        Returns:
            {
                "yes": {"bids": [[price, size], ...], "asks": [[price, size], ...]},
                "no": {"bids": [...], "asks": [...]}
            }
        """
        params = {"depth": depth}
        return await self._request("GET", f"/markets/{ticker}/orderbook", params=params)
    
    async def get_trades(
        self, 
        ticker: str = None, 
        limit: int = 100,
        cursor: str = None
    ) -> List[Dict]:
        """Get recent trades, optionally filtered by ticker"""
        params = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        if cursor:
            params["cursor"] = cursor
        
        data = await self._request("GET", "/markets/trades", params=params)
        return data.get("trades", [])

    # =========================================================================
    # ORDER ENDPOINTS
    # =========================================================================
    
    async def place_order(self, order: OrderRequest) -> OrderResponse:
        """
        Place a new order.
        
        Args:
            order: OrderRequest with ticker, side, count, price
            
        Returns:
            OrderResponse with order details and status
        """
        payload = {
            "ticker": order.ticker,
            "side": order.side.value,
            "count": order.count,
            "type": order.order_type.value,
            "action": "buy"  # Always buy; side determines YES or NO
        }
        
        if order.price is not None:
            # Kalshi uses yes_price for limit orders
            if order.side == Side.YES:
                payload["yes_price"] = order.price
            else:
                # For NO orders, yes_price = 100 - no_price
                payload["yes_price"] = 100 - order.price
        
        if order.client_order_id:
            payload["client_order_id"] = order.client_order_id
        
        data = await self._request("POST", "/orders", json_data=payload)
        
        if "order" not in data:
            raise KalshiAPIError("Order response missing 'order' field", response=data)
        
        return self._parse_order_response(data["order"], order.count)
    
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an existing order by ID"""
        try:
            await self._request("DELETE", f"/orders/{order_id}")
            return True
        except KalshiAPIError as e:
            if e.status_code == 404:
                return False  # Already filled or cancelled
            raise
    
    async def get_order(self, order_id: str) -> OrderResponse:
        """Get order status by ID"""
        data = await self._request("GET", f"/orders/{order_id}")
        return self._parse_order_response(data.get("order", {}))
    
    async def get_orders(
        self, 
        ticker: str = None,
        status: str = None,
        limit: int = 100
    ) -> List[OrderResponse]:
        """Get orders with optional filters"""
        params = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        if status:
            params["status"] = status
        
        data = await self._request("GET", "/orders", params=params)
        return [self._parse_order_response(o) for o in data.get("orders", [])]

    # =========================================================================
    # PORTFOLIO ENDPOINTS
    # =========================================================================
    
    async def get_balance(self) -> AccountBalance:
        """Get account balance"""
        data = await self._request("GET", "/portfolio/balance")
        
        # Kalshi returns balance in cents
        available = Decimal(str(data.get("balance", 0))) / 100
        portfolio = Decimal(str(data.get("portfolio_value", 0))) / 100
        
        return AccountBalance(
            venue=Venue.KALSHI,
            available_balance=available,
            portfolio_value=portfolio,
            total_equity=available + portfolio
        )
    
    async def get_positions(self) -> List[Position]:
        """Get all current positions"""
        data = await self._request("GET", "/portfolio/positions")
        
        positions = []
        for mp in data.get("market_positions", []):
            # Determine side and quantity from position
            yes_qty = mp.get("position", 0)
            
            if yes_qty > 0:
                side = Side.YES
                qty = yes_qty
            elif yes_qty < 0:
                side = Side.NO
                qty = abs(yes_qty)
            else:
                continue  # No position
            
            # Get current market price for P&L calc
            market = await self.get_market(mp["ticker"])
            current_price = Decimal(str(market.get("last_price", 50))) / 100
            
            avg_entry = Decimal(str(mp.get("average_price", 50))) / 100
            
            positions.append(Position(
                ticker=mp["ticker"],
                venue=Venue.KALSHI,
                side=side,
                quantity=qty,
                avg_entry_price=avg_entry,
                current_price=current_price,
                unrealized_pnl=(current_price - avg_entry) * qty if side == Side.YES else (avg_entry - current_price) * qty
            ))
        
        return positions

    # =========================================================================
    # WEBSOCKET STREAMING
    # =========================================================================
    
    async def stream_orderbook(
        self, 
        tickers: List[str], 
        callback: Callable[[Dict], Awaitable[None]]
    ):
        """
        Stream real-time orderbook updates.
        
        Args:
            tickers: List of market tickers to subscribe
            callback: Async function called with each update
        """
        await self._ensure_token()
        
        async with websockets.connect(self.ws_url) as ws:
            self._ws = ws
            
            # Authenticate
            auth_msg = {
                "id": 0,
                "cmd": "login",
                "params": {"token": self.token}
            }
            await ws.send(json.dumps(auth_msg))
            
            # Subscribe to orderbook deltas
            sub_msg = {
                "id": 1,
                "cmd": "subscribe",
                "params": {
                    "channels": ["orderbook_delta"],
                    "market_tickers": tickers
                }
            }
            await ws.send(json.dumps(sub_msg))
            
            logger.info(f"Subscribed to orderbook updates for {len(tickers)} markets")
            
            async for message in ws:
                try:
                    data = json.loads(message)
                    msg_type = data.get("type")
                    
                    if msg_type == "orderbook_delta":
                        await callback(data)
                    elif msg_type == "error":
                        logger.error(f"WebSocket error: {data}")
                    elif msg_type == "subscribed":
                        logger.debug(f"Subscription confirmed: {data}")
                        
                except json.JSONDecodeError:
                    logger.warning(f"Invalid WebSocket message: {message[:100]}")
                except Exception as e:
                    logger.error(f"Error processing WebSocket message: {e}")
    
    async def stream_trades(
        self, 
        tickers: List[str], 
        callback: Callable[[Dict], Awaitable[None]]
    ):
        """Stream real-time trade executions"""
        await self._ensure_token()
        
        async with websockets.connect(self.ws_url) as ws:
            self._ws = ws
            
            await ws.send(json.dumps({
                "id": 0,
                "cmd": "login",
                "params": {"token": self.token}
            }))
            
            await ws.send(json.dumps({
                "id": 1,
                "cmd": "subscribe",
                "params": {
                    "channels": ["trade"],
                    "market_tickers": tickers
                }
            }))
            
            async for message in ws:
                try:
                    data = json.loads(message)
                    if data.get("type") == "trade":
                        await callback(data)
                except Exception as e:
                    logger.error(f"Error in trade stream: {e}")

    # =========================================================================
    # HELPER METHODS
    # =========================================================================
    
    def _parse_order_response(self, data: Dict, requested_count: int = None) -> OrderResponse:
        """Parse API order response into OrderResponse model"""
        status_map = {
            "pending": OrderStatus.PENDING,
            "open": OrderStatus.OPEN,
            "filled": OrderStatus.FILLED,
            "cancelled": OrderStatus.CANCELLED,
            "expired": OrderStatus.EXPIRED,
        }
        
        filled = data.get("filled_count", 0)
        remaining = data.get("remaining_count", 0)
        
        avg_fill = None
        if data.get("avg_fill_price"):
            avg_fill = Decimal(str(data["avg_fill_price"])) / 100
        
        return OrderResponse(
            order_id=data.get("order_id", ""),
            ticker=data.get("ticker", ""),
            side=Side(data.get("side", "yes")),
            status=status_map.get(data.get("status", "pending"), OrderStatus.PENDING),
            requested_count=requested_count or (filled + remaining),
            filled_count=filled,
            remaining_count=remaining,
            price=data.get("yes_price"),
            avg_fill_price=avg_fill,
            created_at=datetime.fromisoformat(data.get("created_time", "2000-01-01T00:00:00Z").replace("Z", "+00:00")),
            updated_at=datetime.fromisoformat(data.get("updated_time", "2000-01-01T00:00:00Z").replace("Z", "+00:00"))
        )
    
    @staticmethod
    def normalize_market(raw: Dict, orderbook: Dict = None) -> NormalizedMarket:
        """Convert Kalshi API response to NormalizedMarket"""
        
        # Parse orderbook for best bid/ask
        if orderbook:
            ob_data = orderbook.get("orderbook") or {}
            yes_data = ob_data.get("yes") or {}
            bids = yes_data.get("bids") or []
            asks = yes_data.get("asks") or []
        else:
            bids = []
            asks = []
        
        best_bid = Decimal(str(bids[0][0])) / 100 if bids else Decimal("0")
        best_ask = Decimal(str(asks[0][0])) / 100 if asks else Decimal("1")
        bid_size = bids[0][1] if bids else 0
        ask_size = asks[0][1] if asks else 0
        
        # Determine category from market metadata
        category = MarketCategory.OTHER
        cat_str = raw.get("category", "").lower()
        if "econ" in cat_str or "cpi" in cat_str or "fed" in cat_str:
            category = MarketCategory.ECONOMICS
        elif "politic" in cat_str or "election" in cat_str:
            category = MarketCategory.POLITICS
        elif "weather" in cat_str or "temperature" in cat_str:
            category = MarketCategory.WEATHER
        elif "crypto" in cat_str or "bitcoin" in cat_str:
            category = MarketCategory.CRYPTO
        elif "sport" in cat_str:
            category = MarketCategory.SPORTS
        
        # Parse expiration time
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
            volume_24h=raw.get("volume_24h"),
            open_interest=raw.get("open_interest")
        )


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

async def create_kalshi_client() -> KalshiClient:
    """Factory function to create and connect a Kalshi client"""
    client = KalshiClient()
    await client.connect()
    return client
