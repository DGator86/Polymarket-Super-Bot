"""
Core data models for the Polymarket hybrid bot.

All timestamps use MICROSECONDS (not milliseconds) for high-frequency trading.
"""
from dataclasses import dataclass, field
from typing import Optional, Literal
from datetime import datetime
from enum import Enum
from src.utils.timing import now_us


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class IntentMode(str, Enum):
    TAKER = "TAKER"
    MAKER = "MAKER"


@dataclass
class Market:
    """Market definition for a Polymarket binary outcome."""
    slug: str
    strike: Optional[float]  # Strike price for price-based markets
    expiry_ts: int  # Unix timestamp in seconds
    yes_token_id: str
    no_token_id: str
    tick_size: float = 0.01
    min_size: float = 1.0
    condition_id: Optional[str] = None

    def __post_init__(self):
        if self.tick_size <= 0:
            raise ValueError("tick_size must be positive")
        if self.min_size <= 0:
            raise ValueError("min_size must be positive")


@dataclass
class BookTop:
    """Top of book snapshot for a single token."""
    token_id: str
    bid_px: Optional[float]
    bid_sz: Optional[float]
    ask_px: Optional[float]
    ask_sz: Optional[float]
    ts: int  # Unix timestamp in MICROSECONDS (not milliseconds!)

    @property
    def mid(self) -> Optional[float]:
        """Return mid price if both sides exist."""
        if self.bid_px is not None and self.ask_px is not None:
            return (self.bid_px + self.ask_px) / 2
        return None

    @property
    def spread(self) -> Optional[float]:
        """Return spread in price units."""
        if self.bid_px is not None and self.ask_px is not None:
            return self.ask_px - self.bid_px
        return None

    @property
    def is_stale(self) -> bool:
        """Check if book data is stale (>2s old)."""
        now_microseconds = now_us()
        stale_threshold_us = 2_000_000  # 2 seconds in microseconds
        return (now_microseconds - self.ts) > stale_threshold_us

    @property
    def age_us(self) -> int:
        """Age of book data in microseconds."""
        return now_us() - self.ts

    @property
    def age_ms(self) -> int:
        """Age of book data in milliseconds."""
        return (now_us() - self.ts) // 1000


@dataclass
class RefPrice:
    """Reference spot price data."""
    symbol: str
    spot_mid: float
    r_1s: float  # 1-second return
    r_5s: float  # 5-second return
    vol_30s: float  # 30-second rolling volatility
    ts: int  # Unix timestamp in MICROSECONDS

    @property
    def is_stale(self) -> bool:
        """Check if reference price is stale (>2s old)."""
        now_microseconds = now_us()
        stale_threshold_us = 2_000_000  # 2 seconds
        return (now_microseconds - self.ts) > stale_threshold_us

    @property
    def age_us(self) -> int:
        """Age in microseconds."""
        return now_us() - self.ts


@dataclass
class Position:
    """Current position in a token."""
    token_id: str
    qty: float  # Positive = long, negative = short
    avg_cost: float  # Average cost basis
    realized_pnl: float = 0.0

    @property
    def notional(self) -> float:
        """Return absolute notional value."""
        return abs(self.qty * self.avg_cost)

    def unrealized_pnl(self, current_mid: float) -> float:
        """Calculate unrealized PnL at current mid price."""
        if self.qty == 0:
            return 0.0
        return self.qty * (current_mid - self.avg_cost)


@dataclass
class OpenOrder:
    """Open order on the CLOB."""
    order_id: str
    token_id: str
    side: Side
    price: float
    size: float
    filled_size: float = 0.0
    ts: int = field(default_factory=now_us)  # MICROSECONDS

    @property
    def remaining_size(self) -> float:
        """Remaining unfilled size."""
        return self.size - self.filled_size

    @property
    def age_us(self) -> int:
        """Age of order in microseconds."""
        return now_us() - self.ts

    @property
    def age_ms(self) -> int:
        """Age of order in milliseconds."""
        return self.age_us // 1000


@dataclass
class Intent:
    """Desired trading intent (before risk checks and execution)."""
    token_id: str
    side: Side
    price: float
    size: float
    mode: IntentMode
    ttl_us: int  # Time to live in MICROSECONDS
    reason: str  # Why this intent was created (for logging)
    created_ts: int = field(default_factory=now_us)  # MICROSECONDS

    def __post_init__(self):
        if self.size <= 0:
            raise ValueError("Intent size must be positive")
        if self.price <= 0 or self.price >= 1:
            raise ValueError("Intent price must be between 0 and 1")

    @property
    def is_expired(self) -> bool:
        """Check if intent has exceeded TTL."""
        return (now_us() - self.created_ts) > self.ttl_us

    @property
    def age_us(self) -> int:
        """Age in microseconds."""
        return now_us() - self.created_ts


@dataclass
class Fill:
    """Executed fill."""
    fill_id: str
    order_id: str
    token_id: str
    side: Side
    price: float
    size: float
    fee: float
    ts: int

    @property
    def notional(self) -> float:
        """Return notional value of fill."""
        return self.price * self.size


@dataclass
class RiskMetrics:
    """Aggregated risk metrics."""
    total_notional: float
    max_position_notional: float
    num_open_orders: int
    daily_pnl: float
    daily_taker_volume: float
    orders_last_minute: int
