"""
Market Maker + Fee-Aware Taker Engine

Combines:
1. Market making: quote both sides around fair value, collect spread
2. Taker: only cross spread when mispricing > fees + spread + buffer

Key principles:
- All decisions fee-adjusted (no "free edge" illusions)
- Inventory management via quote skewing
- Risk limits enforced at all levels
- Conservative by default (widen spreads, reduce size when uncertain)
"""
from __future__ import annotations
import asyncio
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone
from enum import Enum

from core.fee_model import (
    calculate_taker_fee, calculate_maker_fee,
    minimum_profitable_edge_taker, minimum_profitable_spread_maker
)
from core.orderbook import Orderbook, OrderbookManager
from core.digital_pricer import PricerOutput, price_15m_up_down, price_binary_above, PricerInput

logger = logging.getLogger(__name__)


class TradeAction(Enum):
    """Possible trading actions"""
    NONE = "none"
    BUY_YES = "buy_yes"
    SELL_YES = "sell_yes"
    BUY_NO = "buy_no"
    SELL_NO = "sell_no"
    QUOTE_BOTH = "quote_both"
    QUOTE_BID_ONLY = "quote_bid_only"
    QUOTE_ASK_ONLY = "quote_ask_only"


@dataclass
class TradingDecision:
    """A trading decision from the engine"""
    ticker: str
    action: TradeAction
    
    # For taker trades
    taker_side: Optional[str] = None  # "yes" or "no"
    taker_price_cents: int = 0
    taker_quantity: int = 0
    taker_edge_cents: Decimal = Decimal(0)
    
    # For maker quotes
    bid_price_cents: int = 0
    bid_quantity: int = 0
    ask_price_cents: int = 0
    ask_quantity: int = 0
    
    # Context
    fair_value_cents: int = 50
    market_bid_cents: int = 0
    market_ask_cents: int = 0
    spread_cents: int = 0
    
    reason: str = ""
    
    def __str__(self) -> str:
        if self.action == TradeAction.NONE:
            return f"{self.ticker}: NO ACTION - {self.reason}"
        elif "QUOTE" in self.action.value:
            return (f"{self.ticker}: {self.action.value} bid={self.bid_price_cents}c/{self.bid_quantity} "
                    f"ask={self.ask_price_cents}c/{self.ask_quantity} (fair={self.fair_value_cents}c)")
        else:
            return (f"{self.ticker}: {self.action.value} {self.taker_quantity}x @ {self.taker_price_cents}c "
                    f"(edge={self.taker_edge_cents}c, fair={self.fair_value_cents}c)")


@dataclass
class PositionState:
    """Current position in a market"""
    ticker: str
    yes_quantity: int = 0
    no_quantity: int = 0
    avg_entry_price_cents: int = 0
    
    @property
    def net_position(self) -> int:
        """Net YES exposure (positive = long YES, negative = short YES/long NO)"""
        return self.yes_quantity - self.no_quantity
    
    @property
    def is_flat(self) -> bool:
        return self.yes_quantity == 0 and self.no_quantity == 0


@dataclass
class RiskLimits:
    """Risk limits for the engine"""
    max_position_per_market: int = 100        # Max contracts per market
    max_daily_loss_cents: int = 5000          # 0 daily loss limit
    max_open_markets: int = 5                 # Max simultaneous positions
    max_correlated_exposure_pct: float = 0.25 # 25% max in correlated markets
    
    # Dynamic adjustments
    widen_spread_on_loss_pct: float = 0.02   # Widen spread 2% for each 1% loss
    reduce_size_on_vol_spike: float = 0.5    # Cut size in half on vol spike


