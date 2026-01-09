"""
Tests for fair price calculation.
"""
import pytest
from src.models import Market, RefPrice
from src.strategy.fair_price import (
    FairPriceCalculator,
    normal_cdf,
    clamp_to_tick,
    calculate_inventory_skew
)


def test_normal_cdf():
    """Test normal CDF approximation."""
    # Test at known points
    assert abs(normal_cdf(0.0) - 0.5) < 0.01  # Mean
    assert abs(normal_cdf(-3.0) - 0.00135) < 0.001  # -3 sigma
    assert abs(normal_cdf(3.0) - 0.99865) < 0.001  # +3 sigma
    assert abs(normal_cdf(1.0) - 0.8413) < 0.01  # +1 sigma


def test_clamp_to_tick():
    """Test tick clamping."""
    assert clamp_to_tick(0.523, 0.01) == 0.52
    assert clamp_to_tick(0.527, 0.01) == 0.53
    assert clamp_to_tick(0.999, 0.01) == 0.99
    assert clamp_to_tick(0.001, 0.01) == 0.01


def test_inventory_skew():
    """Test inventory skew calculation."""
    # Long position should give negative skew (shift down)
    skew_long = calculate_inventory_skew(
        position_qty=100,
        max_inventory=500,
        skew_factor=0.0001
    )
    assert skew_long < 0

    # Short position should give positive skew (shift up)
    skew_short = calculate_inventory_skew(
        position_qty=-100,
        max_inventory=500,
        skew_factor=0.0001
    )
    assert skew_short > 0

    # Zero position should give zero skew
    skew_zero = calculate_inventory_skew(
        position_qty=0,
        max_inventory=500,
        skew_factor=0.0001
    )
    assert skew_zero == 0.0


def test_fair_price_calculator_above_strike():
    """Test fair price when spot is above strike."""
    calc = FairPriceCalculator(sigma_floor=0.001, use_normal_cdf=True)

    market = Market(
        slug="btc-above-100k",
        strike=100000,
        expiry_ts=1740787200,  # Some future date
        yes_token_id="0x123",
        no_token_id="0x456"
    )

    ref_price = RefPrice(
        symbol="BTCUSDT",
        spot_mid=105000,  # 5% above strike
        r_1s=0.0,
        r_5s=0.0,
        vol_30s=0.5,  # 50% annualized vol
        ts=1700000000000
    )

    current_ts = 1700000000  # Some current time before expiry

    p_fair = calc.calculate_fair_prob(market, ref_price, current_ts)

    # Spot above strike should give p > 0.5
    assert p_fair is not None
    assert p_fair > 0.5
    assert 0.0 < p_fair < 1.0


def test_fair_price_calculator_below_strike():
    """Test fair price when spot is below strike."""
    calc = FairPriceCalculator(sigma_floor=0.001, use_normal_cdf=True)

    market = Market(
        slug="btc-above-100k",
        strike=100000,
        expiry_ts=1740787200,
        yes_token_id="0x123",
        no_token_id="0x456"
    )

    ref_price = RefPrice(
        symbol="BTCUSDT",
        spot_mid=95000,  # 5% below strike
        r_1s=0.0,
        r_5s=0.0,
        vol_30s=0.5,
        ts=1700000000000
    )

    current_ts = 1700000000

    p_fair = calc.calculate_fair_prob(market, ref_price, current_ts)

    # Spot below strike should give p < 0.5
    assert p_fair is not None
    assert p_fair < 0.5
    assert 0.0 < p_fair < 1.0


def test_fair_price_calculator_logistic():
    """Test fair price with logistic function."""
    calc = FairPriceCalculator(sigma_floor=0.001, use_normal_cdf=False)

    market = Market(
        slug="btc-above-100k",
        strike=100000,
        expiry_ts=1740787200,
        yes_token_id="0x123",
        no_token_id="0x456"
    )

    ref_price = RefPrice(
        symbol="BTCUSDT",
        spot_mid=105000,
        r_1s=0.0,
        r_5s=0.0,
        vol_30s=0.5,
        ts=1700000000000
    )

    current_ts = 1700000000

    p_fair = calc.calculate_fair_prob(market, ref_price, current_ts)

    # Should still give reasonable probability
    assert p_fair is not None
    assert 0.0 < p_fair < 1.0


def test_fair_price_edge_calculation():
    """Test edge calculation."""
    calc = FairPriceCalculator()

    p_fair = 0.60
    p_market = 0.55

    edge = calc.calculate_edge(p_fair, p_market)

    # Fair > market means positive edge (YES underpriced)
    assert abs(edge - 0.05) < 0.0001  # Floating point tolerance

    p_fair = 0.45
    p_market = 0.50

    edge = calc.calculate_edge(p_fair, p_market)

    # Fair < market means negative edge (YES overpriced)
    assert abs(edge - (-0.05)) < 0.0001  # Floating point tolerance
