"""
Risk engine - enforces all risk limits.
"""
from typing import Dict, List
from collections import deque
from datetime import datetime
from src.models import Intent, Position, OpenOrder, RiskMetrics
from src.risk.limits import (
    RiskLimits,
    NotionalLimitExceeded,
    InventoryLimitExceeded,
    OrderLimitExceeded,
    RateLimitExceeded,
    DailyLossLimitExceeded,
    KillSwitchActive
)
from src.risk.kill_switch import KillSwitch
from src.logging_setup import get_logger

logger = get_logger("risk_engine")


class RiskEngine:
    """
    Risk management engine.

    Enforces:
    - Position limits per token
    - Notional limits per market
    - Open order limits
    - Rate limits (orders per minute)
    - Daily loss limits
    - Kill switch
    """

    def __init__(self, limits: RiskLimits, kill_switch: KillSwitch):
        """
        Initialize risk engine.

        Args:
            limits: Risk limits configuration
            kill_switch: Kill switch instance
        """
        self.limits = limits
        self.kill_switch = kill_switch
        self._order_timestamps: deque = deque()  # Timestamps of recent orders
        self._daily_pnl: float = 0.0
        self._daily_pnl_reset_ts: int = 0
        logger.info("Risk engine initialized")

    def check_intent(
        self,
        intent: Intent,
        positions: Dict[str, Position],
        open_orders: List[OpenOrder],
        current_mid: float
    ) -> None:
        """
        Check if intent passes risk limits.

        Args:
            intent: Intended trade
            positions: Current positions
            open_orders: Current open orders
            current_mid: Current mid price for intent token

        Raises:
            RiskException: If any limit is violated
        """
        # Check kill switch first
        if self.kill_switch.is_active():
            raise KillSwitchActive("Kill switch is active, no trading allowed")

        # Check inventory limit
        self._check_inventory_limit(intent, positions)

        # Check notional limit
        self._check_notional_limit(intent, positions, current_mid)

        # Check open order limit
        self._check_order_limit(open_orders)

        # Check rate limit
        self._check_rate_limit()

        # Check daily loss limit
        self._check_daily_loss_limit()

        logger.debug(f"Intent passed risk checks: {intent.side} {intent.size} {intent.token_id} @ {intent.price}")

    def _check_inventory_limit(
        self,
        intent: Intent,
        positions: Dict[str, Position]
    ) -> None:
        """Check if intent would exceed inventory limit."""
        position = positions.get(intent.token_id, Position(
            token_id=intent.token_id,
            qty=0.0,
            avg_cost=0.0
        ))

        # Calculate new position after intent
        if intent.side.value == "BUY":
            new_qty = position.qty + intent.size
        else:
            new_qty = position.qty - intent.size

        # Check absolute inventory
        if abs(new_qty) > self.limits.max_inventory_per_token:
            raise InventoryLimitExceeded(
                f"Intent would exceed inventory limit: current={position.qty:.1f}, "
                f"intent={intent.side} {intent.size:.1f}, "
                f"new={new_qty:.1f}, limit={self.limits.max_inventory_per_token:.1f}"
            )

    def _check_notional_limit(
        self,
        intent: Intent,
        positions: Dict[str, Position],
        current_mid: float
    ) -> None:
        """Check if intent would exceed notional limit."""
        position = positions.get(intent.token_id, Position(
            token_id=intent.token_id,
            qty=0.0,
            avg_cost=0.0
        ))

        # Calculate new position notional
        if intent.side.value == "BUY":
            new_qty = position.qty + intent.size
        else:
            new_qty = position.qty - intent.size

        new_notional = abs(new_qty * current_mid)

        if new_notional > self.limits.max_notional_per_market:
            raise NotionalLimitExceeded(
                f"Intent would exceed notional limit: current_notional={position.notional:.2f}, "
                f"new_notional={new_notional:.2f}, limit={self.limits.max_notional_per_market:.2f}"
            )

    def _check_order_limit(self, open_orders: List[OpenOrder]) -> None:
        """Check if we're at open order limit."""
        num_open = len(open_orders)
        if num_open >= self.limits.max_open_orders_total:
            raise OrderLimitExceeded(
                f"Open order limit reached: {num_open}/{self.limits.max_open_orders_total}"
            )

    def _check_rate_limit(self) -> None:
        """Check if we're exceeding order rate limit."""
        now_ms = int(datetime.now().timestamp() * 1000)
        cutoff_ms = now_ms - 60000  # 1 minute ago

        # Remove timestamps older than 1 minute
        while self._order_timestamps and self._order_timestamps[0] < cutoff_ms:
            self._order_timestamps.popleft()

        # Check count
        if len(self._order_timestamps) >= self.limits.max_orders_per_min:
            raise RateLimitExceeded(
                f"Rate limit exceeded: {len(self._order_timestamps)} orders in last minute, "
                f"limit={self.limits.max_orders_per_min}"
            )

    def _check_daily_loss_limit(self) -> None:
        """Check if daily loss limit is exceeded."""
        # Reset daily PnL at midnight
        now_ts = int(datetime.now().timestamp())
        day_start = (now_ts // 86400) * 86400

        if self._daily_pnl_reset_ts < day_start:
            self._daily_pnl = 0.0
            self._daily_pnl_reset_ts = day_start
            logger.info("Daily PnL reset")

        # Check loss limit
        if self._daily_pnl < -self.limits.max_daily_loss:
            raise DailyLossLimitExceeded(
                f"Daily loss limit exceeded: {self._daily_pnl:.2f} < -{self.limits.max_daily_loss:.2f}"
            )

    def record_order(self) -> None:
        """Record that an order was placed (for rate limiting)."""
        now_ms = int(datetime.now().timestamp() * 1000)
        self._order_timestamps.append(now_ms)

    def update_daily_pnl(self, pnl_delta: float) -> None:
        """
        Update daily PnL.

        Args:
            pnl_delta: Change in PnL (positive = profit, negative = loss)
        """
        self._daily_pnl += pnl_delta
        logger.info(f"Daily PnL updated: {self._daily_pnl:.2f} (delta={pnl_delta:.2f})")

        # Check if we've hit loss limit and activate kill switch
        if self._daily_pnl < -self.limits.max_daily_loss:
            self.kill_switch.activate(f"Daily loss limit exceeded: {self._daily_pnl:.2f}")

    def get_metrics(
        self,
        positions: Dict[str, Position],
        open_orders: List[OpenOrder],
        current_mids: Dict[str, float]
    ) -> RiskMetrics:
        """
        Get current risk metrics.

        Args:
            positions: Current positions
            open_orders: Current open orders
            current_mids: Current mid prices by token_id

        Returns:
            RiskMetrics snapshot
        """
        total_notional = sum(
            abs(pos.qty * current_mids.get(token_id, pos.avg_cost))
            for token_id, pos in positions.items()
        )

        max_position_notional = max(
            (abs(pos.qty * current_mids.get(token_id, pos.avg_cost))
             for token_id, pos in positions.items()),
            default=0.0
        )

        # Count orders in last minute
        now_ms = int(datetime.now().timestamp() * 1000)
        cutoff_ms = now_ms - 60000
        orders_last_minute = sum(1 for ts in self._order_timestamps if ts >= cutoff_ms)

        return RiskMetrics(
            total_notional=total_notional,
            max_position_notional=max_position_notional,
            num_open_orders=len(open_orders),
            daily_pnl=self._daily_pnl,
            daily_taker_volume=0.0,  # TODO: track this separately
            orders_last_minute=orders_last_minute
        )
