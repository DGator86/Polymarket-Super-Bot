"""
Streamlit Dashboard for Polymarket Bot.
"""
import streamlit as st
import sqlite3
import pandas as pd
import time
from datetime import datetime
import plotly.express as px

# Config
st.set_page_config(
    page_title="Polymarket Bot Tracker",
    page_icon="📈",
    layout="wide",
)

DB_PATH = "bot_state_smart.db"

@st.cache_data(ttl=5)
def get_data():
    """Fetch data from SQLite."""
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        
        # Positions
        positions = pd.read_sql_query("""
            SELECT token_id, qty, avg_cost, realized_pnl 
            FROM positions 
            WHERE qty != 0 OR realized_pnl != 0
        """, conn)
        
        # Fills (limit 100)
        fills = pd.read_sql_query("""
            SELECT ts, side, price, size, fee, token_id
            FROM fills 
            ORDER BY ts DESC 
            LIMIT 100
        """, conn)
        
        # Daily Stats
        today_start = int(datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
        daily = pd.read_sql_query(f"""
            SELECT count(*) as count, sum(fee) as fees, sum(size * price) as volume
            FROM fills 
            WHERE ts >= {today_start}
        """, conn)
        
        conn.close()
        return positions, fills, daily
    except Exception as e:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# Main UI
st.title("📈 Polymarket Smart Survival Bot ($60)")

# Auto-refresh
if st.button('Refresh Data'):
    st.rerun()

# Fetch data
positions, fills, daily = get_data()

# Top Metrics
col1, col2, col3, col4 = st.columns(4)

total_realized_pnl = positions['realized_pnl'].sum() if not positions.empty else 0.0
daily_fees = daily['fees'].iloc[0] if not daily.empty and daily['fees'].iloc[0] else 0.0
daily_vol = daily['volume'].iloc[0] if not daily.empty and daily['volume'].iloc[0] else 0.0
trades_today = daily['count'].iloc[0] if not daily.empty else 0

with col1:
    st.metric("Total Realized PnL", f"${total_realized_pnl:.2f}", delta=None)
with col2:
    st.metric("Trades Today", f"{trades_today}")
with col3:
    st.metric("Volume Today", f"${daily_vol:.2f}")
with col4:
    st.metric("Fees Paid", f"${daily_fees:.4f}")

# Active Positions
st.subheader("Active Positions")
if not positions.empty:
    # Calculate exposure
    positions['exposure'] = abs(positions['qty'] * positions['avg_cost'])
    
    # Format for display
    display_pos = positions.copy()
    display_pos['token_short'] = display_pos['token_id'].apply(lambda x: x[:16] + "...")
    display_pos = display_pos[['token_short', 'qty', 'avg_cost', 'exposure', 'realized_pnl']]
    
    st.dataframe(display_pos, use_container_width=True)
else:
    st.info("No active positions.")

# Recent Fills
st.subheader("Recent Fills")
if not fills.empty:
    fills['time'] = pd.to_datetime(fills['ts'], unit='ms')
    st.dataframe(
        fills[['time', 'side', 'size', 'price', 'fee', 'token_id']],
        use_container_width=True
    )
else:
    st.info("No fills yet.")

st.caption(f"Last updated: {datetime.now().strftime('%H:%M:%S')}")
