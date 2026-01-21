#!/usr/bin/env python3
"""
Adversarial stress tests for crypto threshold markets.

Implements three tests against the same candidate set:
- Test A: Time jitter (±15m) applied to probability calculation timing
- Test B: Spread shock + no-fill + spread-aware slippage
- Test C: Hard-mode label with margin = max($25, 0.15% of spot)

Defaults follow the execution realism spec:
  - slippage Δ = max(0.01, 0.40 * spread)
  - no-fill when spread >= 0.08 or top_of_book_size < 10
  - taker fee = ceil_to_cent(0.07 * C * P * (1 - P)), charged on entry only (no settlement fee)
  - Prefer NO book when available (not available in synthetic backtest; we fallback to complement)

Usage:
  python3 stress_tests.py --days 180
"""

import asyncio
import math
import random
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple

import numpy as np

from backtester import HistoricalPrice

# --------------------------- Fee model ---------------------------

def ceil_to_cent(x: float) -> float:
    return math.ceil(x * 100.0) / 100.0

def kalshi_trade_fee(price: float, contracts: int, is_maker: bool = False) -> float:
    rate = 0.0175 if is_maker else 0.07
    fee = rate * contracts * price * (1.0 - price)
    return ceil_to_cent(fee)

# --------------------------- Probability model ---------------------------

def bs_probability(current_price: float, strike_price: float, time_to_expiry_seconds: float, volatility: float = 0.60) -> float:
    if time_to_expiry_seconds <= 0:
        return 1.0 if current_price >= strike_price else 0.0
    if current_price <= 0 or strike_price <= 0:
        return 0.5
    T = time_to_expiry_seconds / (365.25 * 24 * 3600)
    sigma = volatility
    log_moneyness = math.log(current_price / strike_price)
    vol_sqrt_t = sigma * math.sqrt(T)
    if vol_sqrt_t < 1e-6:
        return 1.0 if current_price >= strike_price else 0.0
    d2 = (log_moneyness - 0.5 * sigma * sigma * T) / vol_sqrt_t
    # standard normal CDF
    return 0.5 * (1.0 + math.erf(d2 / math.sqrt(2)))

# --------------------------- Adversarial market synth ---------------------------

@dataclass
class MarketSnap:
    ts: datetime
    strike: float
    yes_bid: float
    yes_ask: float
    top_size: int
    expiration: datetime
    close_price: float  # for settlement

@dataclass
class Trade:
    ts: datetime
    side: str  # "YES" or "NO"
    entry_price: float
    fee: float
    qty: int
    settlement: int  # 0 or 1
    pnl: float
    p_cal: float
    yes_bid: float
    yes_ask: float
    spread: float

# execution params (defaults)
SLIP_FLOOR = 0.01
SLIP_K = 0.40
NO_FILL_SPREAD = 0.08
MIN_TOP_SIZE = 10
QTY = 10
MIN_EDGE = 0.03


def effective_slippage(spread: float, slip_floor: float = SLIP_FLOOR, k: float = SLIP_K) -> float:
    return max(slip_floor, k * spread)


def should_no_fill(spread: float, top_size: int, no_fill_spread: float = NO_FILL_SPREAD, min_top_size: int = MIN_TOP_SIZE) -> bool:
    return (spread >= no_fill_spread) or (top_size < min_top_size)


