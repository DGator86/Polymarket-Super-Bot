"""
Digital Option Pricer for Kalshi Hourly Markets

Kalshi hourly markets are essentially digital/binary options:
- "BTC price at 6am EST >= $85,500" pays $1 if true, $0 otherwise
- "BTC price in range [K1, K2]" pays $1 if in range

Critical insight from Kalshi docs:
Settlement uses CF Benchmarks Real-Time Index with a 60-SECOND WINDOW
of per-second observations (often averaged). This is NOT a single tick!

Pricing approach:
1. Use lognormal model for short-term price distribution
2. Inflate volatility slightly to account for 60s averaging uncertainty
3. Add basis risk buffer if your price feed differs from CF RTI

For 15-minute Up/Down markets:
- These are P(price goes up in 15 min)
- With μ≈0, this is roughly 50% + signal adjustments
"""
from __future__ import annotations
import math
from decimal import Decimal
from dataclasses import dataclass
from typing import Optional, Tuple
from scipy.stats import norm
from datetime import datetime, timedelta
import numpy as np


@dataclass
class PricerInput:
    """Input parameters for pricing"""
    current_price: float      # Current spot price (e.g., BTC at 95000)
    strike: float             # Strike price for binary (e.g., 95500)
    time_to_expiry_hours: float  # Time to expiry in hours
    volatility: float         # Annualized volatility (e.g., 0.50 for 50%)
    drift: float = 0.0        # Expected drift (usually 0 for short horizons)
    
    # Settlement adjustments
    settlement_window_seconds: int = 60  # CF Benchmarks uses 60s window
    basis_risk_buffer: float = 0.01     # Buffer for price feed differences


@dataclass
class PricerOutput:
    """Output from pricing calculation"""
    fair_value: float          # Probability in [0, 1]
    fair_value_cents: int      # Fair value in cents [0, 100]
    confidence_interval: Tuple[float, float]  # 95% CI for fair value
    
    # For trading decisions
    d2: float                  # Black-Scholes d2 parameter
    effective_vol: float       # Vol used after adjustments
    
    def __str__(self) -> str:
        return (f"Fair: {self.fair_value_cents}c ({self.fair_value:.3f}) "
                f"[{self.confidence_interval[0]:.3f}, {self.confidence_interval[1]:.3f}]")


def estimate_realized_vol(returns: list, annualize: bool = True) -> float:
    """
    Estimate realized volatility from returns.
    
    Args:
        returns: List of log returns (e.g., 1-minute returns)
        annualize: Whether to annualize (assumes 252 trading days, 24h)
    
    Returns:
        Volatility (annualized if requested)
    """
    if len(returns) < 2:
        return 0.5  # Default to 50% annualized vol
        
    std = np.std(returns)
    
    if annualize:
        # Assuming 1-minute returns: 525600 minutes/year
        # Or approximate: sqrt(252 * 24 * 60) ≈ 610
        std *= math.sqrt(525600)
        
    return float(std)


