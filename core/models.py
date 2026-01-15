"""
Core data models for the Kalshi Prediction Bot.
Normalized schemas that work across all venues and data sources.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional, List, Dict, Any


# =============================================================================
# ENUMS
# =============================================================================

class Venue(Enum):
    """Supported trading venues"""
    KALSHI = "kalshi"
    POLYMARKET = "polymarket"
    PREDICTIT = "predictit"


class Side(Enum):
    """Order side"""
    YES = "yes"
    NO = "no"


class OrderType(Enum):
    """Order type"""
    LIMIT = "limit"
    MARKET = "market"


class OrderStatus(Enum):
    """Order lifecycle status"""
    PENDING = "pending"
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    REJECTED = "rejected"


class MarketCategory(Enum):
    """Market category for correlation grouping"""
    ECONOMICS = "economics"
    POLITICS = "politics"
    WEATHER = "weather"
    CRYPTO = "crypto"
    SPORTS = "sports"
    SCIENCE = "science"
    OTHER = "other"


class SignalType(Enum):
    """Signal source type"""
    MODEL = "model"           # Probability model output
    ARBITRAGE = "arbitrage"   # Cross-platform/latency arb
    NEWS = "news"             # Breaking news trigger


# =============================================================================
# MARKET DATA MODELS
# =============================================================================

@dataclass
class NormalizedMarket:
    """
    Venue-agnostic market representation.
    All strategies operate on this schema regardless of source.
    """
    venue: Venue
    ticker: str
    question: str
    category: MarketCategory
    expiry: datetime
    best_bid: Decimal
    best_ask: Decimal
    bid_size: int
    ask_size: int
    last_price: Optional[Decimal] = None
    volume_24h: Optional[int] = None
    open_interest: Optional[int] = None
    last_update: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    @property
    def implied_prob_mid(self) -> Decimal:
        """Mid-market implied probability"""
        return (self.best_bid + self.best_ask) / 2
    
    @property
    def spread(self) -> Decimal:
        """Bid-ask spread"""
        return self.best_ask - self.best_bid
    
    @property
    def spread_pct(self) -> Decimal:
        """Spread as percentage of mid"""
        mid = self.implied_prob_mid
        if mid == 0:
            return Decimal("1")
        return self.spread / mid
    
    @property
    def is_liquid(self) -> bool:
        """Quick liquidity check"""
        return self.bid_size >= 10 and self.ask_size >= 10


@dataclass
class OrderbookLevel:
    """Single price level in orderbook"""
    price: Decimal  # 0.01 to 0.99
    size: int       # Number of contracts


@dataclass
class Orderbook:
    """Full orderbook snapshot"""
    ticker: str
    venue: Venue
    bids: List[OrderbookLevel]  # Sorted descending by price
    asks: List[OrderbookLevel]  # Sorted ascending by price
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    @property
    def best_bid(self) -> Optional[OrderbookLevel]:
        return self.bids[0] if self.bids else None
    
    @property
    def best_ask(self) -> Optional[OrderbookLevel]:
        return self.asks[0] if self.asks else None
    
    @property
    def mid_price(self) -> Optional[Decimal]:
        if self.best_bid and self.best_ask:
            return (self.best_bid.price + self.best_ask.price) / 2
        return None


# =============================================================================
# ORDER MODELS
# =============================================================================

@dataclass
class OrderRequest:
    """Request to place an order"""
    ticker: str
    side: Side
    count: int                              # Number of contracts
    price: Optional[int] = None             # Price in cents (1-99), None for market
    order_type: OrderType = OrderType.LIMIT
    client_order_id: Optional[str] = None
    
    def __post_init__(self):
        if self.order_type == OrderType.LIMIT and self.price is None:
            raise ValueError("Limit orders require a price")
        if self.price is not None and not (1 <= self.price <= 99):
            raise ValueError(f"Price must be 1-99 cents, got {self.price}")
        if self.count < 1:
            raise ValueError(f"Count must be positive, got {self.count}")


@dataclass
class OrderResponse:
    """Response from order placement"""
    order_id: str
    ticker: str
    side: Side
    status: OrderStatus
    requested_count: int
    filled_count: int
    remaining_count: int
    price: Optional[int]                    # Limit price in cents
    avg_fill_price: Optional[Decimal]       # Average fill price as decimal
    created_at: datetime
    updated_at: datetime


@dataclass
class Position:
    """Current position in a market"""
    ticker: str
    venue: Venue
    side: Side
    quantity: int
    avg_entry_price: Decimal
    current_price: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal = Decimal("0")
    
    @property
    def market_value(self) -> Decimal:
        return Decimal(self.quantity) * self.current_price
    
    @property
    def total_pnl(self) -> Decimal:
        return self.unrealized_pnl + self.realized_pnl


# =============================================================================
# SIGNAL MODELS
# =============================================================================

@dataclass
class TradingSignal:
    """
    Output from strategy layer.
    Contains everything needed for risk manager to size and execute.
    """
    signal_id: str
    signal_type: SignalType
    ticker: str
    venue: Venue
    side: Side
    model_probability: Decimal              # Our estimated probability
    market_probability: Decimal             # Current market implied probability
    confidence: Decimal                     # 0-1, model confidence
    edge: Decimal                           # model_prob - market_prob (adjusted for side)
    urgency: str = "normal"                 # "high", "normal", "low"
    max_position: Optional[int] = None      # Strategy-suggested max size
    reason: str = ""                        # Human-readable explanation
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    @property
    def expected_value(self) -> Decimal:
        """Expected value per dollar risked"""
        if self.side == Side.YES:
            # Buying YES: pay market_prob, win (1 - market_prob) if correct
            win_amount = Decimal("1") - self.market_probability
            return (self.model_probability * win_amount) - ((1 - self.model_probability) * self.market_probability)
        else:
            # Buying NO: pay (1 - market_prob), win market_prob if correct
            win_amount = self.market_probability
            no_prob = Decimal("1") - self.model_probability
            return (no_prob * win_amount) - (self.model_probability * (1 - self.market_probability))


@dataclass
class ArbitrageSignal(TradingSignal):
    """Extended signal for arbitrage opportunities"""
    venue_a: Venue = Venue.KALSHI
    venue_b: Venue = Venue.POLYMARKET
    price_a: Decimal = Decimal("0")
    price_b: Decimal = Decimal("0")
    arb_profit_pct: Decimal = Decimal("0")


# =============================================================================
# EXTERNAL DATA MODELS
# =============================================================================

@dataclass
class EconomicDataPoint:
    """Single observation from economic data source"""
    series_id: str
    value: Decimal
    date: datetime
    source: str                             # "fred", "bls", "bea"
    units: str = ""
    notes: str = ""


@dataclass
class WeatherForecast:
    """Weather forecast for a location"""
    latitude: float
    longitude: float
    forecast_time: datetime
    temperature_f: Optional[float] = None
    precipitation_chance: Optional[float] = None
    wind_speed_mph: Optional[float] = None
    conditions: str = ""
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NewsItem:
    """News article or event"""
    title: str
    source: str
    published_at: datetime
    url: str
    content: str = ""
    relevance_score: float = 0.0
    keywords: List[str] = field(default_factory=list)


@dataclass
class CryptoPrice:
    """Real-time crypto price"""
    symbol: str                             # e.g., "BTC-USD"
    price: Decimal
    bid: Decimal
    ask: Decimal
    volume_24h: Decimal
    timestamp: datetime
    exchange: str = "coinbase"


# =============================================================================
# ACCOUNT MODELS
# =============================================================================

@dataclass
class AccountBalance:
    """Account balance summary"""
    venue: Venue
    available_balance: Decimal              # Cash available to trade
    portfolio_value: Decimal                # Total positions value
    total_equity: Decimal                   # available + portfolio
    pending_orders_value: Decimal = Decimal("0")
    margin_used: Decimal = Decimal("0")
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class DailyPnL:
    """Daily P&L tracking for circuit breaker"""
    date: datetime
    starting_equity: Decimal
    current_equity: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    trades_count: int = 0
    
    @property
    def total_pnl(self) -> Decimal:
        return self.realized_pnl + self.unrealized_pnl
    
    @property
    def pnl_pct(self) -> Decimal:
        if self.starting_equity == 0:
            return Decimal("0")
        return self.total_pnl / self.starting_equity
