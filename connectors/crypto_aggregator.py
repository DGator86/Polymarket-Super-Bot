"""
Multi-Source Crypto Price Aggregator
Aggregates real-time prices from multiple exchanges for robust fair value estimation.
Sources: Coinbase, Binance, Kraken, OKX, Bybit, CoinGecko
"""

import asyncio
import aiohttp
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from decimal import Decimal
from datetime import datetime, timezone
from statistics import median, stdev
from collections import deque
import logging

logger = logging.getLogger(__name__)


@dataclass
class PricePoint:
    """Single price observation from an exchange."""
    exchange: str
    symbol: str
    price: Decimal
    bid: Optional[Decimal] = None
    ask: Optional[Decimal] = None
    volume_24h: Optional[Decimal] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    latency_ms: float = 0.0


@dataclass
class AggregatedPrice:
    """Aggregated price from multiple sources with confidence metrics."""
    symbol: str
    fair_value: Decimal
    median_price: Decimal
    vwap: Decimal
    best_bid: Decimal
    best_ask: Decimal
    spread_bps: float
    num_sources: int
    sources: List[str]
    outliers_removed: List[str]
    confidence: float  # 0-1, based on agreement between sources
    volatility_1m: Optional[float] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ExchangeConnector:
    """Base class for exchange connectors."""
    
    def __init__(self, name: str, rate_limit_ms: int = 100):
        self.name = name
        self.rate_limit_ms = rate_limit_ms
        self.last_request = 0.0
        self.session: Optional[aiohttp.ClientSession] = None
        self.enabled = True
        self.consecutive_failures = 0
        self.max_failures = 5
        
    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=5)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session
        
    async def _rate_limit(self):
        now = time.time() * 1000
        elapsed = now - self.last_request
        if elapsed < self.rate_limit_ms:
            await asyncio.sleep((self.rate_limit_ms - elapsed) / 1000)
        self.last_request = time.time() * 1000
        
    async def fetch_price(self, symbol: str) -> Optional[PricePoint]:
        raise NotImplementedError
        
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()


class CoinbaseConnector(ExchangeConnector):
    """Coinbase Pro/Advanced Trade API."""
    
    def __init__(self):
        super().__init__("coinbase", rate_limit_ms=100)
        self.base_url = "https://api.exchange.coinbase.com"
        self.symbol_map = {
            "BTC": "BTC-USD",
            "ETH": "ETH-USD",
            "SOL": "SOL-USD",
            "DOGE": "DOGE-USD",
        }
        
    async def fetch_price(self, symbol: str) -> Optional[PricePoint]:
        if not self.enabled:
            return None
        await self._rate_limit()
        
        product_id = self.symbol_map.get(symbol.upper(), f"{symbol.upper()}-USD")
        start = time.time()
        
        try:
            session = await self._get_session()
            async with session.get(f"{self.base_url}/products/{product_id}/ticker") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    latency = (time.time() - start) * 1000
                    self.consecutive_failures = 0
                    return PricePoint(
                        exchange=self.name,
                        symbol=symbol.upper(),
                        price=Decimal(str(data.get('price', 0))),
                        bid=Decimal(str(data.get('bid', 0))) if data.get('bid') else None,
                        ask=Decimal(str(data.get('ask', 0))) if data.get('ask') else None,
                        volume_24h=Decimal(str(data.get('volume', 0))) if data.get('volume') else None,
                        latency_ms=latency
                    )
                else:
                    logger.warning(f"Coinbase {product_id}: HTTP {resp.status}")
        except Exception as e:
            logger.error(f"Coinbase error: {e}")
            self.consecutive_failures += 1
            if self.consecutive_failures >= self.max_failures:
                self.enabled = False
                logger.warning(f"Coinbase disabled after {self.max_failures} failures")
        return None


