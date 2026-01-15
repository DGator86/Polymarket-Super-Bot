#!/usr/bin/env python3
"""
Kalshi Latency Bot - Backtesting Module

Validates strategy on historical data before live trading.
"""

import json
import asyncio
import aiohttp
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
import numpy as np
from collections import defaultdict
from scipy.stats import norm

@dataclass
class HistoricalPrice:
    """Historical price point"""
    timestamp: datetime
    price: float
    source: str

@dataclass
class HistoricalMarket:
    """Historical Kalshi market snapshot"""
    timestamp: datetime
    ticker: str
    yes_bid: float
    yes_ask: float
    strike_price: float
    expiration: datetime
    settlement: Optional[float] = None  # 1.0 if YES won, 0.0 if NO won

@dataclass
class BacktestTrade:
    """Simulated trade"""
    entry_time: datetime
    ticker: str
    side: str
    quantity: int
    entry_price: float
    exit_price: float
    pnl: float
    edge_at_entry: float

@dataclass
class BacktestResults:
    """Backtest summary"""
    total_trades: int
    winning_trades: int
    losing_trades: int
    total_pnl: float
    avg_pnl_per_trade: float
    win_rate: float
    avg_edge: float
    sharpe_ratio: float
    max_drawdown: float
    profit_factor: float

    def __str__(self):
        return f"""
╔══════════════════════════════════════════════════════════╗
║              BACKTEST RESULTS                            ║
╠══════════════════════════════════════════════════════════╣
║  Total Trades:      {self.total_trades:>6}                             ║
║  Winning Trades:    {self.winning_trades:>6} ({self.win_rate:>5.1%})                     ║
║  Losing Trades:     {self.losing_trades:>6}                             ║
╠══════════════════════════════════════════════════════════╣
║  Total P&L:         ${self.total_pnl:>10.2f}                       ║
║  Avg P&L/Trade:     ${self.avg_pnl_per_trade:>10.2f}                       ║
║  Avg Edge:          {self.avg_edge:>6.2%}                             ║
╠══════════════════════════════════════════════════════════╣
║  Sharpe Ratio:      {self.sharpe_ratio:>8.2f}                           ║
║  Max Drawdown:      {self.max_drawdown:>6.2%}                             ║
║  Profit Factor:     {self.profit_factor:>8.2f}                           ║
╚══════════════════════════════════════════════════════════╝
"""

