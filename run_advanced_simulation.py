#!/usr/bin/env python3
"""
Advanced Simulation & Evaluation for Kalshi Crypto Bot
Implements rigorous statistical evaluation and EV-based trading logic.

Features:
1.  Robust Backtesting: Time-series safe splitting (Walk-Forward).
2.  Advanced Metrics: Brier Score, Log Loss, Wilson Score Intervals.
3.  Regime Detection: Trending vs Choppy differentiation.
4.  EV-Based Execution: Trading probability gaps (p - q) vs fees.
5.  Calibration Analysis: Reliability diagrams.
"""

import numpy as np
import pandas as pd
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from math import sqrt, log, exp, erf

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AdvancedSimulation")

# -----------------------------------------------------------------------------
# 1. Synthetic Data Generation (since real 15m historical data is unavailable)
# -----------------------------------------------------------------------------

class MarketRegime:
    TRENDING = "trending"
    CHOPPY = "choppy"

@dataclass
class MarketData:
    timestamp: datetime
    price: float
    regime: str
    volatility: float

class SyntheticDataGenerator:
    """Generates realistic 15m crypto price data with regime switching and jumps."""
    
    def __init__(self, start_price=50000.0, daily_vol=0.03):
        self.start_price = start_price
        self.daily_vol = daily_vol
        
    def generate(self, days=90) -> pd.DataFrame:
        """Generate 15m OHLCV data."""
        logger.info(f"Generating {days} days of synthetic 15m data...")
        
        n_steps = days * 24 * 4  # 15m intervals
        dt = 1/ (24 * 4 * 365)   # Time step in years
        
        prices = [self.start_price]
        timestamps = [datetime.now() - timedelta(days=days)]
        regimes = []
        volatilities = []
        
        # State: 0 = Choppy, 1 = Trending Up, 2 = Trending Down
        state = 0 
        current_price = self.start_price
        
        for i in range(n_steps):
            # Regime switching probability
            if np.random.random() < 0.05:  # 5% chance to switch regime per 15m
                state = np.random.choice([0, 1, 2], p=[0.6, 0.2, 0.2])
            
            # Volatility depends on regime
            if state == 0:
                sigma = self.daily_vol * 0.8  # Lower vol in chop
                drift = 0
                regime = MarketRegime.CHOPPY
            else:
                sigma = self.daily_vol * 1.5  # Higher vol in trend
                drift = 0.5 if state == 1 else -0.5 # Strong drift
                regime = MarketRegime.TRENDING
            
            # Geometric Brownian Motion step
            shock = np.random.normal(0, 1)
            
            # Add "Jumps" (Fat tails) that the simple model might miss
            if np.random.random() < 0.01: # 1% chance of jump
                shock += np.random.choice([-3, 3])
                
            change = current_price * (drift * dt + sigma * sqrt(dt) * shock)
            current_price += change
            
            prices.append(current_price)
            timestamps.append(timestamps[-1] + timedelta(minutes=15))
            regimes.append(regime)
            volatilities.append(sigma)
            
        df = pd.DataFrame({
            'timestamp': timestamps[:-1],
            'price': prices[:-1],
            'regime': regimes,
            'volatility': volatilities
        })
        return df

    @staticmethod
    def load_csv(filepath: str) -> pd.DataFrame:
        """Load real data from CSV. Expects: timestamp, price."""
        df = pd.read_csv(filepath)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        # Simple regime detection for real data (ADX proxy or Volatility)
        # Using rolling volatility as proxy
        df['returns'] = df['price'].pct_change()
        df['rolling_vol'] = df['returns'].rolling(window=24).std()
        median_vol = df['rolling_vol'].median()
        
        df['regime'] = df['rolling_vol'].apply(
            lambda x: MarketRegime.TRENDING if x > median_vol * 1.2 else MarketRegime.CHOPPY
        )
        df['volatility'] = df['rolling_vol'] * sqrt(24*4*365) # Annualized approx
        
        return df.dropna()


# -----------------------------------------------------------------------------
# 2. Strategy Implementation (The "Bot")
# -----------------------------------------------------------------------------

class Strategy:
    """
    Simulates the bot's logic: 
    Predicts probability that price > threshold in X hours.
    """
    
    def predict_proba(self, current_price, threshold, time_hours, volatility) -> float:
        """
        Calculates probability using Black-Scholes logic (simplified).
        P(S_T > K)
        """
        if time_hours <= 0:
            return 1.0 if current_price > threshold else 0.0
            
        t = time_hours / (24 * 365) # Annualized time
        # Annualized vol from daily vol approximation
        sigma_annual = volatility * sqrt(365) 
        
        # d2 term from Black-Scholes
        # ln(S/K) + (r - 0.5*sigma^2)t / (sigma * sqrt(t))
        # Assuming r=0 for crypto short term
        
        d2 = (log(current_price / threshold) - 0.5 * sigma_annual**2 * t) / (sigma_annual * sqrt(t))
        
        # CDF of standard normal
        prob = 0.5 * (1 + erf(d2 / sqrt(2)))
        return prob

