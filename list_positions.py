import sqlite3
from datetime import datetime, timezone

conn = sqlite3.connect("integrated_paper_data/paper_trades.db")
cur = conn.cursor()

cur.execute("""
    SELECT ticker, side, SUM(quantity) as qty, 
           AVG(price) as avg_price, 
           SUM(quantity * price)/100.0 as cost_basis,
           MIN(created_at) as first_trade,
           MAX(created_at) as last_trade
    FROM trades
    GROUP BY ticker, side
    ORDER BY ticker
""")

now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
print("="*110)
print("ALL CURRENT PAPER TRADING POSITIONS")
print("As of:", now, "UTC")
print("="*110)
print()
print("Ticker                              Side      Qty  Avg Price       Cost          First Trade          Last Trade")
print("-"*115)

total_cost = 0
total_contracts = 0

for row in cur.fetchall():
    ticker, side, qty, avg_price, cost, first, last = row
    total_cost += cost
    total_contracts += qty
    first_short = first[:19] if first else ""
    last_short = last[:19] if last else ""
    print(f"{ticker:<35} {side.upper():<6} {qty:>8} {avg_price:>9.1f}c ${cost:>8.2f}  {first_short}  {last_short}")

print("-"*115)
print(f"TOTAL: {total_contracts} contracts | Cost Basis: ${total_cost:.2f}")
conn.close()