class MMTakerEngine:
    """
    Combined Market Maker + Taker Engine
    
    Usage:
        engine = MMTakerEngine(book_manager)
        engine.set_fair_value("KXBTC15M-xxx", 50)  # Set fair value
        
        decision = engine.evaluate("KXBTC15M-xxx")
        if decision.action != TradeAction.NONE:
            # Execute the decision
    """
    
    def __init__(
        self,
        book_manager: OrderbookManager,
        risk_limits: RiskLimits = None,
        base_quote_size: int = 10,
        base_half_spread_cents: int = 2
    ):
        self.books = book_manager
        self.limits = risk_limits or RiskLimits()
        self.base_quote_size = base_quote_size
        self.base_half_spread = base_half_spread_cents
        
        # State
        self.fair_values: Dict[str, int] = {}  # ticker -> fair value in cents
        self.positions: Dict[str, PositionState] = {}
        self.daily_pnl_cents: int = 0
        
        # Mode controls
        self.maker_enabled: bool = True
        self.taker_enabled: bool = True
        self.is_killed: bool = False
        
    def set_fair_value(self, ticker: str, fair_cents: int) -> None:
        """Set fair value for a market"""
        self.fair_values[ticker] = max(1, min(99, fair_cents))
        
    def get_position(self, ticker: str) -> PositionState:
        if ticker not in self.positions:
            self.positions[ticker] = PositionState(ticker=ticker)
        return self.positions[ticker]
    
    def kill_switch(self, reason: str) -> None:
        """Emergency stop"""
        logger.critical(f"KILL SWITCH ACTIVATED: {reason}")
        self.is_killed = True
        self.maker_enabled = False
        self.taker_enabled = False
        
    def evaluate(self, ticker: str) -> TradingDecision:
        """
        Evaluate a market and return a trading decision.
        
        Decision priority:
        1. Check kill switch / risk limits
        2. Check for taker opportunity (mispricing)
        3. Generate maker quotes
        """
        # === Gate 1: Kill switch ===
        if self.is_killed:
            return TradingDecision(
                ticker=ticker,
                action=TradeAction.NONE,
                reason="Kill switch active"
            )
            
        # === Gate 2: Daily loss limit ===
        if self.daily_pnl_cents < -self.limits.max_daily_loss_cents:
            self.kill_switch(f"Daily loss limit hit: {self.daily_pnl_cents}c")
            return TradingDecision(
                ticker=ticker,
                action=TradeAction.NONE,
                reason="Daily loss limit"
            )
            
        # === Gate 3: Get book ===
        book = self.books.get_book(ticker)
        if not book or not book.is_valid:
            return TradingDecision(
                ticker=ticker,
                action=TradeAction.NONE,
                reason="No valid orderbook"
            )
            
        # === Gate 4: Get fair value ===
        fair = self.fair_values.get(ticker)
        if fair is None:
            return TradingDecision(
                ticker=ticker,
                action=TradeAction.NONE,
                reason="No fair value set"
            )
            
        # Get market state
        market_bid = book.best_yes_bid or 0
        market_ask = book.best_yes_ask or 100
        spread = market_ask - market_bid
        position = self.get_position(ticker)
        
        # === Check for taker opportunity ===
        if self.taker_enabled:
            taker_decision = self._evaluate_taker(
                ticker, fair, market_bid, market_ask, spread, position
            )
            if taker_decision.action != TradeAction.NONE:
                return taker_decision
                
        # === Generate maker quotes ===
        if self.maker_enabled:
            return self._generate_maker_quotes(
                ticker, fair, market_bid, market_ask, spread, position
            )
            
        return TradingDecision(
            ticker=ticker,
            action=TradeAction.NONE,
            reason="Both maker and taker disabled"
        )
    
    def _evaluate_taker(
        self,
        ticker: str,
        fair: int,
        market_bid: int,
        market_ask: int,
        spread: int,
        position: PositionState
    ) -> TradingDecision:
        """
        Check if there's a taker opportunity.
        
        Buy YES if: fair - market_ask > min_edge (market is cheap)
        Sell YES if: market_bid - fair > min_edge (market is expensive)
        """
        # Calculate minimum edge needed
        min_edge_buy = minimum_profitable_edge_taker(market_ask, self.base_quote_size)
        min_edge_sell = minimum_profitable_edge_taker(market_bid, self.base_quote_size)
        
        # Check BUY YES opportunity
        buy_edge = Decimal(fair - market_ask)
        if buy_edge > min_edge_buy:
            # Check position limit
            if position.net_position >= self.limits.max_position_per_market:
                return TradingDecision(
                    ticker=ticker,
                    action=TradeAction.NONE,
                    reason=f"Position limit (long): {position.net_position}"
                )
                
            quantity = min(
                self.base_quote_size,
                self.limits.max_position_per_market - position.net_position
            )
            
            return TradingDecision(
                ticker=ticker,
                action=TradeAction.BUY_YES,
                taker_side="yes",
                taker_price_cents=market_ask,
                taker_quantity=quantity,
                taker_edge_cents=buy_edge,
                fair_value_cents=fair,
                market_bid_cents=market_bid,
                market_ask_cents=market_ask,
                spread_cents=spread,
                reason=f"Cheap YES: edge={buy_edge}c > min={min_edge_buy}c"
            )
            
        # Check SELL YES (BUY NO) opportunity  
        sell_edge = Decimal(market_bid - fair)
        if sell_edge > min_edge_sell:
            # Check position limit
            if position.net_position <= -self.limits.max_position_per_market:
                return TradingDecision(
                    ticker=ticker,
                    action=TradeAction.NONE,
                    reason=f"Position limit (short): {position.net_position}"
                )
                
            quantity = min(
                self.base_quote_size,
                self.limits.max_position_per_market + position.net_position
            )
            
            return TradingDecision(
                ticker=ticker,
                action=TradeAction.BUY_NO,
                taker_side="no",
                taker_price_cents=100 - market_bid,  # NO price
                taker_quantity=quantity,
                taker_edge_cents=sell_edge,
                fair_value_cents=fair,
                market_bid_cents=market_bid,
                market_ask_cents=market_ask,
                spread_cents=spread,
                reason=f"Expensive YES: edge={sell_edge}c > min={min_edge_sell}c"
            )
            
        return TradingDecision(
            ticker=ticker,
            action=TradeAction.NONE,
            fair_value_cents=fair,
            market_bid_cents=market_bid,
            market_ask_cents=market_ask,
            spread_cents=spread,
            reason=f"No taker edge (buy:{buy_edge}c vs {min_edge_buy}c, sell:{sell_edge}c vs {min_edge_sell}c)"
        )
    
    def _generate_maker_quotes(
        self,
        ticker: str,
        fair: int,
        market_bid: int,
        market_ask: int,
        spread: int,
        position: PositionState
    ) -> TradingDecision:
        """
        Generate market maker quotes around fair value.
        
        Quote logic:
        1. Base spread = maker fee + adverse selection buffer
        2. Skew quotes based on inventory (lower bid if long, raise ask if short)
        3. Don't quote through the market
        """
        # Calculate minimum half-spread
        min_half_spread = int(minimum_profitable_spread_maker(fair, self.base_quote_size))
        half_spread = max(self.base_half_spread, min_half_spread)
        
        # Inventory skew: reduce exposure on the heavy side
        # If long YES, lower bid (less eager to buy more)
        # If long NO (short YES), raise ask (less eager to sell more)
        inventory_skew = 0
        if position.net_position != 0:
            # Skew by 1c per 10 contracts of inventory
            inventory_skew = position.net_position // 10
            
        # Calculate quote prices
        bid_price = fair - half_spread - inventory_skew
        ask_price = fair + half_spread - inventory_skew
        
        # Don't quote through the market (would be immediate taker)
        bid_price = min(bid_price, market_bid + 1) if market_bid > 0 else bid_price
        ask_price = max(ask_price, market_ask - 1) if market_ask < 100 else ask_price
        
        # Ensure valid prices
        bid_price = max(1, min(bid_price, 98))
        ask_price = max(2, min(ask_price, 99))
        
        # Ensure bid < ask
        if bid_price >= ask_price:
            # Market is too tight for us to quote profitably
            return TradingDecision(
                ticker=ticker,
                action=TradeAction.NONE,
                fair_value_cents=fair,
                market_bid_cents=market_bid,
                market_ask_cents=market_ask,
                spread_cents=spread,
                reason=f"Market too tight for maker (our spread would be {ask_price - bid_price}c)"
            )
            
        # Calculate quantities (reduce if near position limits)
        remaining_long_capacity = self.limits.max_position_per_market - position.net_position
        remaining_short_capacity = self.limits.max_position_per_market + position.net_position
        
        bid_qty = min(self.base_quote_size, remaining_long_capacity)
        ask_qty = min(self.base_quote_size, remaining_short_capacity)
        
        # Determine quote type
        if bid_qty <= 0 and ask_qty <= 0:
            action = TradeAction.NONE
            reason = "Position limits prevent quoting"
        elif bid_qty <= 0:
            action = TradeAction.QUOTE_ASK_ONLY
            reason = "Long position limit - ask only"
        elif ask_qty <= 0:
            action = TradeAction.QUOTE_BID_ONLY
            reason = "Short position limit - bid only"
        else:
            action = TradeAction.QUOTE_BOTH
            reason = f"Quoting around fair={fair}c with {half_spread}c half-spread"
            
        return TradingDecision(
            ticker=ticker,
            action=action,
            bid_price_cents=bid_price,
            bid_quantity=max(0, bid_qty),
            ask_price_cents=ask_price,
            ask_quantity=max(0, ask_qty),
            fair_value_cents=fair,
            market_bid_cents=market_bid,
            market_ask_cents=market_ask,
            spread_cents=spread,
            reason=reason
        )


