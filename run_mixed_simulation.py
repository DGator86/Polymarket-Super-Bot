#!/usr/bin/env python3
"""
Mixed Simulation: 1 Real Dataset + 2 Synthetic Datasets
Demonstrates constant data flow setup and backtesting.
"""

import asyncio
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from connectors.coinbase import CoinbaseClient
# Import from our advanced simulation script
from run_advanced_simulation import (
    run_backtest, 
    SyntheticDataGenerator, 
    MarketRegime
)

async def fetch_real_data(days=180):
    """Fetch real 15m candles from Coinbase."""
    client = CoinbaseClient()
    print(f"Fetching {days} days of real BTC 15m data from Coinbase...")
    
    # Coinbase allows max 300 candles per request.
    # 15m candles = 900s.
    # 30 days * 96 candles/day = 2880 candles.
    
    all_candles = []
    end_time = int(datetime.now().timestamp())
    granularity = 900 # 15m
    
    # We want roughly 'days' worth of data.
    # Each request returns up to 300 candles.
    # 300 * 15m = 75 hours ~ 3 days.
    # So we need about days/3 requests.
    
    current_end = end_time
    
    # Loop to fetch older data
    # 60 requests * 3 days ~ 180 days
    for i in range(60): 
        print(f"  Fetching chunk {i+1} ending {datetime.fromtimestamp(current_end)}...")
        try:
             chunk_size = 300 * 900
             current_start = current_end - chunk_size
             
             candles = await client.get_candles(
                 "BTC-USD", 
                 granularity=900, 
                 start=current_start,
                 end=current_end
             )
             
             if not candles:
                 print("  No more candles returned.")
                 break
                 
             all_candles.extend(candles)
             
             times = [c[0] for c in candles]
             if not times:
                 break
                 
             oldest_time = min(times)
             current_end = oldest_time
             
             # Rate limit sleep
             await asyncio.sleep(0.3)
             
             if len(all_candles) >= 180 * 96: # 180 days
                 print(f"  Reached target candle count ({len(all_candles)}).")
                 break
                 
        except Exception as e:
            print(f"Error fetching real data chunk {i}: {e}")
            break
            
    if not all_candles:
        print("Warning: Could not fetch real data. Using fallback.")
        return None
        
    # Convert to DataFrame
    # Coinbase: [time, low, high, open, close, volume]
    df = pd.DataFrame(all_candles, columns=['time', 'low', 'high', 'open', 'close', 'volume'])
    # Deduplicate just in case
    df = df.drop_duplicates(subset=['time'])
    df['timestamp'] = pd.to_datetime(df['time'], unit='s')
    df['price'] = df['close']
    df = df.sort_values('timestamp')
    
    print(f"Successfully fetched {len(df)} real candles spanning {df['timestamp'].min()} to {df['timestamp'].max()}.")
    return df

async def main():
    # 1. Setup APIs & Data Flow (Demonstration)
    print("="*60)
    print("STEP 1: API SETUP & CONSTANT DATA FLOW")
    print("="*60)
    # Start a background stream task (mock for 5 seconds to show it works)
    client = CoinbaseClient()
    print("Starting background WebSocket stream for BTC, ETH, SOL...")
    
    async def price_callback(price):
        print(f"  [STREAM] {price.symbol}: ${price.price:,.2f}")

    # We run this for a few seconds to demonstrate "constant flow"
    stream_task = asyncio.create_task(
        client.stream_prices(["BTC-USD", "ETH-USD", "SOL-USD"], price_callback)
    )
    await asyncio.sleep(5)
    stream_task.cancel()
    try:
        await stream_task
    except asyncio.CancelledError:
        print("Stream stopped for backtest phase.")
    
    # 2. Run Backtests
    print("\n" + "="*60)
    print("STEP 2: RUNNING 3-WAY SIMULATION")
    print("="*60)
    
    # A. Real Data
    df_real = await fetch_real_data()
    if df_real is not None:
        run_backtest(df_real, "REAL DATA (BTC-USD Live)")
    else:
        # Fallback if API fails
        gen = SyntheticDataGenerator(start_price=60000, daily_vol=0.03)
        df_fallback = gen.generate(days=30)
        run_backtest(df_fallback, "REAL DATA (Fallback Synthetic)")

    # B. Synthetic Trending (Force high trending probability)
    print("\nGenerating Synthetic Trending Data...")
    gen_trend = SyntheticDataGenerator(daily_vol=0.04)
    # We hack the generator in the other file by class inheritance or just parameter
    # Actually, the generator in run_advanced_simulation mixes regimes.
    # We will accept the mixed generation but label it "Synthetic Mixed 1".
    # Or ideally, we'd subclass to force regimes, but let's stick to the prompt:
    # "2 synthetic data". The generator provides realistic mixed data.
    # We will generate two distinct "universes" (seeds implicitly different).
    
    df_syn1 = gen_trend.generate(days=180)
    run_backtest(df_syn1, "SYNTHETIC UNIVERSE 1 (Long-term)")
    
    df_syn2 = gen_trend.generate(days=60)
    run_backtest(df_syn2, "SYNTHETIC UNIVERSE 2 (Short-term)")

if __name__ == "__main__":
    asyncio.run(main())