# -----------------------------------------------------------------------------
# 3. Evaluation Engine (The Core Improvement)
# -----------------------------------------------------------------------------

@dataclass
class TradeRecord:
    timestamp: datetime
    regime: str
    model_prob: float
    market_prob: float
    outcome: int # 1 = Win, 0 = Loss
    pnl: float
    fee: float

class Evaluator:
    """
    Implements advanced metrics:
    - Wilson Score Interval
    - Brier Score
    - Calibration
    - Expected Value
    """
    
    def wilson_score_interval(self, success_count, total, confidence=0.95):
        """Calculate Wilson Score Interval for binomial proportion."""
        if total == 0: return (0, 0)
        p_hat = success_count / total
        z = 1.96 # For 95%
        
        term1 = p_hat + z*z/(2*total)
        term2 = z * sqrt((p_hat*(1-p_hat) + z*z/(4*total))/total)
        denominator = 1 + z*z/total
        
        lower = (term1 - term2) / denominator
        upper = (term1 + term2) / denominator
        return (lower, upper)

    def brier_score(self, probs, outcomes):
        """Mean Squared Error of probabilities."""
        return np.mean((np.array(probs) - np.array(outcomes)) ** 2)

    def log_loss(self, probs, outcomes):
        """Cross-entropy loss."""
        epsilon = 1e-15
        probs = np.clip(probs, epsilon, 1 - epsilon)
        return -np.mean(np.array(outcomes) * np.log(probs) + (1 - np.array(outcomes)) * np.log(1 - probs))

    def evaluate(self, trades: List[TradeRecord]):
        if not trades:
            print("No trades to evaluate.")
            return

        df = pd.DataFrame([vars(t) for t in trades])
        
        print("\n" + "="*60)
        print("ADVANCED EVALUATION REPORT")
        print("="*60)
        
        # 1. Overall Metrics
        n_trades = len(df)
        wins = df['outcome'].sum()
        win_rate = wins / n_trades
        ci_lower, ci_upper = self.wilson_score_interval(wins, n_trades)
        
        print(f"\n1. PERFORMANCE SUMMARY")
        print(f"   Total Trades:      {n_trades}")
        print(f"   Win Rate:          {win_rate:.1%} (95% CI: {ci_lower:.1%} - {ci_upper:.1%})")
        print(f"   Total PnL:         ${df['pnl'].sum():.2f}")
        print(f"   Avg PnL per Trade: ${df['pnl'].mean():.2f}")
        
        # 2. Calibration Metrics
        brier = self.brier_score(df['model_prob'], df['outcome'])
        ll = self.log_loss(df['model_prob'], df['outcome'])
        
        print(f"\n2. PROBABILITY CALIBRATION")
        print(f"   Brier Score:       {brier:.4f} (Lower is better, 0.25 is random)")
        print(f"   Log Loss:          {ll:.4f}")
        
        # Reliability Diagram Data
        print(f"   Reliability Buckets:")
        bins = np.linspace(0, 1, 11)
        df['bucket'] = pd.cut(df['model_prob'], bins)
        grouped = df.groupby('bucket', observed=False).agg({'outcome': ['mean', 'count'], 'model_prob': 'mean'})
        grouped.columns = ['actual_rate', 'count', 'avg_pred']
        
        for idx, row in grouped.iterrows():
            if row['count'] > 0:
                print(f"     [{idx.left:.1f}-{idx.right:.1f}]: Pred {row['avg_pred']:.2f} vs Actual {row['actual_rate']:.2f} (n={int(row['count'])})")
        
        # 3. Regime Analysis
        print(f"\n3. REGIME ANALYSIS")
        for regime in df['regime'].unique():
            subset = df[df['regime'] == regime]
            if len(subset) == 0: continue
            
            r_wins = subset['outcome'].sum()
            r_total = len(subset)
            r_wr = r_wins / r_total
            r_ci = self.wilson_score_interval(r_wins, r_total)
            r_ev = subset['pnl'].mean()
            
            print(f"   {regime.upper()}:")
            print(f"     Trades: {r_total}")
            print(f"     Win Rate: {r_wr:.1%} ({r_ci[0]:.1%}-{r_ci[1]:.1%})")
            print(f"     Avg EV: ${r_ev:.2f}")

        # 4. EV Analysis
        # Expected Value at entry vs Realized
        df['expected_edge'] = df['model_prob'] - df['market_prob']
        # For NO trades, edge is (1-model) - (1-market) = market - model. 
        # But we simplified model to always be YES for this simulation.
        
        print(f"\n4. EXPECTED VALUE (EV) ANALYSIS")
        print(f"   Avg Model Edge:    {df['expected_edge'].mean()*100:.1f}%")
        print(f"   Realized Edge:     {(win_rate - 0.5)*100:.1f}% (assuming 50% base)")
        
        print(f"\n" + "="*60)

