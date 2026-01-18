#!/usr/bin/env python3
"""
Compare paper trading accounts side by side.
Shows performance of both aggressive (hourly) and 15m strategies.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

def get_account_stats(db_path: str, account_name: str):
    """Get stats for a single account."""
    if not Path(db_path).exists():
        return None
    
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    # Total trades and contracts
    cur.execute("SELECT COUNT(*), COALESCE(SUM(quantity), 0), COALESCE(SUM(quantity * price)/100.0, 0) FROM trades")
    trade_count, total_contracts, total_cost = cur.fetchone()
    
    # By side
    cur.execute("SELECT side, COUNT(*), SUM(quantity) FROM trades GROUP BY side")
    by_side = {row[0]: {"trades": row[1], "contracts": row[2]} for row in cur.fetchall()}
    
    # By mode (maker/taker)
    cur.execute("SELECT mode, COUNT(*), SUM(quantity) FROM trades GROUP BY mode")
    by_mode = {row[0]: {"trades": row[1], "contracts": row[2]} for row in cur.fetchall()}
    
    # Recent trades
    cur.execute("""
        SELECT ticker, side, quantity, price, created_at 
        FROM trades ORDER BY created_at DESC LIMIT 5
    """)
    recent = cur.fetchall()
    
    # First and last trade times
    cur.execute("SELECT MIN(created_at), MAX(created_at) FROM trades")
    first_trade, last_trade = cur.fetchone()
    
    # Unique tickers
    cur.execute("SELECT COUNT(DISTINCT ticker) FROM trades")
    unique_tickers = cur.fetchone()[0]
    
    conn.close()
    
    return {
        "name": account_name,
        "trade_count": trade_count,
        "total_contracts": total_contracts or 0,
        "total_cost": total_cost or 0,
        "by_side": by_side,
        "by_mode": by_mode,
        "recent": recent,
        "first_trade": first_trade,
        "last_trade": last_trade,
        "unique_tickers": unique_tickers
    }

def print_comparison():
    """Print side-by-side comparison of both accounts."""
    
    # Get stats for both accounts
    aggressive = get_account_stats("integrated_paper_data/paper_trades.db", "AGGRESSIVE (Hourly)")
    fast_15m = get_account_stats("paper_15m_data/paper_trades.db", "FAST 15M")
    
    now = datetime.now(timezone.utc)
    est_hour = (now.hour - 5) % 24
    
    print("=" * 90)
    print("PAPER TRADING ACCOUNT COMPARISON")
    print(f"As of: {now.strftime('%Y-%m-%d %H:%M:%S')} UTC / {est_hour}:{now.strftime('%M:%S')} EST")
    print("=" * 90)
    
    # Header
    print(f"\n{'Metric':<30} {'AGGRESSIVE (Hourly)':>25} {'FAST 15M':>25}")
    print("-" * 82)
    
    # Helper function
    def row(label, val1, val2):
        v1 = str(val1) if val1 is not None else "N/A"
        v2 = str(val2) if val2 is not None else "N/A"
        print(f"{label:<30} {v1:>25} {v2:>25}")
    
    if aggressive:
        agg_trades = aggressive["trade_count"]
        agg_contracts = aggressive["total_contracts"]
        agg_cost = f"${aggressive['total_cost']:.2f}"
        agg_tickers = aggressive["unique_tickers"]
        agg_yes = aggressive["by_side"].get("yes", {}).get("contracts", 0)
        agg_no = aggressive["by_side"].get("no", {}).get("contracts", 0)
        agg_taker = aggressive["by_mode"].get("taker", {}).get("contracts", 0)
        agg_maker = aggressive["by_mode"].get("maker", {}).get("contracts", 0)
    else:
        agg_trades = agg_contracts = agg_cost = agg_tickers = "N/A"
        agg_yes = agg_no = agg_taker = agg_maker = "N/A"
    
    if fast_15m:
        f15_trades = fast_15m["trade_count"]
        f15_contracts = fast_15m["total_contracts"]
        f15_cost = f"${fast_15m['total_cost']:.2f}"
        f15_tickers = fast_15m["unique_tickers"]
        f15_yes = fast_15m["by_side"].get("yes", {}).get("contracts", 0)
        f15_no = fast_15m["by_side"].get("no", {}).get("contracts", 0)
        f15_taker = fast_15m["by_mode"].get("taker", {}).get("contracts", 0)
        f15_maker = fast_15m["by_mode"].get("maker", {}).get("contracts", 0)
    else:
        f15_trades = f15_contracts = f15_cost = f15_tickers = "N/A"
        f15_yes = f15_no = f15_taker = f15_maker = "N/A"
    
    row("Total Trades", agg_trades, f15_trades)
    row("Total Contracts", agg_contracts, f15_contracts)
    row("Total Cost Basis", agg_cost, f15_cost)
    row("Unique Markets", agg_tickers, f15_tickers)
    print("-" * 82)
    row("YES Contracts", agg_yes, f15_yes)
    row("NO Contracts", agg_no, f15_no)
    row("Taker Contracts", agg_taker, f15_taker)
    row("Maker Contracts", agg_maker, f15_maker)
    
    # Trading period
    print("-" * 82)
    if aggressive and aggressive["first_trade"]:
        row("First Trade", aggressive["first_trade"][:19], 
            fast_15m["first_trade"][:19] if fast_15m and fast_15m["first_trade"] else "N/A")
        row("Last Trade", aggressive["last_trade"][:19] if aggressive["last_trade"] else "N/A",
            fast_15m["last_trade"][:19] if fast_15m and fast_15m["last_trade"] else "N/A")
    
    # Recent trades for each
    print("\n" + "=" * 90)
    print("RECENT TRADES")
    print("=" * 90)
    
    if aggressive and aggressive["recent"]:
        print(f"\n--- AGGRESSIVE (Hourly) - Last 5 trades ---")
        for t in aggressive["recent"]:
            print(f"  {t[4][:19]} | {t[1].upper():>3} {t[2]:>4}x {t[0]:<30} @ {t[3]}c")
    
    if fast_15m and fast_15m["recent"]:
        print(f"\n--- FAST 15M - Last 5 trades ---")
        for t in fast_15m["recent"]:
            print(f"  {t[4][:19]} | {t[1].upper():>3} {t[2]:>4}x {t[0]:<30} @ {t[3]}c")
    elif fast_15m:
        print(f"\n--- FAST 15M - No trades yet (waiting for 15m markets) ---")
    
    print("\n" + "=" * 90)
    print("STRATEGY NOTES")
    print("=" * 90)
    print("""
AGGRESSIVE (Hourly):
  - Trades ALL crypto markets (15m + hourly)
  - Prioritizes highest expected profit
  - Typically buys deep ITM hourly options at cheap prices
  - Capital: $1,000 | Interval: 45s

FAST 15M:
  - Trades ONLY 15-minute markets
  - Faster capital turnover
  - More diversified, smaller positions per trade
  - Capital: $500 | Interval: 30s
  - Note: 15m markets have limited hours (may show 0 trades overnight)
""")

if __name__ == "__main__":
    print_comparison()