def price_binary_above(input: PricerInput) -> PricerOutput:
    """
    Price a binary option: pays $1 if S_T >= K, else $0.
    
    This is P(S_T >= K) under risk-neutral measure.
    For very short horizons (< 1 day), we use P-measure (real probability).
    
    Using Black-Scholes framework:
    P(S_T >= K) = Φ(d2)
    where d2 = [ln(S/K) + (μ - σ²/2)T] / (σ√T)
    """
    S = input.current_price
    K = input.strike
    T = input.time_to_expiry_hours / (365 * 24)  # Convert to years
    mu = input.drift
    
    # Adjust volatility for settlement averaging
    # The 60-second average has lower variance than a single tick
    # But we ADD uncertainty because we're not sure of exact settlement mechanics
    vol_adjustment = 1.0 + (input.settlement_window_seconds / 3600) * 0.1
    sigma = input.volatility * vol_adjustment
    
    # Add basis risk buffer
    sigma += input.basis_risk_buffer
    
    if T <= 0 or sigma <= 0:
        # Already expired or invalid
        return PricerOutput(
            fair_value=1.0 if S >= K else 0.0,
            fair_value_cents=100 if S >= K else 0,
            confidence_interval=(0.0, 1.0),
            d2=0.0,
            effective_vol=sigma
        )
    
    # Calculate d2
    d2 = (math.log(S / K) + (mu - 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    
    # Probability of finishing above strike
    prob = norm.cdf(d2)
    
    # Confidence interval (using delta approximation)
    # Standard error of probability estimate scales with sqrt(T) and vol uncertainty
    vol_uncertainty = 0.1  # 10% uncertainty in vol estimate
    prob_se = norm.pdf(d2) * sigma * math.sqrt(T) * vol_uncertainty / (sigma * math.sqrt(T))
    prob_se = min(prob_se, 0.15)  # Cap at 15%
    
    ci_low = max(0, prob - 1.96 * prob_se)
    ci_high = min(1, prob + 1.96 * prob_se)
    
    return PricerOutput(
        fair_value=prob,
        fair_value_cents=int(round(prob * 100)),
        confidence_interval=(ci_low, ci_high),
        d2=d2,
        effective_vol=sigma
    )


def price_binary_below(input: PricerInput) -> PricerOutput:
    """Price a binary option: pays $1 if S_T < K"""
    above = price_binary_above(input)
    return PricerOutput(
        fair_value=1 - above.fair_value,
        fair_value_cents=100 - above.fair_value_cents,
        confidence_interval=(1 - above.confidence_interval[1], 1 - above.confidence_interval[0]),
        d2=-above.d2,
        effective_vol=above.effective_vol
    )


def price_binary_range(
    current_price: float,
    lower_strike: float,
    upper_strike: float,
    time_to_expiry_hours: float,
    volatility: float,
    drift: float = 0.0
) -> PricerOutput:
    """
    Price a binary option: pays $1 if K1 <= S_T < K2.
    
    P(K1 <= S_T < K2) = P(S_T >= K1) - P(S_T >= K2)
    """
    input_lower = PricerInput(
        current_price=current_price,
        strike=lower_strike,
        time_to_expiry_hours=time_to_expiry_hours,
        volatility=volatility,
        drift=drift
    )
    
    input_upper = PricerInput(
        current_price=current_price,
        strike=upper_strike,
        time_to_expiry_hours=time_to_expiry_hours,
        volatility=volatility,
        drift=drift
    )
    
    above_lower = price_binary_above(input_lower)
    above_upper = price_binary_above(input_upper)
    
    prob = above_lower.fair_value - above_upper.fair_value
    
    return PricerOutput(
        fair_value=max(0, prob),
        fair_value_cents=max(0, int(round(prob * 100))),
        confidence_interval=(
            max(0, above_lower.confidence_interval[0] - above_upper.confidence_interval[1]),
            min(1, above_lower.confidence_interval[1] - above_upper.confidence_interval[0])
        ),
        d2=above_lower.d2,
        effective_vol=above_lower.effective_vol
    )


def price_15m_up_down(
    current_price: float,
    volatility: float,
    orderbook_imbalance: float = 0.0,
    recent_return_z: float = 0.0
) -> PricerOutput:
    """
    Price a 15-minute Up/Down market.
    
    These are essentially P(price goes up in 15 minutes).
    With μ≈0, this is roughly 50%, but we can adjust for:
    - Orderbook imbalance (bid vs ask pressure)
    - Recent momentum (z-score of last 1-5 minute returns)
    
    Args:
        current_price: Current spot price
        volatility: Annualized volatility
        orderbook_imbalance: (bid_qty - ask_qty) / (bid_qty + ask_qty), in [-1, 1]
        recent_return_z: Z-score of recent returns (positive = trending up)
    
    Returns:
        Fair value for YES (price goes up)
    """
    # Base probability is 50%
    base_prob = 0.5
    
    # Adjust for orderbook imbalance (weak signal, capped at ±3%)
    imbalance_adjustment = orderbook_imbalance * 0.03
    
    # Adjust for momentum (stronger signal, capped at ±5%)
    momentum_adjustment = np.clip(recent_return_z * 0.02, -0.05, 0.05)
    
    # Combined fair value
    fair = base_prob + imbalance_adjustment + momentum_adjustment
    fair = np.clip(fair, 0.05, 0.95)  # Never go extreme
    
    # Confidence interval is wide for these short-term markets
    ci_width = 0.10  # ±10%
    
    return PricerOutput(
        fair_value=fair,
        fair_value_cents=int(round(fair * 100)),
        confidence_interval=(fair - ci_width, fair + ci_width),
        d2=0.0,  # Not applicable
        effective_vol=volatility
    )


if __name__ == "__main__":
    print("=== DIGITAL OPTION PRICER TESTS ===")
    
    # Test 1: BTC hourly strike market
    print("\n1. BTC hourly: Price >= $95,500 (current: $95,000, 30min to expiry)")
    input1 = PricerInput(
        current_price=95000,
        strike=95500,
        time_to_expiry_hours=0.5,
        volatility=0.50  # 50% annualized vol
    )
    result1 = price_binary_above(input1)
    print(f"   {result1}")
    
    # Test 2: Same but in the money
    print("\n2. BTC hourly: Price >= $94,500 (current: $95,000, 30min to expiry)")
    input2 = PricerInput(
        current_price=95000,
        strike=94500,
        time_to_expiry_hours=0.5,
        volatility=0.50
    )
    result2 = price_binary_above(input2)
    print(f"   {result2}")
    
    # Test 3: Range market
    print("\n3. BTC hourly: Price in [$94,500, $95,500] (current: $95,000, 30min to expiry)")
    result3 = price_binary_range(
        current_price=95000,
        lower_strike=94500,
        upper_strike=95500,
        time_to_expiry_hours=0.5,
        volatility=0.50
    )
    print(f"   {result3}")
    
    # Test 4: 15-minute up/down
    print("\n4. BTC 15m Up/Down (neutral conditions)")
    result4 = price_15m_up_down(
        current_price=95000,
        volatility=0.50,
        orderbook_imbalance=0.0,
        recent_return_z=0.0
    )
    print(f"   {result4}")
    
    # Test 5: 15-minute up/down with bullish signals
    print("\n5. BTC 15m Up/Down (bullish: imbalance=+0.3, momentum z=+1.5)")
    result5 = price_15m_up_down(
        current_price=95000,
        volatility=0.50,
        orderbook_imbalance=0.3,
        recent_return_z=1.5
    )
    print(f"   {result5}")
    
    # Test 6: Compare different volatilities
    print("\n6. Volatility sensitivity (Strike $96,000, Current $95,000, 1hr)")
    for vol in [0.3, 0.5, 0.7, 1.0]:
        inp = PricerInput(
            current_price=95000,
            strike=96000,
            time_to_expiry_hours=1.0,
            volatility=vol
        )
        res = price_binary_above(inp)
        print(f"   Vol={vol:.0%}: {res.fair_value_cents}c")
