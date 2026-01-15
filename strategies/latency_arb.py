"""
Latency Arbitrage Strategy

Exploits the delay between real-time crypto exchange prices and 
Kalshi market maker quote updates.

When BTC moves significantly on Coinbase but Kalshi MM quotes haven't
updated yet, this strategy:
1. Detects the divergence
2. Calculates fair value based on real-time price
3. Trades against stale Kalshi quotes
4. Captures the spread as profit when MM catches up

This is your existing strategy - integrated into the framework.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional, Dict, List, Callable, Awaitable
from dataclasses import dataclass
import re

from config import config
from core.models import (
    NormalizedMarket, TradingSignal, Side, SignalType,
    CryptoPrice, Venue, ArbitrageSignal
)
from connectors.kalshi import KalshiClient
from connectors.coinbase import CoinbaseClient

logger = logging.getLogger(__name__)


@dataclass
class CryptoMarketMatch:
    """A Kalshi market matched to a crypto price threshold"""
    ticker: str
    symbol: str         # BTC-USD, ETH-USD
    threshold: Decimal  # Price threshold
    is_above: bool      # True = "price > threshold", False = "price < threshold"
    expiry: datetime
    market: NormalizedMarket


@dataclass
class LatencySignal:
    """Signal from latency detection"""
    market: CryptoMarketMatch
    real_price: Decimal
    stale_quote_age_ms: int
    fair_value: Decimal      # Our estimate of true probability
    market_value: Decimal    # Current Kalshi mid
    edge: Decimal
    side: Side
    urgency: str  # "high", "medium", "low"


class LatencyArbStrategy:
    """
    Latency arbitrage on crypto-related Kalshi markets.
    
    Core insight: Kalshi market makers update quotes less frequently
    than crypto exchanges. When BTC moves 1-2% in seconds, the MM
    may take 500ms+ to update. We can trade in that window.
    
    Usage:
        strategy = LatencyArbStrategy(kalshi, coinbase)
        await strategy.run(on_signal_callback)
    """
    
    def __init__(
        self,
        kalshi_client: KalshiClient,
        coinbase_client: CoinbaseClient,
        min_divergence_pct: Decimal = None,
        stale_threshold_ms: int = None,
        symbols: tuple = None
    ):
        self.kalshi = kalshi_client
        self.coinbase = coinbase_client
        
        self.min_divergence = min_divergence_pct or config.latency_arb.min_price_divergence_pct
        self.stale_threshold_ms = stale_threshold_ms or config.latency_arb.stale_quote_threshold_ms
        self.symbols = symbols or config.latency_arb.crypto_symbols
        
        # State
        self._running = False
        self._crypto_markets: List[CryptoMarketMatch] = []
        self._last_prices: Dict[str, CryptoPrice] = {}
        self._last_kalshi_update: Dict[str, datetime] = {}
        
        # Callbacks
        self._on_signal: Optional[Callable[[LatencySignal], Awaitable[None]]] = None
    
    async def initialize(self):
        """Find Kalshi markets that reference crypto prices"""
        logger.info("Scanning for crypto-linked Kalshi markets...")
        
        markets = await self.kalshi.get_markets(status="open", limit=500)
        
        self._crypto_markets = []
        
        for raw in markets:
            question = raw.get("title", "") + " " + raw.get("subtitle", "")
            match = self._parse_crypto_market(question, raw)
            
            if match:
                # Get initial orderbook
                try:
                    orderbook = await self.kalshi.get_orderbook(match.ticker)
                    match.market = KalshiClient.normalize_market(raw, orderbook)
                    self._crypto_markets.append(match)
                except Exception as e:
                    logger.debug(f"Failed to get orderbook for {match.ticker}: {e}")
        
        logger.info(f"Found {len(self._crypto_markets)} crypto-linked markets")
        
        for m in self._crypto_markets[:5]:  # Log first 5
            logger.info(f"  {m.ticker}: {m.symbol} {'>' if m.is_above else '<'} ${m.threshold:,.0f}")
    
    def _parse_crypto_market(self, question: str, raw: dict) -> Optional[CryptoMarketMatch]:
        """Parse market question to extract crypto threshold info"""
        question_lower = question.lower()
        
        # Determine symbol
        symbol = None
        if "btc" in question_lower or "bitcoin" in question_lower:
            symbol = "BTC-USD"
        elif "eth" in question_lower or "ethereum" in question_lower:
            symbol = "ETH-USD"
        else:
            return None
        
        # Parse threshold price
        price_match = re.search(r'\$?([\d,]+(?:\.\d+)?)', question)
        if not price_match:
            return None
        
        try:
            threshold = Decimal(price_match.group(1).replace(",", ""))
        except:
            return None
        
        # Determine direction
        is_above = "above" in question_lower or ">" in question or "over" in question_lower
        
        # Parse expiry
        expiry_str = raw.get("expiration_time", raw.get("close_time", ""))
        try:
            expiry = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
        except:
            expiry = datetime.now(timezone.utc) + timedelta(days=1)
        
        return CryptoMarketMatch(
            ticker=raw.get("ticker", ""),
            symbol=symbol,
            threshold=threshold,
            is_above=is_above,
            expiry=expiry,
            market=None  # Filled in later
        )
    
    async def run(self, on_signal: Callable[[LatencySignal], Awaitable[None]]):
        """
        Main strategy loop.
        
        Streams real-time crypto prices and compares to Kalshi quotes.
        Fires callback when divergence detected.
        """
        if not self._crypto_markets:
            await self.initialize()
        
        if not self._crypto_markets:
            logger.warning("No crypto markets to monitor")
            return
        
        self._on_signal = on_signal
        self._running = True
        
        # Get unique symbols to monitor
        symbols = list(set(m.symbol for m in self._crypto_markets))
        
        logger.info(f"Starting latency arb monitoring for {symbols}")
        
        # Stream crypto prices
        await self.coinbase.stream_prices(symbols, self._on_crypto_price)
    
    async def _on_crypto_price(self, price: CryptoPrice):
        """Handle incoming crypto price update"""
        self._last_prices[price.symbol] = price
        
        # Check all markets for this symbol
        for match in self._crypto_markets:
            if match.symbol != price.symbol:
                continue
            
            await self._check_divergence(match, price)
    
    async def _check_divergence(self, match: CryptoMarketMatch, price: CryptoPrice):
        """Check if Kalshi quote is stale relative to crypto price"""
        
        # Calculate fair value based on current price
        fair_value = self._calculate_fair_value(match, price.price)
        
        # Get current Kalshi quote
        if not match.market:
            return
        
        market_mid = match.market.implied_prob_mid
        
        # Calculate divergence
        divergence = abs(fair_value - market_mid)
        
        if divergence < self.min_divergence:
            return  # Not enough edge
        
        # Estimate quote staleness
        last_update = self._last_kalshi_update.get(match.ticker)
        if last_update:
            staleness_ms = int((datetime.now(timezone.utc) - last_update).total_seconds() * 1000)
        else:
            staleness_ms = 1000  # Assume stale if no update seen
        
        # Determine side
        if fair_value > market_mid:
            side = Side.YES  # Fair value higher, buy YES
        else:
            side = Side.NO   # Fair value lower, buy NO
        
        # Create signal
        signal = LatencySignal(
            market=match,
            real_price=price.price,
            stale_quote_age_ms=staleness_ms,
            fair_value=fair_value,
            market_value=market_mid,
            edge=divergence,
            side=side,
            urgency="high" if staleness_ms > self.stale_threshold_ms else "medium"
        )
        
        logger.info(
            f"LATENCY SIGNAL: {match.ticker} | "
            f"{price.symbol}=${price.price:,.0f} | "
            f"Fair={fair_value:.1%} vs Market={market_mid:.1%} | "
            f"Edge={divergence:.1%} | Stale={staleness_ms}ms"
        )
        
        if self._on_signal:
            await self._on_signal(signal)
    
    def _calculate_fair_value(self, match: CryptoMarketMatch, current_price: Decimal) -> Decimal:
        """
        Calculate fair probability based on current crypto price.
        
        Simple model: linear interpolation around threshold with
        adjustments for time to expiry and volatility.
        """
        hours_to_expiry = (match.expiry - datetime.now(timezone.utc)).total_seconds() / 3600
        
        # Distance from threshold as percentage
        if match.threshold == 0:
            return Decimal("0.5")
        
        pct_from_threshold = (current_price - match.threshold) / match.threshold
        
        # Base probability from distance
        # If price is 2% above threshold, high prob of staying above
        # Adjust for volatility (~3% daily vol for BTC)
        
        vol_adjustment = Decimal("0.03") * Decimal(str((hours_to_expiry / 24) ** 0.5))
        
        if match.is_above:
            # Market is "price > threshold"
            if pct_from_threshold > 0:
                # Currently above threshold
                prob = Decimal("0.5") + (pct_from_threshold / vol_adjustment) * Decimal("0.25")
            else:
                # Currently below threshold
                prob = Decimal("0.5") + (pct_from_threshold / vol_adjustment) * Decimal("0.25")
        else:
            # Market is "price < threshold"
            if pct_from_threshold < 0:
                # Currently below threshold
                prob = Decimal("0.5") - (pct_from_threshold / vol_adjustment) * Decimal("0.25")
            else:
                # Currently above threshold
                prob = Decimal("0.5") - (pct_from_threshold / vol_adjustment) * Decimal("0.25")
        
        # Clamp to valid range
        return max(Decimal("0.05"), min(Decimal("0.95"), prob))
    
    async def refresh_kalshi_quotes(self):
        """Periodically refresh Kalshi orderbooks"""
        while self._running:
            for match in self._crypto_markets:
                try:
                    orderbook = await self.kalshi.get_orderbook(match.ticker)
                    raw = await self.kalshi.get_market(match.ticker)
                    match.market = KalshiClient.normalize_market(raw, orderbook)
                    self._last_kalshi_update[match.ticker] = datetime.now(timezone.utc)
                except Exception as e:
                    logger.debug(f"Failed to refresh {match.ticker}: {e}")
            
            await asyncio.sleep(0.5)  # Refresh every 500ms
    
    def stop(self):
        """Stop the strategy"""
        self._running = False


def signal_to_trading_signal(latency_signal: LatencySignal) -> TradingSignal:
    """Convert LatencySignal to standard TradingSignal"""
    import uuid
    
    return TradingSignal(
        signal_id=str(uuid.uuid4()),
        signal_type=SignalType.ARBITRAGE,
        ticker=latency_signal.market.ticker,
        venue=Venue.KALSHI,
        side=latency_signal.side,
        model_probability=latency_signal.fair_value,
        market_probability=latency_signal.market_value,
        confidence=Decimal("0.8"),  # High confidence in real-time price
        edge=latency_signal.edge,
        urgency=latency_signal.urgency,
        reason=f"Latency arb: {latency_signal.market.symbol} @ ${latency_signal.real_price:,.0f}",
        metadata={
            "crypto_price": float(latency_signal.real_price),
            "stale_ms": latency_signal.stale_quote_age_ms,
            "threshold": float(latency_signal.market.threshold)
        }
    )
