from datetime import datetime, timezone
import sqlite3

# Get current time
now = datetime.now(timezone.utc)
utc_str = now.strftime("%Y-%m-%d %H:%M:%S")
est_hour = (now.hour - 5) % 24
est_str = now.strftime("%Y-%m-%d") + " " + str(est_hour) + now.strftime(":%M:%S")
print(f"Current UTC: {utc_str}")
print(f"Current EST: {est_str}")
print()

# Check trade count
conn = sqlite3.connect("integrated_paper_data/paper_trades.db")
cur = conn.cursor()
cur.execute("SELECT COUNT(*), SUM(quantity) FROM trades")
count, qty = cur.fetchone()
print(f"Total Trades: {count}")
print(f"Total Contracts: {qty}")

# Get latest trade
cur.execute("SELECT ticker, side, quantity, price, created_at FROM trades ORDER BY created_at DESC LIMIT 5")
print()
print("Last 5 trades:")
for row in cur.fetchall():
    print(f"  {row[4][:19]} - {row[1].upper()} {row[2]}x {row[0]} @ {row[3]}c")
conn.close()
