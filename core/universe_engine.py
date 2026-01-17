"""
Universe Engine

Fast pre-filter that scans all available markets and eliminates those
that don't meet basic trading criteria. This prevents wasting computation
on illiquid, near-expiry, or wide-spread markets.

Runs before the expensive Probability Engine computations.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import List, Optional, Dict, Set, TYPE_CHECKING
from dataclasses import dataclass

from config import config
from core.models import NormalizedMarket, MarketCategory, Venue

if TYPE_CHECKING:
    from connectors.kalshi import KalshiClient

logger = logging.getLogger(__name__)


@dataclass
class FilterStats:
    """Statistics from filtering run"""
    total_markets: int
    passed_liquidity: int
    passed_spread: int
    passed_expiry: int
    final_count: int
    filter_time_ms: float


class UniverseEngine:
    """
    Market pre-filter for efficient opportunity scanning.
    
    Applies fast, cheap filters to eliminate markets before running
    expensive probability computations.
    
    Filter chain:
    1. Liquidity: Minimum $ available at best quotes
    2. Spread: Maximum bid-ask spread percentage
    3. Time to Expiry: Minimum hours until settlement
    4. Category (optional): Focus on specific market types
    
    Usage:
        engine = UniverseEngine(kalshi_client)
        tradeable = await engine.scan()
    """
    
    def __init__(
        self,
        kalshi_client: "KalshiClient",
        min_liquidity: Decimal = None,
        max_spread_pct: Decimal = None,
        min_expiry_hours: int = None,
        categories: List[MarketCategory] = None,
        max_markets: int = None
    ):
        self.kalshi = kalshi_client
        
        self.min_liquidity = min_liquidity or config.universe.min_liquidity_usd
        self.max_spread_pct = max_spread_pct or config.universe.max_spread_pct
        self.min_expiry_hours = min_expiry_hours or config.universe.min_time_to_expiry_hours
        self.max_markets = max_markets or config.universe.max_markets_to_analyze
        self.categories = categories
        
        self._last_scan_stats: Optional[FilterStats] = None
        self._blacklist: Set[str] = set()
    
    async def scan(self, force_refresh: bool = False) -> List[NormalizedMarket]:
        """
        Scan all markets and return those passing all filters.
        
        Returns:
            List of tradeable NormalizedMarket objects, sorted by liquidity
        """
        import time
        start = time.time()
        
        # Fetch markets from allowed series (connector handles allowlist)
        raw_markets = await self.kalshi.get_markets(status="open", limit=500)
        total = len(raw_markets)
        
        logger.info(f"Universe scan starting: {total} markets")
        
        candidates = []
        stats = {"passed_liquidity": 0, "passed_spread": 0, "passed_expiry": 0}
        
        for raw in raw_markets:
            # MVE filtering now handled by connector allowlist
            ticker = raw.get("ticker", "")
            
            if ticker in self._blacklist:
                continue
            
            try:
                orderbook = await self.kalshi.get_orderbook(ticker, depth=5)
            except Exception as e:
                logger.debug(f"Failed to get orderbook for {ticker}: {e}")
                continue
            
            # Import dynamically to avoid circular import
            from connectors.kalshi import KalshiClient as KClient
            market = KClient.normalize_market(raw, orderbook)
            
            # Filter 1: Liquidity (use market liquidity field OR orderbook liquidity)
            bid_value = market.best_bid * market.bid_size
            ask_value = (Decimal("1") - market.best_ask) * market.ask_size
            orderbook_liq = max(bid_value, ask_value)  # Use max for one-sided markets
            
            # Also check raw market liquidity field (Kalshi provides this)
            raw_liq = Decimal(str(raw.get("liquidity", 0)))
            effective_liq = max(orderbook_liq, raw_liq)
            
            if effective_liq < self.min_liquidity:
                continue
            stats["passed_liquidity"] += 1
            
            # Filter 2: Spread (skip for one-sided markets)
            # One-sided markets have very high calculated spread but are still tradeable
            if market.best_bid > 0 and market.best_ask < 1:
                # Two-sided market - check spread
                if market.spread_pct > self.max_spread_pct:
                    continue
            # For one-sided markets, just check that there is some orderbook activity
            elif market.bid_size == 0 and market.ask_size == 0:
                continue
            stats["passed_spread"] += 1
            
            # Filter 3: Time to Expiry
            now = datetime.now(timezone.utc)
            hours_to_expiry = (market.expiry - now).total_seconds() / 3600
            
            if hours_to_expiry < self.min_expiry_hours:
                continue
            stats["passed_expiry"] += 1
            
            # Filter 4: Category (optional)
            if self.categories and market.category not in self.categories:
                continue
            
            candidates.append(market)
            
            if len(candidates) >= self.max_markets:
                break
        
        # Sort by liquidity (most liquid first)
        candidates.sort(
            key=lambda m: min(m.best_bid * m.bid_size, (1 - m.best_ask) * m.ask_size),
            reverse=True
        )
        
        elapsed_ms = (time.time() - start) * 1000
        
        self._last_scan_stats = FilterStats(
            total_markets=total,
            passed_liquidity=stats["passed_liquidity"],
            passed_spread=stats["passed_spread"],
            passed_expiry=stats["passed_expiry"],
            final_count=len(candidates),
            filter_time_ms=elapsed_ms
        )
        
        logger.info(
            f"Universe scan complete: {len(candidates)}/{total} markets passed "
            f"({elapsed_ms:.0f}ms)"
        )
        
        return candidates
    
    def blacklist_ticker(self, ticker: str):
        """Add ticker to blacklist (skip in future scans)"""
        self._blacklist.add(ticker)
    
    def clear_blacklist(self):
        """Clear all blacklisted tickers"""
        self._blacklist.clear()
    
    @property
    def last_stats(self) -> Optional[FilterStats]:
        """Get statistics from last scan"""
        return self._last_scan_stats
