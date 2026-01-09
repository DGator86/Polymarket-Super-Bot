"""
Risk limit definitions and exceptions.
"""
from dataclasses import dataclass
from typing import Optional


class RiskException(Exception):
    """Base exception for risk violations."""
    pass


class NotionalLimitExceeded(RiskException):
    """Notional limit exceeded."""
    pass


class InventoryLimitExceeded(RiskException):
    """Inventory limit exceeded."""
    pass


class OrderLimitExceeded(RiskException):
    """Open order limit exceeded."""
    pass


class RateLimitExceeded(RiskException):
    """Rate limit exceeded."""
    pass


class DailyLossLimitExceeded(RiskException):
    """Daily loss limit exceeded."""
    pass


class KillSwitchActive(RiskException):
    """Kill switch is active."""
    pass


class FeedStale(RiskException):
    """Market feed is stale."""
    pass


@dataclass
class RiskLimits:
    """Risk limits configuration."""
    max_notional_per_market: float
    max_inventory_per_token: float
    max_open_orders_total: int
    max_orders_per_min: int
    max_daily_loss: float
    max_taker_slippage: float
    feed_stale_ms: int

    def __post_init__(self):
        """Validate limits."""
        if self.max_notional_per_market <= 0:
            raise ValueError("max_notional_per_market must be positive")
        if self.max_inventory_per_token <= 0:
            raise ValueError("max_inventory_per_token must be positive")
        if self.max_open_orders_total <= 0:
            raise ValueError("max_open_orders_total must be positive")
        if self.max_orders_per_min <= 0:
            raise ValueError("max_orders_per_min must be positive")
