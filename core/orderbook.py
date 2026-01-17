"""
Kalshi WebSocket Orderbook Manager

Critical understanding from Kalshi docs:
- Orderbook is BID-ONLY because YES bid @ X == NO ask @ (100-X)
- You receive orderbook_snapshot first, then orderbook_delta updates
- If you miss deltas, your book is WRONG - must resync

This implements proper book maintenance with:
- Snapshot initialization
- Delta application
- Automatic resync on inconsistency
- Best bid/ask extraction with proper YES/NO conversion
"""
from __future__ import annotations
import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional, Callable, Tuple
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class PriceLevel:
    """A single price level in the book"""
    price_cents: int
    quantity: int
    
    
@dataclass
class OrderbookSide:
    """One side of the orderbook (YES bids or NO bids)"""
    # price_cents -> quantity
    levels: Dict[int, int] = field(default_factory=dict)
    
    def update_level(self, price_cents: int, quantity: int) -> None:
        """Update a price level (quantity=0 removes it)"""
        if quantity <= 0:
            self.levels.pop(price_cents, None)
        else:
            self.levels[price_cents] = quantity
            
    def best_price(self, is_bid: bool = True) -> Optional[int]:
        """Get best price (highest for bids, lowest for asks)"""
        if not self.levels:
            return None
        return max(self.levels.keys()) if is_bid else min(self.levels.keys())
    
    def best_quantity(self, is_bid: bool = True) -> int:
        """Get quantity at best price"""
        best = self.best_price(is_bid)
        return self.levels.get(best, 0) if best else 0
    
    def depth(self, levels: int = 5) -> List[Tuple[int, int]]:
        """Get top N levels as [(price, qty), ...] sorted best first"""
        sorted_prices = sorted(self.levels.keys(), reverse=True)  # Bids: highest first
        return [(p, self.levels[p]) for p in sorted_prices[:levels]]
    
    def total_quantity(self) -> int:
        """Total quantity across all levels"""
        return sum(self.levels.values())
    
    def clear(self) -> None:
        self.levels.clear()


@dataclass  
class Orderbook:
    """
    Complete orderbook for a Kalshi market.
    
    CRITICAL: Kalshi only sends YES side bids.
    - YES bid @ 40c = someone willing to buy YES @ 40c
    - To get YES ask: look at NO bids and convert (NO bid @ 60c = YES ask @ 40c)
    
    We maintain both YES and NO bids from the stream, then derive:
    - yes_bid = best YES bid price
    - yes_ask = 100 - best NO bid price (the implied YES ask)
    """
    ticker: str
    yes_bids: OrderbookSide = field(default_factory=OrderbookSide)
    no_bids: OrderbookSide = field(default_factory=OrderbookSide)
    
    last_snapshot_seq: int = 0
    last_delta_seq: int = 0
    last_update_time: float = 0
    is_valid: bool = False
    
    def apply_snapshot(self, yes_bids: List[List[int]], no_bids: List[List[int]], seq: int) -> None:
        """
        Apply a full orderbook snapshot.
        
        Format: [[price_cents, quantity], ...]
        """
        self.yes_bids.clear()
        self.no_bids.clear()
        
        for price, qty in yes_bids:
            self.yes_bids.update_level(price, qty)
            
        for price, qty in no_bids:
            self.no_bids.update_level(price, qty)
            
        self.last_snapshot_seq = seq
        self.last_delta_seq = seq
        self.last_update_time = time.time()
        self.is_valid = True
        
        logger.debug(f"{self.ticker}: Snapshot applied (seq={seq}, {len(self.yes_bids.levels)} yes levels, {len(self.no_bids.levels)} no levels)")
        
    def apply_delta(self, side: str, price_cents: int, quantity: int, seq: int) -> bool:
        """
        Apply an orderbook delta update.
        
        Returns False if sequence is out of order (need resync).
        """
        if seq <= self.last_delta_seq:
            # Already processed or old
            return True
            
        if seq > self.last_delta_seq + 1:
            # Missed deltas - need resync
            logger.warning(f"{self.ticker}: Missed deltas (expected {self.last_delta_seq + 1}, got {seq})")
            self.is_valid = False
            return False
            
        if side == "yes":
            self.yes_bids.update_level(price_cents, quantity)
        elif side == "no":
            self.no_bids.update_level(price_cents, quantity)
        else:
            logger.warning(f"{self.ticker}: Unknown side '{side}'")
            
        self.last_delta_seq = seq
        self.last_update_time = time.time()
        return True
    
    # === Derived prices (the key insight) ===
    
    @property
    def best_yes_bid(self) -> Optional[int]:
        """Best price someone will pay for YES"""
        return self.yes_bids.best_price(is_bid=True)
    
    @property
    def best_yes_ask(self) -> Optional[int]:
        """
        Best price you can buy YES at.
        
        This is derived from NO bids:
        - If someone bids 60c for NO, they're implicitly offering YES @ 40c
        - YES ask = 100 - best NO bid
        """
        best_no_bid = self.no_bids.best_price(is_bid=True)
        if best_no_bid is None:
            return None
        return 100 - best_no_bid
    
    @property
    def best_no_bid(self) -> Optional[int]:
        """Best price someone will pay for NO"""
        return self.no_bids.best_price(is_bid=True)
    
    @property
    def best_no_ask(self) -> Optional[int]:
        """
        Best price you can buy NO at.
        NO ask = 100 - best YES bid
        """
        best_yes_bid = self.yes_bids.best_price(is_bid=True)
        if best_yes_bid is None:
            return None
        return 100 - best_yes_bid
    
    @property
    def spread_cents(self) -> Optional[int]:
        """YES bid-ask spread in cents"""
        bid = self.best_yes_bid
        ask = self.best_yes_ask
        if bid is None or ask is None:
            return None
        return ask - bid
    
    @property
    def mid_price(self) -> Optional[Decimal]:
        """Midpoint of YES bid/ask in cents"""
        bid = self.best_yes_bid
        ask = self.best_yes_ask
        if bid is None or ask is None:
            return None
        return Decimal(bid + ask) / 2
    
    @property
    def best_yes_bid_size(self) -> int:
        return self.yes_bids.best_quantity(is_bid=True)
    
    @property
    def best_yes_ask_size(self) -> int:
        """Size at best YES ask (which is actually NO bid size)"""
        best_no_bid = self.no_bids.best_price(is_bid=True)
        return self.no_bids.levels.get(best_no_bid, 0) if best_no_bid else 0
    
    def is_stale(self, max_age_seconds: float = 5.0) -> bool:
        """Check if book is stale (no updates recently)"""
        return time.time() - self.last_update_time > max_age_seconds
    
    def summary(self) -> str:
        """Human-readable summary"""
        bid = self.best_yes_bid or 0
        ask = self.best_yes_ask or 100
        spread = self.spread_cents or 0
        return f"{self.ticker}: {bid}c / {ask}c (spread: {spread}c, valid: {self.is_valid})"