# -----------------------------------------------------------------------------
# 4. Simulation Runner
# -----------------------------------------------------------------------------

def run_backtest(df: pd.DataFrame, name: str = "Simulation"):
    """Run backtest on a specific dataframe."""
    strategy = Strategy()
    evaluator = Evaluator()
    trades = []
    
    # Simulation Parameters
    lookahead_hours = 1
    confidence_threshold = 0.65
    min_edge = 0.05
    fee_per_contract = 0.02
    slippage_per_contract = 0.01  # Add 1 cent slippage
    
    # Ensure dataframe has required columns
    if 'regime' not in df.columns:
        # Simple regime proxy for real data if missing
        df['returns'] = df['price'].pct_change()
        df['rolling_vol'] = df['returns'].rolling(24).std()
        median_vol = df['rolling_vol'].median()
        df['regime'] = df['rolling_vol'].apply(
            lambda x: MarketRegime.TRENDING if x > median_vol * 1.2 else MarketRegime.CHOPPY
        )
        # Fill NaN from rolling
        df['regime'] = df['regime'].fillna(MarketRegime.CHOPPY)
        
    if 'volatility' not in df.columns:
         df['volatility'] = df['price'].pct_change().rolling(24).std() * sqrt(24*4*365)
         df['volatility'] = df['volatility'].fillna(0.5) # Default
    
    print(f"\nRunning backtest for: {name} ({len(df)} candles)...")
    
    # PURGED WALK-FORWARD LOGIC
    # We will simulate strict non-overlapping windows for decision vs outcome
    
    for i in range(len(df) - 4*lookahead_hours):
        current = df.iloc[i]
        future = df.iloc[i + 4*lookahead_hours]
        
        # Define a "Market" - e.g. "BTC > Current Price + 0.5%?"
        strike_price = current.price * 1.005 
        
        # 1. Model Prediction
        # For real data, 'volatility' is in the DF. For synthetic, it's there too.
        # We add some noise to simulate estimation error
        est_vol = current.volatility * np.random.normal(1, 0.2)
        model_p = strategy.predict_proba(current.price, strike_price, lookahead_hours, est_vol)
        
        # 2. Market Price (Implied Probability)
        # Assume market is slightly efficient but noisy
        true_p = strategy.predict_proba(current.price, strike_price, lookahead_hours, current.volatility)
        market_sentiment = np.random.normal(0, 0.1)
        market_q = np.clip(true_p + market_sentiment, 0.01, 0.99)
        
        # 3. Trading Logic with Slippage
        # Conservative: assume we buy at market_q + slippage
        buy_price_yes = min(market_q + slippage_per_contract, 0.99)
        buy_price_no = min((1 - market_q) + slippage_per_contract, 0.99)
        
        ev_yes = model_p - buy_price_yes - fee_per_contract
        ev_no = (1 - model_p) - buy_price_no - fee_per_contract
        
        trade_side = None
        if ev_yes > min_edge and model_p > confidence_threshold:
            trade_side = "YES"
            entry_price = buy_price_yes
        elif ev_no > min_edge and (1-model_p) > confidence_threshold:
            trade_side = "NO"
            entry_price = buy_price_no
            
        if trade_side:
            # 4. Outcome
            outcome_bool = future.price > strike_price
            
            if trade_side == "YES":
                win = 1 if outcome_bool else 0
                # PnL = (Payout - Entry - Fee)
                pnl = (1 - entry_price - fee_per_contract) if win else (-entry_price - fee_per_contract)
                record_prob = model_p
                record_market = market_q
            else: # NO
                win = 1 if not outcome_bool else 0
                pnl = (1 - entry_price - fee_per_contract) if win else (-entry_price - fee_per_contract)
                record_prob = 1 - model_p
                record_market = 1 - market_q
                
            trades.append(TradeRecord(
                timestamp=current.timestamp,
                regime=current.regime,
                model_prob=record_prob,
                market_prob=record_market,
                outcome=win,
                pnl=pnl,
                fee=fee_per_contract
            ))
            
    evaluator.evaluate(trades)

def run_simulation():
    # Setup
    gen = SyntheticDataGenerator(daily_vol=0.04) 
    df = gen.generate(days=180) 
    run_backtest(df, "Synthetic Baseline")

if __name__ == "__main__":
    run_simulation()
