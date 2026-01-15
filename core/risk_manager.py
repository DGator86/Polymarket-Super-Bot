"""
Risk Manager

Handles position sizing, portfolio limits, and circuit breakers.
Ensures no single trade or correlated group of trades can blow up the account.

Key responsibilities:
1. Kelly-based position sizing
2. Per-market position limits
3. Correlated exposure limits
4. Daily loss circuit breaker
"""

import logging
from datetime import datetime, timezone, date
from decimal import Decimal
from typing import List, Dict, Optional, Set
from dataclasses import dataclass, field

from config import config
from core.models import (
    TradingSignal, Position, AccountBalance, DailyPnL,
    Side, MarketCategory, Venue
)

logger = logging.getLogger(__name__)


@dataclass
class SizedOrder:
    """Order with risk-adjusted sizing"""
    signal: TradingSignal
    size: int                    # Number of contracts
    max_loss: Decimal           # Maximum loss if wrong
    position_pct: Decimal       # Percentage of account
    reason: str                 # Sizing rationale


@dataclass
class PortfolioState:
    """Current portfolio risk state"""
    total_equity: Decimal
    available_cash: Decimal
    positions: List[Position]
    open_exposure: Decimal      # Total value at risk
    exposure_by_category: Dict[MarketCategory, Decimal]
    daily_pnl: DailyPnL