class OrderbookManager:
    """
    Manages orderbooks for multiple markets.
    
    Usage:
        manager = OrderbookManager()
        manager.on_snapshot(ticker, yes_bids, no_bids, seq)
        manager.on_delta(ticker, side, price, qty, seq)
        
        book = manager.get_book(ticker)
        if book and book.is_valid:
            print(f"YES bid/ask: {book.best_yes_bid}/{book.best_yes_ask}")
    """
    
    def __init__(self):
        self.books: Dict[str, Orderbook] = {}
        self._callbacks: List[Callable] = []
        
    def get_book(self, ticker: str) -> Optional[Orderbook]:
        return self.books.get(ticker)
        
    def get_or_create_book(self, ticker: str) -> Orderbook:
        if ticker not in self.books:
            self.books[ticker] = Orderbook(ticker=ticker)
        return self.books[ticker]
    
    def on_snapshot(self, ticker: str, yes_bids: List, no_bids: List, seq: int) -> None:
        """Handle orderbook_snapshot message"""
        book = self.get_or_create_book(ticker)
        book.apply_snapshot(yes_bids, no_bids, seq)
        self._notify_callbacks(ticker, "snapshot")
        
    def on_delta(self, ticker: str, side: str, price: int, qty: int, seq: int) -> bool:
        """
        Handle orderbook_delta message.
        Returns False if resync needed.
        """
        book = self.get_or_create_book(ticker)
        success = book.apply_delta(side, price, qty, seq)
        
        if success:
            self._notify_callbacks(ticker, "delta")
        else:
            self._notify_callbacks(ticker, "resync_needed")
            
        return success
    
    def add_callback(self, callback: Callable) -> None:
        """Add callback for book updates: callback(ticker, event_type)"""
        self._callbacks.append(callback)
        
    def _notify_callbacks(self, ticker: str, event_type: str) -> None:
        for cb in self._callbacks:
            try:
                cb(ticker, event_type)
            except Exception as e:
                logger.error(f"Callback error: {e}")
                
    def get_valid_books(self) -> List[Orderbook]:
        """Get all valid, non-stale orderbooks"""
        return [b for b in self.books.values() if b.is_valid and not b.is_stale()]
    
    def needs_resync(self) -> List[str]:
        """Get tickers that need resubscription"""
        return [t for t, b in self.books.items() if not b.is_valid or b.is_stale()]
    
    def summary(self) -> str:
        """Summary of all books"""
        lines = ["=== ORDERBOOK SUMMARY ==="]
        for ticker, book in sorted(self.books.items()):
            lines.append(f"  {book.summary()}")
        return "\n".join(lines)


if __name__ == "__main__":
    # Test the orderbook
    manager = OrderbookManager()
    
    # Simulate a snapshot
    manager.on_snapshot(
        ticker="KXBTC15M-TEST",
        yes_bids=[[40, 100], [39, 200], [38, 150]],  # YES bids
        no_bids=[[55, 80], [56, 120], [57, 90]],     # NO bids (implies YES asks)
        seq=1
    )
    
    book = manager.get_book("KXBTC15M-TEST")
    print(f"After snapshot:")
    print(f"  Best YES bid: {book.best_yes_bid}c (size: {book.best_yes_bid_size})")
    print(f"  Best YES ask: {book.best_yes_ask}c (size: {book.best_yes_ask_size})")
    print(f"  Spread: {book.spread_cents}c")
    print(f"  Mid: {book.mid_price}c")
    
    # Simulate deltas
    manager.on_delta("KXBTC15M-TEST", "yes", 41, 50, seq=2)  # New YES bid @ 41c
    print(f"\nAfter delta (new YES bid @ 41c):")
    print(f"  Best YES bid: {book.best_yes_bid}c")
    print(f"  Spread: {book.spread_cents}c")
    
    manager.on_delta("KXBTC15M-TEST", "no", 54, 100, seq=3)  # New NO bid @ 54c = YES ask @ 46c
    print(f"\nAfter delta (new NO bid @ 54c = YES ask @ 46c):")
    print(f"  Best YES ask: {book.best_yes_ask}c")
    print(f"  Spread: {book.spread_cents}c")
    
    print(f"\n{book.summary()}")