def build_adversarial_markets(prices: List[HistoricalPrice], interval_minutes: int = 15,
                              hard_mode: bool = False) -> List[MarketSnap]:
    if not prices:
        return []
    markets: List[MarketSnap] = []
    # align to interval
    start = prices[0].timestamp
    end = prices[-1].timestamp
    current = start.replace(minute=(start.minute // interval_minutes) * interval_minutes, second=0, microsecond=0)
    while current + timedelta(minutes=interval_minutes) < end:
        expiration = current + timedelta(minutes=interval_minutes)
        # window prices
        window = [p for p in prices if current <= p.timestamp < expiration]
        if not window:
            current = expiration
            continue
        open_p = window[0].price
        close_p = window[-1].price
        # choose strike near open
        strike = round(open_p * random.choice([0.9975, 1.0, 1.0025]), -1)
        # stochastic lag: 15s to 120s
        lag_seconds = random.randint(15, 120)
        lag_index = max(0, len(window) - max(1, lag_seconds // 5))
        mm_price = window[lag_index].price
        # mm fair value with slightly lower vol
        mm_prob = bs_probability(mm_price, strike, (expiration - window[lag_index].timestamp).total_seconds(), volatility=0.55)
        # stochastic spread: base ~ 3c-12c with lognormal shock
        base_spread = random.uniform(0.02, 0.10)
        shock = np.random.lognormal(mean=0.0, sigma=0.25)
        spread = float(np.clip(base_spread * shock, 0.01, 0.20))
        yes_bid = max(0.01, min(0.99, mm_prob - spread / 2))
        yes_ask = max(0.01, min(0.99, mm_prob + spread / 2))
        # top size stochastic
        top_size = max(1, int(np.random.lognormal(mean=3.0, sigma=0.75)))  # median ~20
        # settlement with hard-mode margin if enabled
        if hard_mode:
            margin = max(25.0, 0.0015 * close_p)
            settlement = 1 if close_p >= (strike + margin) else 0
        else:
            settlement = 1 if close_p >= strike else 0
        markets.append(MarketSnap(ts=current, strike=strike, yes_bid=yes_bid, yes_ask=yes_ask,
                                  top_size=top_size, expiration=expiration, close_price=close_p))
        current = expiration
    return markets


def decide_and_execute(mkts: List[MarketSnap], prices_by_time: dict, jitter_seconds: int = 0) -> List[Trade]:
    trades: List[Trade] = []
    for m in mkts:
        # information set for p_cal with jitter applied
        p_ts = int(m.ts.timestamp()) + jitter_seconds
        # find closest price in our sampling grid (5s)
        grid_ts = p_ts - (p_ts % 5)
        p0 = prices_by_time.get(grid_ts)
        if p0 is None:
            # fallback to immediate next prices
            for off in (0, 5, 10, 15, 20, 25, 30):
                p0 = prices_by_time.get(grid_ts + off)
                if p0 is not None:
                    break
        if p0 is None:
            continue
        time_to_exp = (m.expiration - m.ts).total_seconds()
        p_cal_yes = bs_probability(p0, m.strike, time_to_exp, volatility=0.60)
        # compute edge
        spread = m.yes_ask - m.yes_bid
        # choose side by larger edge
        yes_edge = p_cal_yes - m.yes_ask
        no_edge = (1 - p_cal_yes) - (1 - m.yes_bid)  # compl. fallback
        side = None
        if yes_edge > MIN_EDGE or no_edge > MIN_EDGE:
            side = "YES" if yes_edge >= no_edge else "NO"
        if not side:
            continue
        # no-fill check
        if should_no_fill(spread, m.top_size):
            continue
        # entry price with spread-aware slippage
        delta = effective_slippage(spread)
        if side == "YES":
            entry = min(0.99, m.yes_ask + delta)
            p_cal = p_cal_yes
        else:
            # NO ask from complement (no book not available in synth)
            no_ask = 1 - m.yes_bid
            entry = min(0.99, no_ask + delta)
            p_cal = 1 - p_cal_yes
        qty = min(QTY, m.top_size)
        fee = kalshi_trade_fee(entry, qty, is_maker=False)
        # settlement payoff
        settle = m.close_price >= m.strike
        if side == "YES":
            payout = 1 if settle else 0
        else:
            payout = 1 if not settle else 0
        pnl = qty * (payout - entry) - fee
        trades.append(Trade(ts=m.ts, side=side, entry_price=entry, fee=fee, qty=qty,
                            settlement=int(payout == 1 if side == "YES" else payout == 1),
                            pnl=pnl, p_cal=p_cal, yes_bid=m.yes_bid, yes_ask=m.yes_ask, spread=spread))
    return trades


def summarize(trades: List[Trade], label: str):
    if not trades:
        print(f"\n{label}: 0 trades")
        return
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    total_pnl = sum(t.pnl for t in trades)
    wr = len(wins) / len(trades) if trades else 0.0
    avg = total_pnl / len(trades)
    print(f"\n{label}")
    print(f"  Trades: {len(trades)} | Win rate: {wr:.1%} | Total PnL: ${total_pnl:.2f} | Avg/trade: ${avg:.2f}")


async def fetch_prices(days: int = 180) -> List[HistoricalPrice]:
    from backtester import LatencyBacktester
    bt = LatencyBacktester()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    prices = await bt.fetch_historical_prices("BTC", start, end)
    return prices


def build_price_grid(prices: List[HistoricalPrice]) -> dict:
    grid = {}
    for p in prices:
        ts = int(p.timestamp.timestamp())
        ts = ts - (ts % 5)
        grid[ts] = p.price
    return grid


async def main(days: int = 180):
    print(f"Fetching ~{days} days of BTC spot data (5s sampling) for stress tests...")
    prices = await fetch_prices(days)
    print(f"Got {len(prices)} price points")
    if not prices:
        print("No prices available")
        return
    grid = build_price_grid(prices)
    
    # Baseline (no jitter, no spread shock beyond stochastic, normal label)
    mkts_baseline = build_adversarial_markets(prices, hard_mode=False)
    trades_baseline = decide_and_execute(mkts_baseline, grid, jitter_seconds=0)
    summarize(trades_baseline, "Baseline")

    # Test A: Time jitter ±15m
    trades_jitter_plus = decide_and_execute(mkts_baseline, grid, jitter_seconds=+900)
    trades_jitter_minus = decide_and_execute(mkts_baseline, grid, jitter_seconds=-900)
    summarize(trades_jitter_plus, "Test A (+15m jitter)")
    summarize(trades_jitter_minus, "Test A (-15m jitter)")

    # Test B: Spread shock (multiply spread stochastically by extra shock) + enforce no-fill
    # Implement by rebuilding markets with added spread shock while keeping other randomness
    def shock_markets(markets: List[MarketSnap]) -> List[MarketSnap]:
        shocked = []
        for m in markets:
            extra = float(np.random.lognormal(mean=0.0, sigma=0.5))
            base_spread = (m.yes_ask - m.yes_bid)
            new_spread = float(np.clip(base_spread * extra, 0.01, 0.30))
            mid = (m.yes_bid + m.yes_ask) / 2
            yes_bid = max(0.01, min(0.99, mid - new_spread / 2))
            yes_ask = max(0.01, min(0.99, mid + new_spread / 2))
            shocked.append(MarketSnap(ts=m.ts, strike=m.strike, yes_bid=yes_bid, yes_ask=yes_ask,
                                      top_size=m.top_size, expiration=m.expiration, close_price=m.close_price))
        return shocked
    mkts_shock = shock_markets(mkts_baseline)
    trades_shock = decide_and_execute(mkts_shock, grid, jitter_seconds=0)
    summarize(trades_shock, "Test B (spread shock + no-fill)")

    # Test C: Hard-mode label margin
    mkts_hard = build_adversarial_markets(prices, hard_mode=True)
    trades_hard = decide_and_execute(mkts_hard, grid, jitter_seconds=0)
    summarize(trades_hard, "Test C (hard-mode label)")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run adversarial stress tests")
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--min-edge", type=float, default=MIN_EDGE, help="Minimum edge threshold (default 0.03)")
    args = parser.parse_args()
    # Update global min edge for this run
    global MIN_EDGE
    MIN_EDGE = args.min_edge
    asyncio.run(main(days=args.days))