if __name__ == "__main__":
    # Test the engine
    from core.orderbook import OrderbookManager
    
    print("=== MM+TAKER ENGINE TEST ===")
    
    # Set up book manager with test data
    books = OrderbookManager()
    books.on_snapshot(
        ticker="KXBTC15M-TEST",
        yes_bids=[[45, 100], [44, 200]],
        no_bids=[[52, 100], [53, 200]],  # YES ask = 48c, 47c
        seq=1
    )
    
    # Create engine
    engine = MMTakerEngine(
        book_manager=books,
        base_quote_size=10,
        base_half_spread_cents=2
    )
    
    book = books.get_book("KXBTC15M-TEST")
    print(f"\nMarket state: {book.summary()}")
    
    # Test 1: No fair value set
    print("\n1. No fair value set:")
    decision = engine.evaluate("KXBTC15M-TEST")
    print(f"   {decision}")
    
    # Test 2: Fair value at mid (no edge)
    engine.set_fair_value("KXBTC15M-TEST", 46)
    print("\n2. Fair=46c (at mid, no edge):")
    decision = engine.evaluate("KXBTC15M-TEST")
    print(f"   {decision}")
    
    # Test 3: Fair value below market (BUY opportunity)
    engine.set_fair_value("KXBTC15M-TEST", 52)  # Market ask is 48c, fair is 52c
    print("\n3. Fair=52c (market cheap, BUY edge):")
    decision = engine.evaluate("KXBTC15M-TEST")
    print(f"   {decision}")
    
    # Test 4: Fair value above market (SELL opportunity)
    engine.set_fair_value("KXBTC15M-TEST", 42)  # Market bid is 45c, fair is 42c
    print("\n4. Fair=42c (market expensive, SELL edge):")
    decision = engine.evaluate("KXBTC15M-TEST")
    print(f"   {decision}")
    
    # Test 5: With existing position (inventory skew)
    engine.set_fair_value("KXBTC15M-TEST", 46)
    engine.positions["KXBTC15M-TEST"] = PositionState(
        ticker="KXBTC15M-TEST",
        yes_quantity=50,  # Long 50 YES
        no_quantity=0
    )
    print("\n5. Fair=46c with +50 YES position (should skew quotes):")
    decision = engine.evaluate("KXBTC15M-TEST")
    print(f"   {decision}")