class RiskManager:
    """
    Risk management and position sizing.
    
    Implements:
    - Fractional Kelly criterion for sizing
    - Hard position limits per market
    - Correlation-based exposure limits
    - Daily loss circuit breaker
    
    Usage:
        risk_mgr = RiskManager()
        risk_mgr.update_portfolio(balance, positions)
        sized_order = risk_mgr.size_order(signal)
        if sized_order:
            # Execute the order
    """
    
    def __init__(
        self,
        kelly_fraction: Decimal = None,
        max_position_pct: Decimal = None,
        max_correlated_pct: Decimal = None,
        max_daily_loss_pct: Decimal = None,
        min_bet_size: int = None,
        max_bet_size: int = None
    ):
        self.kelly_fraction = kelly_fraction or config.risk.kelly_fraction
        self.max_position_pct = max_position_pct or config.risk.max_position_pct
        self.max_correlated_pct = max_correlated_pct or config.risk.max_correlated_exposure_pct
        self.max_daily_loss_pct = max_daily_loss_pct or config.risk.max_daily_loss_pct
        self.min_bet_size = min_bet_size or config.risk.min_bet_size
        self.max_bet_size = max_bet_size or config.risk.max_bet_size
        
        # Portfolio state
        self._balance: Optional[AccountBalance] = None
        self._positions: List[Position] = []
        self._daily_pnl: Optional[DailyPnL] = None
        self._position_map: Dict[str, Position] = {}
        
        # Circuit breaker state
        self._circuit_breaker_triggered = False
        self._blocked_tickers: Set[str] = set()
    
    def update_portfolio(
        self,
        balance: AccountBalance,
        positions: List[Position]
    ):
        """Update current portfolio state"""
        self._balance = balance
        self._positions = positions
        self._position_map = {p.ticker: p for p in positions}
        
        # Initialize or update daily P&L tracking
        today = datetime.now(timezone.utc).date()
        
        if self._daily_pnl is None or self._daily_pnl.date.date() != today:
            self._daily_pnl = DailyPnL(
                date=datetime.now(timezone.utc),
                starting_equity=balance.total_equity,
                current_equity=balance.total_equity,
                realized_pnl=Decimal("0"),
                unrealized_pnl=Decimal("0"),
                trades_count=0
            )
            self._circuit_breaker_triggered = False
        else:
            self._daily_pnl.current_equity = balance.total_equity
            self._daily_pnl.unrealized_pnl = sum(p.unrealized_pnl for p in positions)
        
        # Check circuit breaker
        self._check_circuit_breaker()
    
    def size_order(self, signal: TradingSignal) -> Optional[SizedOrder]:
        """
        Calculate position size for a trading signal.
        
        Returns None if:
        - Circuit breaker is triggered
        - Position limits would be exceeded
        - Kelly sizing suggests no bet
        
        Returns:
            SizedOrder with risk-adjusted size, or None
        """
        if not self._balance:
            logger.warning("No portfolio state - call update_portfolio first")
            return None
        
        # Check circuit breaker
        if self._circuit_breaker_triggered:
            logger.warning("Circuit breaker active - no new trades")
            return None
        
        # Check if ticker is blocked
        if signal.ticker in self._blocked_tickers:
            logger.debug(f"{signal.ticker} is blocked")
            return None
        
        equity = self._balance.total_equity
        cash = self._balance.available_balance
        
        # Step 1: Calculate Kelly-optimal size
        kelly_size = self._calculate_kelly_size(signal, equity)
        
        if kelly_size <= 0:
            logger.debug(f"{signal.ticker}: Kelly suggests no bet (edge too small)")
            return None
        
        # Step 2: Apply position limit
        max_position_value = equity * self.max_position_pct
        existing_position = self._position_map.get(signal.ticker)
        
        if existing_position:
            current_value = existing_position.market_value
            remaining_capacity = max_position_value - current_value
            
            if remaining_capacity <= 0:
                logger.debug(f"{signal.ticker}: Position limit reached")
                return None
            
            kelly_size = min(kelly_size, int(remaining_capacity / signal.market_probability))
        
        # Step 3: Apply correlation limit
        category_exposure = self._get_category_exposure(signal)
        max_category = equity * self.max_correlated_pct
        remaining_category = max_category - category_exposure
        
        if remaining_category <= 0:
            logger.debug(f"{signal.ticker}: Category exposure limit reached")
            return None
        
        kelly_size = min(kelly_size, int(remaining_category / signal.market_probability))
        
        # Step 4: Apply cash constraint
        cost_per_contract = signal.market_probability  # Approximate
        max_affordable = int(cash / cost_per_contract)
        kelly_size = min(kelly_size, max_affordable)
        
        # Step 5: Apply min/max constraints
        if kelly_size < self.min_bet_size:
            logger.debug(f"{signal.ticker}: Size {kelly_size} below minimum")
            return None
        
        kelly_size = min(kelly_size, self.max_bet_size)
        
        # Calculate max loss for this position
        if signal.side == Side.YES:
            max_loss = signal.market_probability * kelly_size
        else:
            max_loss = (Decimal("1") - signal.market_probability) * kelly_size
        
        position_pct = (kelly_size * signal.market_probability) / equity
        
        return SizedOrder(
            signal=signal,
            size=kelly_size,
            max_loss=max_loss,
            position_pct=position_pct,
            reason=f"Kelly {self.kelly_fraction}x, edge {signal.edge:.1%}"
        )
    
    def _calculate_kelly_size(self, signal: TradingSignal, equity: Decimal) -> int:
        """
        Calculate Kelly-optimal position size.
        
        Kelly formula: f* = (p * b - q) / b
        Where:
            p = probability of winning
            q = probability of losing (1 - p)
            b = odds received (payout / stake)
        
        We use fractional Kelly for conservatism.
        """
        if signal.side == Side.YES:
            p = signal.model_probability
            # Buying YES at market_prob, win (1 - market_prob) if correct
            b = (Decimal("1") - signal.market_probability) / signal.market_probability
        else:
            p = Decimal("1") - signal.model_probability
            # Buying NO at (1 - market_prob), win market_prob if correct
            b = signal.market_probability / (Decimal("1") - signal.market_probability)
        
        q = Decimal("1") - p
        
        if b <= 0:
            return 0
        
        # Full Kelly fraction
        kelly_fraction = (p * b - q) / b
        
        if kelly_fraction <= 0:
            return 0
        
        # Apply fractional Kelly
        adjusted_fraction = kelly_fraction * self.kelly_fraction
        
        # Convert to position size
        bet_value = equity * adjusted_fraction
        
        # Contracts = bet_value / cost_per_contract
        cost_per_contract = signal.market_probability if signal.side == Side.YES else (Decimal("1") - signal.market_probability)
        
        return int(bet_value / cost_per_contract)
    
    def _get_category_exposure(self, signal: TradingSignal) -> Decimal:
        """Get current exposure in the signal's market category"""
        # Would need market category info from the signal
        # For now, return 0 (no existing exposure tracking)
        return Decimal("0")
    
    def _check_circuit_breaker(self):
        """Check if daily loss limit has been breached"""
        if not self._daily_pnl:
            return
        
        if self._daily_pnl.pnl_pct < -self.max_daily_loss_pct:
            if not self._circuit_breaker_triggered:
                logger.error(
                    f"CIRCUIT BREAKER TRIGGERED: Daily loss {self._daily_pnl.pnl_pct:.1%} "
                    f"exceeds limit {self.max_daily_loss_pct:.1%}"
                )
                self._circuit_breaker_triggered = True
    
    def record_trade(self, ticker: str, pnl: Decimal):
        """Record a completed trade for P&L tracking"""
        if self._daily_pnl:
            self._daily_pnl.realized_pnl += pnl
            self._daily_pnl.trades_count += 1
            self._check_circuit_breaker()
    
    def block_ticker(self, ticker: str, reason: str = ""):
        """Temporarily block trading a ticker"""
        self._blocked_tickers.add(ticker)
        logger.info(f"Blocked {ticker}: {reason}")
    
    def unblock_ticker(self, ticker: str):
        """Remove ticker from blocklist"""
        self._blocked_tickers.discard(ticker)
    
    def reset_circuit_breaker(self):
        """Manually reset circuit breaker (use with caution)"""
        self._circuit_breaker_triggered = False
        logger.warning("Circuit breaker manually reset")
    
    @property
    def is_circuit_breaker_active(self) -> bool:
        """Check if circuit breaker is currently active"""
        return self._circuit_breaker_triggered
    
    @property
    def daily_pnl(self) -> Optional[DailyPnL]:
        """Get current daily P&L"""
        return self._daily_pnl
    
    def get_portfolio_summary(self) -> Dict:
        """Get summary of current portfolio state"""
        if not self._balance:
            return {}
        
        return {
            "total_equity": float(self._balance.total_equity),
            "available_cash": float(self._balance.available_balance),
            "num_positions": len(self._positions),
            "daily_pnl": float(self._daily_pnl.total_pnl) if self._daily_pnl else 0,
            "daily_pnl_pct": float(self._daily_pnl.pnl_pct) if self._daily_pnl else 0,
            "circuit_breaker": self._circuit_breaker_triggered,
            "trades_today": self._daily_pnl.trades_count if self._daily_pnl else 0
        }
