"""
Tests for risk engine.
"""
import pytest
from src.models import Intent, Position, OpenOrder, Side, IntentMode
from src.risk.limits import (
    RiskLimits,
    NotionalLimitExceeded,
    InventoryLimitExceeded,
    OrderLimitExceeded,
    RateLimitExceeded,
    KillSwitchActive
)
from src.risk.kill_switch import KillSwitch
from src.risk.risk_engine import RiskEngine


def test_inventory_limit():
    """Test inventory limit enforcement."""
    limits = RiskLimits(
        max_notional_per_market=1000.0,
        max_inventory_per_token=100.0,
        max_open_orders_total=10,
        max_orders_per_min=30,
        max_daily_loss=50.0,
        max_taker_slippage=0.02,
        feed_stale_ms=2000
    )

    kill_switch = KillSwitch()
    risk_engine = RiskEngine(limits, kill_switch)

    # Current position: long 90
    positions = {
        "0x123": Position(
            token_id="0x123",
            qty=90,
            avg_cost=0.50
        )
    }

    # Intent to buy 20 more would exceed limit (90 + 20 = 110 > 100)
    intent = Intent(
        token_id="0x123",
        side=Side.BUY,
        price=0.52,
        size=20,
        mode=IntentMode.MAKER,
        ttl_ms=3000,
        reason="test"
    )

    with pytest.raises(InventoryLimitExceeded):
        risk_engine.check_intent(intent, positions, [], 0.52)


def test_inventory_limit_pass():
    """Test inventory limit allows valid trades."""
    limits = RiskLimits(
        max_notional_per_market=1000.0,
        max_inventory_per_token=100.0,
        max_open_orders_total=10,
        max_orders_per_min=30,
        max_daily_loss=50.0,
        max_taker_slippage=0.02,
        feed_stale_ms=2000
    )

    kill_switch = KillSwitch()
    risk_engine = RiskEngine(limits, kill_switch)

    positions = {
        "0x123": Position(
            token_id="0x123",
            qty=90,
            avg_cost=0.50
        )
    }

    # Intent to buy 5 more is OK (90 + 5 = 95 < 100)
    intent = Intent(
        token_id="0x123",
        side=Side.BUY,
        price=0.52,
        size=5,
        mode=IntentMode.MAKER,
        ttl_ms=3000,
        reason="test"
    )

    # Should not raise
    risk_engine.check_intent(intent, positions, [], 0.52)


def test_notional_limit():
    """Test notional limit enforcement."""
    limits = RiskLimits(
        max_notional_per_market=100.0,  # Low limit
        max_inventory_per_token=1000.0,
        max_open_orders_total=10,
        max_orders_per_min=30,
        max_daily_loss=50.0,
        max_taker_slippage=0.02,
        feed_stale_ms=2000
    )

    kill_switch = KillSwitch()
    risk_engine = RiskEngine(limits, kill_switch)

    positions = {
        "0x123": Position(
            token_id="0x123",
            qty=100,
            avg_cost=0.50
        )
    }

    # Intent to buy 100 more at 0.80 would exceed notional
    # New qty = 200, notional = 200 * 0.80 = 160 > 100
    intent = Intent(
        token_id="0x123",
        side=Side.BUY,
        price=0.80,
        size=100,
        mode=IntentMode.MAKER,
        ttl_ms=3000,
        reason="test"
    )

    with pytest.raises(NotionalLimitExceeded):
        risk_engine.check_intent(intent, positions, [], 0.80)


def test_order_limit():
    """Test open order limit enforcement."""
    limits = RiskLimits(
        max_notional_per_market=1000.0,
        max_inventory_per_token=1000.0,
        max_open_orders_total=2,  # Low limit
        max_orders_per_min=30,
        max_daily_loss=50.0,
        max_taker_slippage=0.02,
        feed_stale_ms=2000
    )

    kill_switch = KillSwitch()
    risk_engine = RiskEngine(limits, kill_switch)

    # Already have 2 open orders
    open_orders = [
        OpenOrder("order1", "0x123", Side.BUY, 0.49, 10),
        OpenOrder("order2", "0x123", Side.SELL, 0.51, 10)
    ]

    intent = Intent(
        token_id="0x456",
        side=Side.BUY,
        price=0.50,
        size=10,
        mode=IntentMode.MAKER,
        ttl_ms=3000,
        reason="test"
    )

    with pytest.raises(OrderLimitExceeded):
        risk_engine.check_intent(intent, {}, open_orders, 0.50)


def test_kill_switch():
    """Test kill switch blocks all trading."""
    limits = RiskLimits(
        max_notional_per_market=1000.0,
        max_inventory_per_token=1000.0,
        max_open_orders_total=10,
        max_orders_per_min=30,
        max_daily_loss=50.0,
        max_taker_slippage=0.02,
        feed_stale_ms=2000
    )

    kill_switch = KillSwitch()
    risk_engine = RiskEngine(limits, kill_switch)

    # Activate kill switch
    kill_switch.activate("Test activation")

    intent = Intent(
        token_id="0x123",
        side=Side.BUY,
        price=0.50,
        size=10,
        mode=IntentMode.MAKER,
        ttl_ms=3000,
        reason="test"
    )

    with pytest.raises(KillSwitchActive):
        risk_engine.check_intent(intent, {}, [], 0.50)


def test_rate_limit():
    """Test rate limiting."""
    limits = RiskLimits(
        max_notional_per_market=1000.0,
        max_inventory_per_token=1000.0,
        max_open_orders_total=100,
        max_orders_per_min=2,  # Very low limit for testing
        max_daily_loss=50.0,
        max_taker_slippage=0.02,
        feed_stale_ms=2000
    )

    kill_switch = KillSwitch()
    risk_engine = RiskEngine(limits, kill_switch)

    intent = Intent(
        token_id="0x123",
        side=Side.BUY,
        price=0.50,
        size=10,
        mode=IntentMode.MAKER,
        ttl_ms=3000,
        reason="test"
    )

    # First two orders should pass
    risk_engine.check_intent(intent, {}, [], 0.50)
    risk_engine.record_order()

    risk_engine.check_intent(intent, {}, [], 0.50)
    risk_engine.record_order()

    # Third should fail rate limit
    with pytest.raises(RateLimitExceeded):
        risk_engine.check_intent(intent, {}, [], 0.50)
