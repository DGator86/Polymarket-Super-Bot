"""
Kalshi Fee Model

Kalshi uses a parabolic fee structure that peaks at 50c (mid-probability).
This is critical for determining when edge is real vs illusory.

Fee formulas (per Kalshi docs):
- Taker fee: ceil_to_cent(0.07 * C * P * (1-P))
- Maker fee: ceil_to_cent(0.0175 * C * P * (1-P))

Where:
- P = price in dollars (0.50 = 50c)
- C = number of contracts
"""
from __future__ import annotations
import math
from decimal import Decimal, ROUND_UP
from dataclasses import dataclass
from typing import Optional

# Fee rate constants (from Kalshi fee schedule)
TAKER_FEE_RATE = Decimal("0.07")
MAKER_FEE_RATE = Decimal("0.0175")

# Minimum fee per contract (1 cent minimum)
MIN_FEE_CENTS = 1


@dataclass
class FeeBreakdown:
    """Complete fee breakdown for a trade"""
    contracts: int
    price_cents: int
    is_maker: bool
    
    # Computed fees
    fee_per_contract_cents: Decimal
    total_fee_cents: Decimal
    
    # For edge calculations
    fee_as_price_impact: Decimal  # Fee expressed as price movement needed to break even
    
    def __str__(self) -> str:
        role = "maker" if self.is_maker else "taker"
        return (f"FeeBreakdown({self.contracts}x @ {self.price_cents}c {role}): "
                f"{self.total_fee_cents}c total, {self.fee_as_price_impact:.2f}c/contract impact")


def ceil_to_cent(value: Decimal) -> int:
    """Round up to nearest cent (Kalshi uses ceiling)"""
    return int(value.quantize(Decimal("1"), rounding=ROUND_UP))


def compute_fee_factor(price_cents: int) -> Decimal:
    """
    Compute P * (1-P) factor where P is price in dollars.
    This is the parabolic curve that peaks at 50c.
    
    Examples:
    - 50c: 0.50 * 0.50 = 0.25 (maximum)
    - 20c: 0.20 * 0.80 = 0.16
    - 90c: 0.90 * 0.10 = 0.09
    - 5c:  0.05 * 0.95 = 0.0475
    """
    p = Decimal(price_cents) / Decimal(100)
    return p * (Decimal(1) - p)


def calculate_taker_fee(contracts: int, price_cents: int) -> FeeBreakdown:
    """
    Calculate taker fee for crossing the spread.
    
    Formula: ceil(0.07 * C * P * (1-P))
    """
    if contracts <= 0 or price_cents <= 0 or price_cents >= 100:
        return FeeBreakdown(
            contracts=contracts,
            price_cents=price_cents,
            is_maker=False,
            fee_per_contract_cents=Decimal(0),
            total_fee_cents=Decimal(0),
            fee_as_price_impact=Decimal(0)
        )
    
    fee_factor = compute_fee_factor(price_cents)
    raw_fee = TAKER_FEE_RATE * Decimal(contracts) * fee_factor
    total_fee = max(ceil_to_cent(raw_fee), MIN_FEE_CENTS * contracts)
    
    fee_per_contract = Decimal(total_fee) / Decimal(contracts)
    fee_impact = fee_per_contract  # In cents, this IS the price impact
    
    return FeeBreakdown(
        contracts=contracts,
        price_cents=price_cents,
        is_maker=False,
        fee_per_contract_cents=fee_per_contract,
        total_fee_cents=Decimal(total_fee),
        fee_as_price_impact=fee_impact
    )


def calculate_maker_fee(contracts: int, price_cents: int) -> FeeBreakdown:
    """
    Calculate maker fee for providing liquidity.
    
    Formula: ceil(0.0175 * C * P * (1-P))
    """
    if contracts <= 0 or price_cents <= 0 or price_cents >= 100:
        return FeeBreakdown(
            contracts=contracts,
            price_cents=price_cents,
            is_maker=True,
            fee_per_contract_cents=Decimal(0),
            total_fee_cents=Decimal(0),
            fee_as_price_impact=Decimal(0)
        )
    
    fee_factor = compute_fee_factor(price_cents)
    raw_fee = MAKER_FEE_RATE * Decimal(contracts) * fee_factor
    total_fee = max(ceil_to_cent(raw_fee), MIN_FEE_CENTS * contracts)
    
    fee_per_contract = Decimal(total_fee) / Decimal(contracts)
    fee_impact = fee_per_contract
    
    return FeeBreakdown(
        contracts=contracts,
        price_cents=price_cents,
        is_maker=True,
        fee_per_contract_cents=fee_per_contract,
        total_fee_cents=Decimal(total_fee),
        fee_as_price_impact=fee_impact
    )


def minimum_profitable_edge_taker(price_cents: int, contracts: int = 1) -> Decimal:
    """
    Calculate minimum edge needed for a taker trade to be profitable.
    
    Returns edge in cents - price must deviate by at least this much
    from fair value for a taker trade to be +EV after fees.
    """
    fee = calculate_taker_fee(contracts, price_cents)
    # Add 0.5c safety buffer for slippage
    return fee.fee_as_price_impact + Decimal("0.5")


def minimum_profitable_spread_maker(price_cents: int, contracts: int = 1) -> Decimal:
    """
    Calculate minimum half-spread needed for market making to be profitable.
    
    Returns cents - bid/ask must be at least this far from fair value.
    """
    fee = calculate_maker_fee(contracts, price_cents)
    # Add buffer for adverse selection risk
    adverse_selection_buffer = Decimal("0.5")
    return fee.fee_as_price_impact + adverse_selection_buffer


def breakeven_table():
    """Generate a breakeven table showing fees at different price points"""
    print("\n=== KALSHI FEE BREAKEVEN TABLE (10 contracts) ===")
    print(f"{'Price':>6} | {'P*(1-P)':>8} | {'Taker Fee':>10} | {'Maker Fee':>10} | {'Min Edge':>10}")
    print("-" * 60)
    
    for price in [5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 95]:
        fee_factor = compute_fee_factor(price)
        taker = calculate_taker_fee(10, price)
        maker = calculate_maker_fee(10, price)
        min_edge = minimum_profitable_edge_taker(price, 10)
        
        print(f"{price:>5}c | {float(fee_factor):>8.4f} | {taker.total_fee_cents:>9}c | {maker.total_fee_cents:>9}c | {min_edge:>9.1f}c")


if __name__ == "__main__":
    breakeven_table()
    
    # Example calculations
    print("\n=== EXAMPLE CALCULATIONS ===")
    
    # 50c trade (worst case for fees)
    taker_50 = calculate_taker_fee(10, 50)
    print(f"\nBuying 10 contracts @ 50c (taker):")
    print(f"  {taker_50}")
    print(f"  Min edge needed: {minimum_profitable_edge_taker(50, 10)}c")
    
    # 20c trade (better fee environment)
    taker_20 = calculate_taker_fee(10, 20)
    print(f"\nBuying 10 contracts @ 20c (taker):")
    print(f"  {taker_20}")
    print(f"  Min edge needed: {minimum_profitable_edge_taker(20, 10)}c")
    
    # Market making at 50c
    maker_50 = calculate_maker_fee(10, 50)
    print(f"\nQuoting 10 contracts @ 50c (maker):")
    print(f"  {maker_50}")
    print(f"  Min half-spread needed: {minimum_profitable_spread_maker(50, 10)}c")
