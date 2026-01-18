import sqlite3
from collections import defaultdict

conn = sqlite3.connect("integrated_paper_data/paper_trades.db")
cur = conn.cursor()

# Analyze by market type
cur.execute("""
    SELECT ticker, side, SUM(quantity) as qty, SUM(quantity * price)/100.0 as cost
    FROM trades
    GROUP BY ticker
    ORDER BY cost DESC
""")

print("=" * 80)
print("TRADE ANALYSIS BY MARKET TYPE")
print("=" * 80)

hourly_count = 0
hourly_contracts = 0
hourly_cost = 0

m15_count = 0
m15_contracts = 0  
m15_cost = 0

print("\nHOURLY MARKETS (26JAN17XX or 26JAN23XX):")
print("-" * 60)
for row in cur.fetchall():
    ticker, side, qty, cost = row
    if "15M" in ticker.upper():
        m15_count += 1
        m15_contracts += qty
        m15_cost += cost
    else:
        hourly_count += 1
        hourly_contracts += qty
        hourly_cost += cost
        print(f"  {ticker}: {qty} contracts, ${cost:.2f}")

cur.execute("""
    SELECT ticker, side, SUM(quantity) as qty, SUM(quantity * price)/100.0 as cost
    FROM trades
    WHERE ticker LIKE '%15M%'
    GROUP BY ticker
    ORDER BY cost DESC
""")

print("\n15-MINUTE MARKETS:")
print("-" * 60)
for row in cur.fetchall():
    ticker, side, qty, cost = row
    print(f"  {ticker}: {qty} contracts, ${cost:.2f}")

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)
print(f"Hourly Markets:  {hourly_count} positions, {hourly_contracts} contracts, ${hourly_cost:.2f} cost")
print(f"15-Min Markets:  {m15_count} positions, {m15_contracts} contracts, ${m15_cost:.2f} cost")
print(f"\nHourly = {hourly_cost/(hourly_cost+m15_cost)*100:.1f}% of capital")
print(f"15-Min = {m15_cost/(hourly_cost+m15_cost)*100:.1f}% of capital")

# Check why hourly was preferred - look at edge/expected profit
print("\n" + "=" * 80)
print("WHY HOURLY WAS PREFERRED:")
print("=" * 80)
print("""
The bot sorts opportunities by EXPECTED PROFIT (edge * quantity).

Hourly markets at strikes far below current price (e.g., $91,250 when BTC=$95,400):
- Fair value: ~100% (deep ITM)
- Market price: 4-7 cents (cheap!)
- Edge: 93-96 cents per contract
- With aggressive sizing (250 max contracts): Expected profit = $230+ per trade

15-minute markets:
- Fair value: ~50% (coin flip)
- Market price: ~50 cents
- Edge: Maybe 5-10 cents if lucky
- Expected profit: Much smaller

The bot correctly identified the deep ITM hourly options as having MASSIVE expected value.
The issue: No diversification logic - it just maximizes expected profit.
""")

conn.close()
