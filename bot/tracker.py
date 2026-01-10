"""
Simple P&L and Position Tracker for Polymarket Bot.
Connects to the SQLite database and displays a real-time dashboard.
"""
import sqlite3
import time
import os
import sys
from datetime import datetime
from pathlib import Path

# Config
DB_PATH = "bot_state_smart.db"
REFRESH_RATE = 5  # seconds

def clear_screen():
    """Clear the terminal screen."""
    os.system('cls' if os.name == 'nt' else 'clear')

def get_db_connection():
    """Get read-only connection to the database."""
    if not Path(DB_PATH).exists():
        print(f"Database not found at {DB_PATH}")
        sys.exit(1)
    
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn

def get_positions(conn):
    """Fetch active positions."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT token_id, qty, avg_cost, realized_pnl 
        FROM positions 
        WHERE qty != 0 OR realized_pnl != 0
        ORDER BY abs(qty * avg_cost) DESC
    """)
    return cursor.fetchall()

def get_recent_fills(conn, limit=10):
    """Fetch recent fills."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT side, price, size, fee, ts, token_id
        FROM fills 
        ORDER BY ts DESC 
        LIMIT ?
    """, (limit,))
    return cursor.fetchall()

def get_daily_stats(conn):
    """Calculate daily statistics."""
    cursor = conn.cursor()
    
    # Get today's start timestamp (midnight UTC)
    today_start = int(datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
    
    # Daily Realized PnL from fills
    # Note: This is an approximation. Fills table stores fees but PnL logic is in positions.
    # We can sum realized_pnl from positions if they updated today, or try to reconstruct.
    # Better to query decisions/fills joined or just aggregate fills.
    # Simplified: Sum of (Sell Price - Buy Price) logic is complex without matching.
    # We will rely on the `positions` table `realized_pnl` column which accumulates over time.
    # To get DAILY PnL, we'd need a history of pnl snapshots.
    
    # Alternative: Estimate from fills today
    cursor.execute("""
        SELECT count(*), sum(fee), sum(size * price)
        FROM fills 
        WHERE ts >= ?
    """, (today_start,))
    row = cursor.fetchone()
    num_trades = row[0] if row else 0
    total_fees = row[1] if row and row[1] else 0.0
    volume = row[2] if row and row[2] else 0.0
    
    return {
        "trades": num_trades,
        "fees": total_fees,
        "volume": volume
    }

def print_dashboard(conn):
    """Print the dashboard."""
    clear_screen()
    
    # Header
    print("=" * 80)
    print(f"  POLYMARKET BOT TRACKER - SMART SURVIVAL MODE ($60)")
    print(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    
    # 1. Account / Daily Stats
    stats = get_daily_stats(conn)
    positions = get_positions(conn)
    total_realized_pnl = sum(p['realized_pnl'] for p in positions)
    current_exposure = sum(abs(p['qty'] * p['avg_cost']) for p in positions if p['qty'] != 0)
    
    print(f"\n[ DAILY STATS (Since Midnight UTC) ]")
    print(f"  Trades:       {stats['trades']}")
    print(f"  Volume:       ${stats['volume']:.2f}")
    print(f"  Fees Paid:    ${stats['fees']:.4f}")
    print(f"  Net Exposure: ${current_exposure:.2f}")
    print(f"  Total Realized PnL (All Time): ${total_realized_pnl:.2f}")
    
    # 2. Active Positions
    print(f"\n[ ACTIVE POSITIONS ]")
    print(f"  {'Token ID (Short)':<20} | {'Qty':>10} | {'Avg Entry':>10} | {'Exposure':>10} | {'Realized':>10}")
    print("-" * 80)
    
    if not positions:
        print("  No active positions.")
    
    for p in positions:
        if p['qty'] == 0 and p['realized_pnl'] == 0:
            continue
            
        token_short = p['token_id'][:18] + "..."
        exposure = abs(p['qty'] * p['avg_cost'])
        
        print(f"  {token_short:<20} | {p['qty']:>10.1f} | ${p['avg_cost']:>9.3f} | ${exposure:>9.2f} | ${p['realized_pnl']:>9.2f}")

    # 3. Recent Fills
    print(f"\n[ RECENT FILLS ]")
    print(f"  {'Time':<19} | {'Side':<4} | {'Size':>8} | {'Price':>8} | {'Fee':>8}")
    print("-" * 80)
    
    fills = get_recent_fills(conn)
    if not fills:
        print("  No trades yet.")
        
    for f in fills:
        ts_dt = datetime.fromtimestamp(f['ts'] / 1000)
        ts_str = ts_dt.strftime('%H:%M:%S')
        side = f['side']
        color = "" # Could add ANSI colors here
        
        print(f"  {ts_str:<19} | {side:<4} | {f['size']:>8.1f} | ${f['price']:>7.3f} | ${f['fee']:>7.4f}")
        
    print("\n" + "=" * 80)
    print("  Press Ctrl+C to exit")

def main():
    try:
        while True:
            try:
                conn = get_db_connection()
                print_dashboard(conn)
                conn.close()
            except sqlite3.OperationalError:
                # DB might be locked by the bot writer
                print("\n  Database locked, retrying...")
            except Exception as e:
                print(f"\n  Error: {e}")
            
            time.sleep(REFRESH_RATE)
            
    except KeyboardInterrupt:
        print("\nExiting tracker...")
        sys.exit(0)

if __name__ == "__main__":
    main()
