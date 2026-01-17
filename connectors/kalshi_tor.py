"""
Kalshi API Connector with Tor Support

Routes all API requests through Tor SOCKS5 proxy to bypass CloudFront blocks.
"""

import asyncio
import aiohttp
from aiohttp_socks import ProxyConnector
import json
import base64
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, List, Dict, Any
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

# Tor SOCKS5 proxy
TOR_PROXY = 'socks5://127.0.0.1:9050'


class KalshiAuthError(Exception):
    pass


class KalshiAPIError(Exception):
    def __init__(self, message: str, status_code: int = 0, response: Dict = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response or {}


class KalshiClient:
    """Kalshi API client with Tor proxy support"""
    
    def __init__(self, api_key: str = None, private_key_path: str = None, use_tor: bool = True):
        self.api_key = api_key or config.kalshi.api_key
        self.private_key_path = private_key_path or config.kalshi.private_key_path
        self.use_tor = use_tor
        
        # Always use elections API
        self.base_url = 'https://api.elections.kalshi.com/trade-api/v2'
        self.ws_url = 'wss://api.elections.kalshi.com/trade-api/ws/v2'
        
        self.private_key = None
        self.session: Optional[aiohttp.ClientSession] = None
        
    async def connect(self):
        """Initialize client with Tor proxy"""
        self._load_private_key()
        
        if self.use_tor:
            connector = ProxyConnector.from_url(TOR_PROXY)
            self.session = aiohttp.ClientSession(connector=connector)
            logger.info(f'Kalshi client connected via Tor to {self.base_url}')
        else:
            self.session = aiohttp.ClientSession()
            logger.info(f'Kalshi client connected directly to {self.base_url}')
        
    async def close(self):
        if self.session:
            await self.session.close()
        logger.info('Kalshi client disconnected')
    
    def _load_private_key(self):
        try:
            with open(self.private_key_path, 'rb') as f:
                self.private_key = serialization.load_pem_private_key(
                    f.read(), password=None, backend=default_backend()
                )
        except FileNotFoundError:
            raise KalshiAuthError(f'Private key not found: {self.private_key_path}')
        except Exception as e:
            raise KalshiAuthError(f'Failed to load private key: {e}')
    
    def _sign(self, timestamp_ms: int, method: str, path: str) -> str:
        path_without_query = path.split('?')[0]
        message = f'{timestamp_ms}{method}{path_without_query}'.encode('utf-8')
        signature = self.private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode('utf-8')
    
    def _auth_headers(self, method: str, path: str) -> Dict[str, str]:
        timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        full_path = f'/trade-api/v2{path}'
        signature = self._sign(timestamp_ms, method, full_path)
        
        return {
            'KALSHI-ACCESS-KEY': self.api_key,
            'KALSHI-ACCESS-SIGNATURE': signature,
            'KALSHI-ACCESS-TIMESTAMP': str(timestamp_ms),
            'Content-Type': 'application/json'
        }
    
    async def _request(self, method: str, path: str, params: Dict = None, json_data: Dict = None) -> Dict[str, Any]:
        url = f'{self.base_url}{path}'
        
        for attempt in range(3):
            try:
                headers = self._auth_headers(method, path)
                
                async with self.session.request(
                    method, url, headers=headers, params=params, json=json_data
                ) as resp:
                    content_type = resp.headers.get('Content-Type', '')
                    if 'application/json' not in content_type:
                        text = await resp.text()
                        if resp.status != 200:
                            raise KalshiAPIError(
                                f'API error (non-JSON): {resp.status}',
                                status_code=resp.status,
                                response={'error': text[:500]}
                            )
                        return {}
                    
                    data = await resp.json()
                    
                    if resp.status == 200:
                        return data
                    elif resp.status == 401:
                        logger.warning(f'401 Unauthorized - attempt {attempt + 1}')
                        await asyncio.sleep(0.5)
                        continue
                    else:
                        raise KalshiAPIError(
                            data.get('error', f'HTTP {resp.status}'),
                            status_code=resp.status,
                            response=data
                        )
            except aiohttp.ClientError as e:
                logger.warning(f'Request failed (attempt {attempt + 1}): {e}')
                if attempt < 2:
                    await asyncio.sleep(1)
                    continue
                raise KalshiAPIError(f'Connection error: {e}')
        
        raise KalshiAPIError('Max retries exceeded')
    
    async def get_balance(self) -> AccountBalance:
        data = await self._request('GET', '/portfolio/balance')
        return AccountBalance(
            venue=Venue.KALSHI,
            available_balance=Decimal(str(data.get('balance', 0))) / 100,
            portfolio_value=Decimal(str(data.get('portfolio_value', 0))) / 100,
            total_equity=Decimal(str(data.get('balance', 0) + data.get('portfolio_value', 0))) / 100,
            pending_orders_value=Decimal('0'),
            margin_used=Decimal('0'),
            updated_at=datetime.now(timezone.utc)
        )
    
    async def get_markets(self, status: str = 'open', limit: int = 100, cursor: str = None) -> List[Dict]:
        params = {'status': status, 'limit': limit}
        if cursor:
            params['cursor'] = cursor
        data = await self._request('GET', '/markets', params=params)
        return data.get('markets', [])
    
    async def get_market(self, ticker: str) -> Dict:
        return await self._request('GET', f'/markets/{ticker}')
    
    async def get_orderbook(self, ticker: str, depth: int = 10) -> Dict:
        params = {'depth': depth}
        return await self._request('GET', f'/markets/{ticker}/orderbook', params=params)
    
    async def get_positions(self) -> List[Dict]:
        data = await self._request('GET', '/portfolio/positions')
        return data.get('market_positions', [])
    
    async def place_order(self, order: OrderRequest) -> OrderResponse:
        json_data = {
            'ticker': order.ticker,
            'action': 'buy' if order.side == Side.YES else 'sell',
            'type': order.order_type.value,
            'count': order.count,
        }
        if order.price:
            json_data['yes_price'] = int(order.price)
        
        data = await self._request('POST', '/portfolio/orders', json_data=json_data)
        return self._parse_order_response(data.get('order', data))
    
    async def cancel_order(self, order_id: str) -> bool:
        await self._request('DELETE', f'/portfolio/orders/{order_id}')
        return True
    
    def _parse_order_response(self, data: Dict) -> OrderResponse:
        status_map = {
            'pending': OrderStatus.pending,
            'open': OrderStatus.open,
            'filled': OrderStatus.filled,
            'cancelled': OrderStatus.cancelled,
        }
        return OrderResponse(
            order_id=data.get('order_id', ''),
            ticker=data.get('ticker', ''),
            side=Side.YES if data.get('action') == 'buy' else Side.NO,
            status=status_map.get(data.get('status', ''), OrderStatus.pending),
            requested_count=data.get('count', 0),
            filled_count=data.get('filled_count', 0),
            remaining_count=data.get('remaining_count', 0),
            price=Decimal(str(data.get('yes_price', 0))) / 100 if data.get('yes_price') else None,
            avg_fill_price=Decimal(str(data.get('avg_fill_price', 0))) / 100 if data.get('avg_fill_price') else None,
            created_at=datetime.fromisoformat(data.get('created_time', datetime.now(timezone.utc).isoformat()).replace('Z', '+00:00')),
            updated_at=datetime.now(timezone.utc)
        )


def create_kalshi_client(use_tor: bool = True) -> KalshiClient:
    return KalshiClient(use_tor=use_tor)