class LatencyBacktester:
    """
    Backtests the latency arbitrage strategy using historical data.

    Simulates:
    1. Real-time price feeds from exchanges
    2. Kalshi market snapshots
    3. Strategy signal generation
    4. Trade execution with realistic slippage
    """

    def __init__(
        self,
        min_edge: float = 0.03,
        max_spread: float = 0.02,
        position_size: int = 10,
        slippage_bps: float = 10,  # 10 basis points slippage
    ):
        self.min_edge = min_edge
        self.max_spread = max_spread
        self.position_size = position_size
        self.slippage = slippage_bps / 10000

        self.price_history: List[HistoricalPrice] = []
        self.market_history: List[HistoricalMarket] = []
        self.trades: List[BacktestTrade] = []

    async def fetch_historical_prices(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> List[HistoricalPrice]:
        """
        Fetch historical crypto prices from CoinGecko (free API).
        For production, use exchange historical data APIs.
        """
        prices = []

        # CoinGecko API
        coin_id = "bitcoin" if symbol == "BTC" else "ethereum"
        start_ts = int(start.timestamp())
        end_ts = int(end.timestamp())

        url = (
            f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart/range"
            f"?vs_currency=usd&from={start_ts}&to={end_ts}"
        )

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for ts, price in data.get("prices", []):
                        prices.append(HistoricalPrice(
                            timestamp=datetime.fromtimestamp(ts/1000, tz=timezone.utc),
                            price=price,
                            source="coingecko"
                        ))

        return prices

    def _calculate_probability(
        self,
        current_price: float,
        strike_price: float,
        time_to_expiry_seconds: float,
        volatility: float = 0.60,
    ) -> float:
        """Black-Scholes probability calculation"""
        if time_to_expiry_seconds <= 0:
            return 1.0 if current_price >= strike_price else 0.0

        T = time_to_expiry_seconds / (365.25 * 24 * 3600)
        sigma = volatility

        if current_price <= 0 or strike_price <= 0:
            return 0.5

        log_moneyness = np.log(current_price / strike_price)
        vol_sqrt_t = sigma * np.sqrt(T)

        if vol_sqrt_t < 0.0001:
            return 1.0 if current_price >= strike_price else 0.0

        d2 = (log_moneyness - 0.5 * sigma**2 * T) / vol_sqrt_t
        return norm.cdf(d2)

    def _simulate_market_prices(
        self,
        crypto_prices: List[HistoricalPrice],
        interval_minutes: int = 15,
    ) -> List[HistoricalMarket]:
        """
        Simulate Kalshi market prices based on historical crypto prices.

        Assumes market makers price with some lag and inefficiency
        that the bot can exploit.
        """
        markets = []

        if not crypto_prices:
            return markets

        # Generate markets at regular intervals
        start = crypto_prices[0].timestamp
        end = crypto_prices[-1].timestamp

        current = start.replace(minute=(start.minute // interval_minutes) * interval_minutes,
                               second=0, microsecond=0)

        while current < end:
            expiration = current + timedelta(minutes=interval_minutes)

            # Find prices around this time
            prices_in_window = [
                p for p in crypto_prices
                if current <= p.timestamp < expiration
            ]

            if prices_in_window:
                # Get price at market open and close
                open_price = prices_in_window[0].price
                close_price = prices_in_window[-1].price

                # Generate multiple strike levels
                for strike_pct in [0.995, 0.9975, 1.0, 1.0025, 1.005]:
                    strike = round(open_price * strike_pct, -1)  # Round to nearest $10

                    # Simulate market maker pricing (with lag)
                    # MM uses 60-second old price for their model
                    lag_idx = max(0, len(prices_in_window) - 12)  # ~60 sec lag at 5s intervals
                    lagged_price = prices_in_window[lag_idx].price

                    # Calculate MM's fair value (based on lagged price)
                    mm_prob = self._calculate_probability(
                        lagged_price, strike,
                        (expiration - prices_in_window[lag_idx].timestamp).total_seconds(),
                        volatility=0.55  # MM uses lower vol estimate
                    )

                    # Add spread around fair value
                    spread = 0.04  # 4 cent spread
                    yes_bid = max(0.01, mm_prob - spread/2)
                    yes_ask = min(0.99, mm_prob + spread/2)

                    # Determine settlement
                    settlement = 1.0 if close_price >= strike else 0.0

                    markets.append(HistoricalMarket(
                        timestamp=current,
                        ticker=f"KXBTC-{current.strftime('%H%M')}-{int(strike)}",
                        yes_bid=yes_bid,
                        yes_ask=yes_ask,
                        strike_price=strike,
                        expiration=expiration,
                        settlement=settlement,
                    ))

            current = expiration

        return markets

    def run_backtest(
        self,
        crypto_prices: List[HistoricalPrice],
    ) -> BacktestResults:
        """
        Run backtest on historical data.
        """
        # Generate simulated markets
        markets = self._simulate_market_prices(crypto_prices)
        self.market_history = markets
        self.price_history = crypto_prices

        # Build price lookup
        price_by_time: Dict[int, float] = {}
        for p in crypto_prices:
            # Round to nearest 5 seconds
            ts = int(p.timestamp.timestamp()) // 5 * 5
            price_by_time[ts] = p.price

        trades = []
        equity_curve = [0.0]

        for market in markets:
            # Get current crypto price
            market_ts = int(market.timestamp.timestamp()) // 5 * 5

            # Look for price slightly ahead (simulating our latency advantage)
            current_price = None
            for offset in range(0, 15, 5):  # Check 0, 5, 10 seconds ahead
                ts = market_ts + offset
                if ts in price_by_time:
                    current_price = price_by_time[ts]
                    break

            if current_price is None:
                continue

            # Calculate our fair value
            time_to_expiry = (market.expiration - market.timestamp).total_seconds()
            fair_prob = self._calculate_probability(
                current_price,
                market.strike_price,
                time_to_expiry,
                volatility=0.60,
            )

            # Check spread
            spread = market.yes_ask - market.yes_bid
            if spread > self.max_spread:
                continue

            # Calculate edge for both sides
            yes_edge = fair_prob - market.yes_ask
            no_edge = (1 - fair_prob) - (1 - market.yes_bid)

            # Trade if edge exceeds threshold
            if yes_edge > self.min_edge:
                entry_price = market.yes_ask * (1 + self.slippage)
                exit_price = market.settlement
                pnl = self.position_size * (exit_price - entry_price)

                trades.append(BacktestTrade(
                    entry_time=market.timestamp,
                    ticker=market.ticker,
                    side="YES",
                    quantity=self.position_size,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    pnl=pnl,
                    edge_at_entry=yes_edge,
                ))
                equity_curve.append(equity_curve[-1] + pnl)

            elif no_edge > self.min_edge:
                entry_price = (1 - market.yes_bid) * (1 + self.slippage)
                exit_price = 1 - market.settlement
                pnl = self.position_size * (exit_price - entry_price)

                trades.append(BacktestTrade(
                    entry_time=market.timestamp,
                    ticker=market.ticker,
                    side="NO",
                    quantity=self.position_size,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    pnl=pnl,
                    edge_at_entry=no_edge,
                ))
                equity_curve.append(equity_curve[-1] + pnl)

        self.trades = trades

        # Calculate metrics
        if not trades:
            return BacktestResults(
                total_trades=0, winning_trades=0, losing_trades=0,
                total_pnl=0, avg_pnl_per_trade=0, win_rate=0,
                avg_edge=0, sharpe_ratio=0, max_drawdown=0, profit_factor=0,
            )

        pnls = [t.pnl for t in trades]
        winning = [p for p in pnls if p > 0]
        losing = [p for p in pnls if p <= 0]

        # Sharpe ratio (assuming daily returns)
        returns = np.array(pnls)
        sharpe = (np.mean(returns) / np.std(returns) * np.sqrt(252)) if np.std(returns) > 0 else 0

        # Max drawdown
        peak = equity_curve[0]
        max_dd = 0
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)

        # Profit factor
        gross_profit = sum(winning) if winning else 0
        gross_loss = abs(sum(losing)) if losing else 1
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        return BacktestResults(
            total_trades=len(trades),
            winning_trades=len(winning),
            losing_trades=len(losing),
            total_pnl=sum(pnls),
            avg_pnl_per_trade=np.mean(pnls),
            win_rate=len(winning) / len(trades),
            avg_edge=np.mean([t.edge_at_entry for t in trades]),
            sharpe_ratio=sharpe,
            max_drawdown=max_dd,
            profit_factor=profit_factor,
        )

async def run_sample_backtest():
    """Run a sample backtest with real historical data"""
    print("Kalshi Latency Bot - Backtester")
    print("=" * 50)

    backtester = LatencyBacktester(
        min_edge=0.03,
        max_spread=0.04,
        position_size=10,
    )

    # Fetch last 7 days of BTC data
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=7)

    print(f"Fetching historical prices from {start.date()} to {end.date()}...")
    prices = await backtester.fetch_historical_prices("BTC", start, end)
    print(f"Got {len(prices)} price points")

    if not prices:
        print("No price data available - using synthetic data")
        # Generate synthetic data for demo
        base_price = 95000
        prices = []
        current = start
        while current < end:
            # Random walk with mean reversion
            base_price *= (1 + np.random.normal(0, 0.001))
            prices.append(HistoricalPrice(
                timestamp=current,
                price=base_price,
                source="synthetic"
            ))
            current += timedelta(seconds=5)

    print("Running backtest...")
    results = backtester.run_backtest(prices)
    print(results)

    # Show sample trades
    if backtester.trades:
        print("\nSample Trades:")
        print("-" * 80)
        for trade in backtester.trades[:10]:
            status = "WIN" if trade.pnl > 0 else "LOSS"
            print(
                f"{trade.entry_time.strftime('%Y-%m-%d %H:%M')} | "
                f"{trade.ticker:30} | {trade.side:3} | "
                f"Edge: {trade.edge_at_entry:5.2%} | "
                f"P&L: ${trade.pnl:7.2f} [{status}]"
            )

if __name__ == "__main__":
    asyncio.run(run_sample_backtest())