class BinanceConnector(ExchangeConnector):
    """Binance public API."""
    
    def __init__(self):
        super().__init__("binance", rate_limit_ms=50)
        self.base_url = "https://api.binance.us/api/v3"  # US endpoint
        self.symbol_map = {
            "BTC": "BTCUSDT",
            "ETH": "ETHUSDT",
            "SOL": "SOLUSDT",
            "DOGE": "DOGEUSDT",
        }
        
    async def fetch_price(self, symbol: str) -> Optional[PricePoint]:
        if not self.enabled:
            return None
        await self._rate_limit()
        
        binance_symbol = self.symbol_map.get(symbol.upper(), f"{symbol.upper()}USDT")
        start = time.time()
        
        try:
            session = await self._get_session()
            async with session.get(
                f"{self.base_url}/ticker/bookTicker",
                params={"symbol": binance_symbol}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    latency = (time.time() - start) * 1000
                    bid = Decimal(str(data.get('bidPrice', 0)))
                    ask = Decimal(str(data.get('askPrice', 0)))
                    self.consecutive_failures = 0
                    return PricePoint(
                        exchange=self.name,
                        symbol=symbol.upper(),
                        price=(bid + ask) / 2,
                        bid=bid,
                        ask=ask,
                        latency_ms=latency
                    )
        except Exception as e:
            logger.error(f"Binance error: {e}")
            self.consecutive_failures += 1
            if self.consecutive_failures >= self.max_failures:
                self.enabled = False
        return None


class KrakenConnector(ExchangeConnector):
    """Kraken public API."""
    
    def __init__(self):
        super().__init__("kraken", rate_limit_ms=200)
        self.base_url = "https://api.kraken.com/0/public"
        self.symbol_map = {
            "BTC": "XXBTZUSD",
            "ETH": "XETHZUSD",
            "SOL": "SOLUSD",
            "DOGE": "XDGUSD",
        }
        
    async def fetch_price(self, symbol: str) -> Optional[PricePoint]:
        if not self.enabled:
            return None
        await self._rate_limit()
        
        kraken_pair = self.symbol_map.get(symbol.upper(), f"{symbol.upper()}USD")
        start = time.time()
        
        try:
            session = await self._get_session()
            async with session.get(
                f"{self.base_url}/Ticker",
                params={"pair": kraken_pair}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('error'):
                        return None
                    result = data.get('result', {})
                    # Kraken returns data under the pair key
                    for key, ticker in result.items():
                        latency = (time.time() - start) * 1000
                        bid = Decimal(str(ticker['b'][0]))  # Best bid
                        ask = Decimal(str(ticker['a'][0]))  # Best ask
                        last = Decimal(str(ticker['c'][0]))  # Last trade
                        self.consecutive_failures = 0
                        return PricePoint(
                            exchange=self.name,
                            symbol=symbol.upper(),
                            price=last,
                            bid=bid,
                            ask=ask,
                            volume_24h=Decimal(str(ticker['v'][1])) if ticker.get('v') else None,
                            latency_ms=latency
                        )
        except Exception as e:
            logger.error(f"Kraken error: {e}")
            self.consecutive_failures += 1
            if self.consecutive_failures >= self.max_failures:
                self.enabled = False
        return None


class OKXConnector(ExchangeConnector):
    """OKX public API."""
    
    def __init__(self):
        super().__init__("okx", rate_limit_ms=100)
        self.base_url = "https://www.okx.com/api/v5"
        self.symbol_map = {
            "BTC": "BTC-USDT",
            "ETH": "ETH-USDT",
            "SOL": "SOL-USDT",
            "DOGE": "DOGE-USDT",
        }
        
    async def fetch_price(self, symbol: str) -> Optional[PricePoint]:
        if not self.enabled:
            return None
        await self._rate_limit()
        
        inst_id = self.symbol_map.get(symbol.upper(), f"{symbol.upper()}-USDT")
        start = time.time()
        
        try:
            session = await self._get_session()
            async with session.get(
                f"{self.base_url}/market/ticker",
                params={"instId": inst_id}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('code') == '0' and data.get('data'):
                        ticker = data['data'][0]
                        latency = (time.time() - start) * 1000
                        self.consecutive_failures = 0
                        return PricePoint(
                            exchange=self.name,
                            symbol=symbol.upper(),
                            price=Decimal(str(ticker.get('last', 0))),
                            bid=Decimal(str(ticker.get('bidPx', 0))),
                            ask=Decimal(str(ticker.get('askPx', 0))),
                            volume_24h=Decimal(str(ticker.get('vol24h', 0))),
                            latency_ms=latency
                        )
        except Exception as e:
            logger.error(f"OKX error: {e}")
            self.consecutive_failures += 1
            if self.consecutive_failures >= self.max_failures:
                self.enabled = False
        return None


class BybitConnector(ExchangeConnector):
    """Bybit public API."""
    
    def __init__(self):
        super().__init__("bybit", rate_limit_ms=100)
        self.base_url = "https://api.bybit.com/v5"
        self.symbol_map = {
            "BTC": "BTCUSDT",
            "ETH": "ETHUSDT",
            "SOL": "SOLUSDT",
            "DOGE": "DOGEUSDT",
        }
        
    async def fetch_price(self, symbol: str) -> Optional[PricePoint]:
        if not self.enabled:
            return None
        await self._rate_limit()
        
        bybit_symbol = self.symbol_map.get(symbol.upper(), f"{symbol.upper()}USDT")
        start = time.time()
        
        try:
            session = await self._get_session()
            async with session.get(
                f"{self.base_url}/market/tickers",
                params={"category": "spot", "symbol": bybit_symbol}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('retCode') == 0 and data.get('result', {}).get('list'):
                        ticker = data['result']['list'][0]
                        latency = (time.time() - start) * 1000
                        self.consecutive_failures = 0
                        return PricePoint(
                            exchange=self.name,
                            symbol=symbol.upper(),
                            price=Decimal(str(ticker.get('lastPrice', 0))),
                            bid=Decimal(str(ticker.get('bid1Price', 0))),
                            ask=Decimal(str(ticker.get('ask1Price', 0))),
                            volume_24h=Decimal(str(ticker.get('volume24h', 0))),
                            latency_ms=latency
                        )
        except Exception as e:
            logger.error(f"Bybit error: {e}")
            self.consecutive_failures += 1
            if self.consecutive_failures >= self.max_failures:
                self.enabled = False
        return None


class CoinGeckoConnector(ExchangeConnector):
    """CoinGecko API (free tier, lower rate limit)."""
    
    def __init__(self):
        super().__init__("coingecko", rate_limit_ms=1500)  # Free tier: 10-30 calls/min
        self.base_url = "https://api.coingecko.com/api/v3"
        self.symbol_map = {
            "BTC": "bitcoin",
            "ETH": "ethereum",
            "SOL": "solana",
            "DOGE": "dogecoin",
        }
        
    async def fetch_price(self, symbol: str) -> Optional[PricePoint]:
        if not self.enabled:
            return None
        await self._rate_limit()
        
        coin_id = self.symbol_map.get(symbol.upper())
        if not coin_id:
            return None
        start = time.time()
        
        try:
            session = await self._get_session()
            async with session.get(
                f"{self.base_url}/simple/price",
                params={
                    "ids": coin_id,
                    "vs_currencies": "usd",
                    "include_24hr_vol": "true"
                }
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if coin_id in data:
                        latency = (time.time() - start) * 1000
                        self.consecutive_failures = 0
                        return PricePoint(
                            exchange=self.name,
                            symbol=symbol.upper(),
                            price=Decimal(str(data[coin_id]['usd'])),
                            volume_24h=Decimal(str(data[coin_id].get('usd_24h_vol', 0))),
                            latency_ms=latency
                        )
        except Exception as e:
            logger.error(f"CoinGecko error: {e}")
            self.consecutive_failures += 1
            if self.consecutive_failures >= self.max_failures:
                self.enabled = False
        return None


class CryptoAggregator:
    """
    Aggregates prices from multiple exchanges with outlier detection.
    Provides robust fair value estimation for Kalshi pricing.
    """
    
    def __init__(self, outlier_threshold: float = 0.5):
        """
        Args:
            outlier_threshold: Maximum deviation from median (in %) to be considered valid
        """
        self.connectors: Dict[str, ExchangeConnector] = {
            "coinbase": CoinbaseConnector(),
            "binance": BinanceConnector(),
            "kraken": KrakenConnector(),
            "okx": OKXConnector(),
            "bybit": BybitConnector(),
            "coingecko": CoinGeckoConnector(),
        }
        self.outlier_threshold = outlier_threshold
        self.price_history: Dict[str, deque] = {}  # symbol -> deque of (timestamp, price)
        self.history_window = 60  # Keep 60 seconds of history
        
    async def fetch_all_prices(self, symbol: str) -> List[PricePoint]:
        """Fetch prices from all enabled exchanges concurrently."""
        tasks = [
            conn.fetch_price(symbol) 
            for conn in self.connectors.values() 
            if conn.enabled
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        prices = []
        for result in results:
            if isinstance(result, PricePoint) and result.price > 0:
                prices.append(result)
            elif isinstance(result, Exception):
                logger.debug(f"Fetch error: {result}")
                
        return prices
        
    def _detect_outliers(self, prices: List[PricePoint]) -> Tuple[List[PricePoint], List[str]]:
        """Remove prices that deviate too far from median."""
        if len(prices) < 3:
            return prices, []
            
        values = [float(p.price) for p in prices]
        med = median(values)
        
        valid = []
        outliers = []
        
        for p in prices:
            deviation = abs(float(p.price) - med) / med * 100
            if deviation <= self.outlier_threshold:
                valid.append(p)
            else:
                outliers.append(f"{p.exchange}({float(p.price):.2f}, {deviation:.2f}% off)")
                logger.warning(f"Outlier removed: {p.exchange} {p.price} ({deviation:.2f}% from median)")
                
        return valid, outliers
        
    def _calculate_vwap(self, prices: List[PricePoint]) -> Decimal:
        """Calculate volume-weighted average price (or simple average if no volume)."""
        prices_with_volume = [p for p in prices if p.volume_24h and p.volume_24h > 0]
        
        if len(prices_with_volume) >= 2:
            total_volume = sum(float(p.volume_24h) for p in prices_with_volume)
            vwap = sum(float(p.price) * float(p.volume_24h) for p in prices_with_volume) / total_volume
            return Decimal(str(round(vwap, 2)))
        else:
            # Fall back to simple average
            return Decimal(str(round(sum(float(p.price) for p in prices) / len(prices), 2)))
            
    def _update_history(self, symbol: str, price: Decimal):
        """Update price history for volatility calculation."""
        if symbol not in self.price_history:
            self.price_history[symbol] = deque(maxlen=120)  # 2 minutes at 1/sec
            
        now = time.time()
        self.price_history[symbol].append((now, float(price)))
        
        # Clean old entries
        cutoff = now - self.history_window
        while self.price_history[symbol] and self.price_history[symbol][0][0] < cutoff:
            self.price_history[symbol].popleft()
            
    def _calculate_volatility(self, symbol: str) -> Optional[float]:
        """Calculate 1-minute rolling volatility (annualized)."""
        if symbol not in self.price_history or len(self.price_history[symbol]) < 10:
            return None
            
        prices = [p[1] for p in self.price_history[symbol]]
        if len(prices) < 2:
            return None
            
        returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
        
        if len(returns) < 2:
            return None
            
        try:
            vol = stdev(returns)
            # Annualize (assuming ~1 second intervals, ~31.5M seconds/year)
            annualized = vol * (31536000 ** 0.5)
            return min(annualized, 5.0)  # Cap at 500% annual vol
        except:
            return None
            
    async def get_aggregated_price(self, symbol: str) -> Optional[AggregatedPrice]:
        """Get aggregated price with outlier detection and confidence metrics."""
        raw_prices = await self.fetch_all_prices(symbol)
        
        if not raw_prices:
            logger.warning(f"No prices available for {symbol}")
            return None
            
        # Detect and remove outliers
        valid_prices, outliers = self._detect_outliers(raw_prices)
        
        if not valid_prices:
            logger.warning(f"All prices were outliers for {symbol}")
            return None
            
        # Calculate metrics
        price_values = [float(p.price) for p in valid_prices]
        median_price = Decimal(str(round(median(price_values), 2)))
        vwap = self._calculate_vwap(valid_prices)
        
        # Use median as fair value (more robust than mean)
        fair_value = median_price
        
        # Best bid/ask across exchanges
        bids = [p.bid for p in valid_prices if p.bid and p.bid > 0]
        asks = [p.ask for p in valid_prices if p.ask and p.ask > 0]
        
        best_bid = max(bids) if bids else fair_value * Decimal('0.999')
        best_ask = min(asks) if asks else fair_value * Decimal('1.001')
        
        # Spread in basis points
        spread_bps = float((best_ask - best_bid) / fair_value * 10000)
        
        # Confidence: based on number of sources and their agreement
        if len(valid_prices) >= 4:
            try:
                price_std = stdev(price_values)
                agreement = 1.0 - min(price_std / float(median_price), 0.01) * 100
            except:
                agreement = 0.8
            confidence = min(1.0, 0.5 + 0.1 * len(valid_prices) + agreement * 0.3)
        else:
            confidence = 0.3 + 0.15 * len(valid_prices)
            
        # Update history and calculate volatility
        self._update_history(symbol, fair_value)
        volatility = self._calculate_volatility(symbol)
        
        return AggregatedPrice(
            symbol=symbol,
            fair_value=fair_value,
            median_price=median_price,
            vwap=vwap,
            best_bid=best_bid,
            best_ask=best_ask,
            spread_bps=spread_bps,
            num_sources=len(valid_prices),
            sources=[p.exchange for p in valid_prices],
            outliers_removed=outliers,
            confidence=confidence,
            volatility_1m=volatility
        )
        
    async def get_prices_for_all_coins(self) -> Dict[str, AggregatedPrice]:
        """Get aggregated prices for all supported coins."""
        coins = ["BTC", "ETH", "SOL", "DOGE"]
        tasks = [self.get_aggregated_price(coin) for coin in coins]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        prices = {}
        for coin, result in zip(coins, results):
            if isinstance(result, AggregatedPrice):
                prices[coin] = result
                
        return prices
        
    async def close(self):
        """Close all connections."""
        for conn in self.connectors.values():
            await conn.close()


# Singleton instance
_aggregator: Optional[CryptoAggregator] = None

def get_aggregator() -> CryptoAggregator:
    global _aggregator
    if _aggregator is None:
        _aggregator = CryptoAggregator()
    return _aggregator


async def test_aggregator():
    """Test the crypto aggregator."""
    print("=" * 60)
    print("CRYPTO PRICE AGGREGATOR TEST")
    print("=" * 60)
    
    aggregator = CryptoAggregator()
    
    for symbol in ["BTC", "ETH", "SOL", "DOGE"]:
        print(f"\n--- {symbol} ---")
        agg = await aggregator.get_aggregated_price(symbol)
        
        if agg:
            print(f"Fair Value: ${float(agg.fair_value):,.2f}")
            print(f"Median:     ${float(agg.median_price):,.2f}")
            print(f"VWAP:       ${float(agg.vwap):,.2f}")
            print(f"Bid/Ask:    ${float(agg.best_bid):,.2f} / ${float(agg.best_ask):,.2f}")
            print(f"Spread:     {agg.spread_bps:.1f} bps")
            print(f"Sources:    {agg.num_sources} ({', '.join(agg.sources)})")
            print(f"Confidence: {agg.confidence:.1%}")
            if agg.outliers_removed:
                print(f"Outliers:   {', '.join(agg.outliers_removed)}")
        else:
            print("No price available")
            
    await aggregator.close()
    print("\n" + "=" * 60)
    print("TEST COMPLETE")


if __name__ == "__main__":
    asyncio.run(test_aggregator())
