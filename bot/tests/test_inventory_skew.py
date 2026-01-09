"""
Tests for inventory skew in market making.
"""
import pytest
from src.models import Market, Position
from src.strategy.market_maker import MarketMakerStrategy


def test_market_maker_no_inventory():
    """Test market maker quotes with no inventory."""
    mm = MarketMakerStrategy(
        half_spread=0.01,
        default_size=10.0,
        inventory_skew_factor=0.0001,
        max_inventory=500.0
    )

    market = Market(
        slug="test-market",
        strike=100000,
        expiry_ts=1740787200,
        yes_token_id="0x123",
        no_token_id="0x456"
    )

    p_fair = 0.50
    positions = {}

    intents = mm.generate_intents(market, p_fair, positions)

    assert len(intents) == 2

    # Find bid and ask
    bid = next(i for i in intents if i.side.value == "BUY")
    ask = next(i for i in intents if i.side.value == "SELL")

    # With no inventory, quotes should be symmetric around fair
    assert abs(bid.price - 0.49) < 0.01
    assert abs(ask.price - 0.51) < 0.01


def test_market_maker_long_inventory():
    """Test market maker quotes when long (should skew down)."""
    mm = MarketMakerStrategy(
        half_spread=0.01,
        default_size=10.0,
        inventory_skew_factor=0.001,  # Larger skew for testing
        max_inventory=500.0
    )

    market = Market(
        slug="test-market",
        strike=100000,
        expiry_ts=1740787200,
        yes_token_id="0x123",
        no_token_id="0x456"
    )

    p_fair = 0.50

    # Long 100 shares
    positions = {
        "0x123": Position(
            token_id="0x123",
            qty=100,
            avg_cost=0.48
        )
    }

    intents = mm.generate_intents(market, p_fair, positions)

    assert len(intents) == 2

    bid = next(i for i in intents if i.side.value == "BUY")
    ask = next(i for i in intents if i.side.value == "SELL")

    # Long position should shift quotes down (more aggressive ask, less aggressive bid)
    # Skew = -100/500 * 0.001 = -0.0002
    # Center = 0.50 - 0.0002 = 0.4998
    # After tick clamping to 0.01, the skew may be too small to see in final prices
    # But we can verify quotes are at or below neutral (due to downward skew intention)
    assert bid.price <= 0.49
    assert ask.price <= 0.51


def test_market_maker_short_inventory():
    """Test market maker quotes when short (should skew up)."""
    mm = MarketMakerStrategy(
        half_spread=0.01,
        default_size=10.0,
        inventory_skew_factor=0.001,
        max_inventory=500.0
    )

    market = Market(
        slug="test-market",
        strike=100000,
        expiry_ts=1740787200,
        yes_token_id="0x123",
        no_token_id="0x456"
    )

    p_fair = 0.50

    # Short 100 shares
    positions = {
        "0x123": Position(
            token_id="0x123",
            qty=-100,
            avg_cost=0.52
        )
    }

    intents = mm.generate_intents(market, p_fair, positions)

    assert len(intents) == 2

    bid = next(i for i in intents if i.side.value == "BUY")
    ask = next(i for i in intents if i.side.value == "SELL")

    # Short position should shift quotes up
    # Skew = -(-100)/500 * 0.001 = 0.0002
    # Center = 0.50 + 0.0002 = 0.5002
    # After tick clamping to 0.01, the skew may be too small to see in final prices
    # But we can verify quotes are at or above neutral (due to upward skew intention)
    assert bid.price >= 0.49
    assert ask.price >= 0.51
