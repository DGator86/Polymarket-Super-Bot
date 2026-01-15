#!/usr/bin/env python3
"""
Position Guardian - Auto-Exit Protection System
Monitors positions and automatically sells when price approaches strike to protect profits.

Key features:
- Monitors real-time crypto prices from multiple exchanges
- Compares against your position strikes
- Auto-sells if price gets too close to strike (configurable buffer)
- Protects winning positions from turning into losses
"""

import os
import sys
import time
import json
import base64
import asyncio
import aiohttp
import requests
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Dict, List, Optional
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding

# Load environment
env_path = Path("/opt/kalshi-latency-bot/.env")
if env_path.exists():
    for line in open(env_path):
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            os.environ.setdefault(k, v)

API_KEY = os.getenv("KALSHI_API_KEY")
KEY_PATH = "/opt/kalshi-latency-bot/kalshi_private_key.pem"
BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

# Load private key
with open(KEY_PATH, "rb") as f:
    PRIVATE_KEY = serialization.load_pem_private_key(f.read(), password=None)

# =============================================================================
# CONFIGURATION - Auto-Exit Thresholds
# =============================================================================

# How close price can get to strike before auto-selling (as percentage of strike)
# e.g., 0.005 = 0.5% buffer -> for $97,500 strike, sell if BTC reaches $97,012
EXIT_BUFFER_PERCENT = 0.005  # 0.5% buffer

# Minimum profit percentage to protect (only protect if we're making money)
MIN_PROFIT_TO_PROTECT = 0.0  # 0% - protect all positions

# How often to check prices (seconds)
CHECK_INTERVAL = 2

# Price sources
PRICE_SOURCES = [
    "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
    "https://api.binance.us/api/v3/ticker/price?symbol=BTCUSD",
    "https://api.coinbase.com/v2/prices/BTC-USD/spot",
]

ETH_PRICE_SOURCES = [
    "https://api.binance.com/api/v3/ticker/price?symbol=ETHUSDT",
    "https://api.coinbase.com/v2/prices/ETH-USD/spot",
]


# =============================================================================
# Kalshi API Functions
# =============================================================================

def sign(msg: str) -> str:
    """Sign message using RSA-PSS"""
    sig = PRIVATE_KEY.sign(
        msg.encode(),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH
        ),
        hashes.SHA256()
    )
    return base64.b64encode(sig).decode()


def get_headers(method: str, path: str) -> dict:
    """Generate auth headers for Kalshi API"""
    ts = str(int(time.time() * 1000))
    msg = ts + method + "/trade-api/v2" + path
    return {
        "Content-Type": "application/json",
        "KALSHI-ACCESS-KEY": API_KEY,
        "KALSHI-ACCESS-SIGNATURE": sign(msg),
        "KALSHI-ACCESS-TIMESTAMP": ts,
    }


def get_positions() -> list:
    """Get all positions"""
    path = "/portfolio/positions"
    r = requests.get(BASE_URL + path, headers=get_headers("GET", path), timeout=10)
    if r.status_code == 200:
        return r.json().get("market_positions", [])
    return []


def get_market(ticker: str) -> dict:
    """Get current market data"""
    path = f"/markets/{ticker}"
    r = requests.get(BASE_URL + path, headers=get_headers("GET", path), timeout=10)
    if r.status_code == 200:
        return r.json()
    return {}


def sell_position(ticker: str, side: str, quantity: int, price: float) -> dict:
    """Sell a position"""
    path = "/portfolio/orders"
    
    order_data = {
        "ticker": ticker,
        "type": "limit",
        "action": "sell",
        "side": side.lower(),
        "count": quantity,
    }
    
    price_cents = int(price * 100)
    if side.lower() == "yes":
        order_data["yes_price"] = price_cents
    else:
        order_data["no_price"] = price_cents
    
    r = requests.post(
        BASE_URL + path,
        headers=get_headers("POST", path),
        json=order_data,
        timeout=10
    )
    
    return r.json()


# =============================================================================
# Price Fetching
# =============================================================================

async def fetch_btc_price() -> Optional[float]:
    """Fetch BTC price from multiple sources"""
    prices = []
    
    async with aiohttp.ClientSession() as session:
        # Binance
        try:
            async with session.get(
                "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    prices.append(float(data["price"]))
        except:
            pass
        
        # Coinbase
        try:
            async with session.get(
                "https://api.coinbase.com/v2/prices/BTC-USD/spot",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    prices.append(float(data["data"]["amount"]))
        except:
            pass
        
        # Kraken
        try:
            async with session.get(
                "https://api.kraken.com/0/public/Ticker?pair=XBTUSD",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    result = data.get("result", {})
                    if "XXBTZUSD" in result:
                        prices.append(float(result["XXBTZUSD"]["c"][0]))
        except:
            pass
    
    if prices:
        return sum(prices) / len(prices)
    return None


async def fetch_eth_price() -> Optional[float]:
    """Fetch ETH price from multiple sources"""
    prices = []
    
    async with aiohttp.ClientSession() as session:
        # Binance
        try:
            async with session.get(
                "https://api.binance.com/api/v3/ticker/price?symbol=ETHUSDT",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    prices.append(float(data["price"]))
        except:
            pass
        
        # Coinbase
        try:
            async with session.get(
                "https://api.coinbase.com/v2/prices/ETH-USD/spot",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    prices.append(float(data["data"]["amount"]))
        except:
            pass
    
    if prices:
        return sum(prices) / len(prices)
    return None


# =============================================================================
# Position Guardian
# =============================================================================

@dataclass
class MonitoredPosition:
    ticker: str
    side: str  # YES or NO
    qty: int
    strike: float
    cost_basis: float
    expiry: str
    asset: str  # BTC or ETH
    exit_trigger: float  # Price that triggers exit


class PositionGuardian:
    def __init__(self, exit_buffer: float = EXIT_BUFFER_PERCENT):
        self.exit_buffer = exit_buffer
        self.positions: Dict[str, MonitoredPosition] = {}
        self.running = False
        self.sold_positions = set()  # Track what we've already sold
    
    def parse_ticker(self, ticker: str) -> tuple:
        """Parse ticker to extract asset, expiry, strike"""
        # Format: KXBTCD-26JAN1617-T97499.99
        parts = ticker.split("-")
        if len(parts) < 3:
            return None, None, None
        
        asset_code = parts[0]
        expiry = parts[1]
        strike_str = parts[2]
        
        # Determine asset
        if "BTC" in asset_code:
            asset = "BTC"
        elif "ETH" in asset_code:
            asset = "ETH"
        else:
            asset = None
        
        # Parse strike
        if strike_str.startswith("T") or strike_str.startswith("B"):
            try:
                strike = float(strike_str[1:])
            except:
                strike = None
        else:
            strike = None
        
        return asset, expiry, strike
    
    def load_positions(self):
        """Load current positions from Kalshi"""
        print(f"\n{'='*60}")
        print(f"LOADING POSITIONS")
        print(f"{'='*60}")
        
        try:
            positions = get_positions()
        except Exception as e:
            print(f"Error loading positions: {e}")
            return
        
        self.positions = {}
        
        for pos in positions:
            ticker = pos.get("ticker", "")
            position_qty = pos.get("position", 0)
            market_exposure = pos.get("market_exposure", 0) / 100
            
            if position_qty == 0:
                continue
            
            # Skip already sold
            if ticker in self.sold_positions:
                continue
            
            # Determine side and quantity
            if position_qty > 0:
                side = "YES"
                qty = position_qty
            else:
                side = "NO"
                qty = abs(position_qty)
            
            # Parse ticker
            asset, expiry, strike = self.parse_ticker(ticker)
            if not all([asset, expiry, strike]):
                print(f"  Skipping unparseable ticker: {ticker}")
                continue
            
            cost_basis = market_exposure / qty if qty > 0 else 0
            
            # Calculate exit trigger
            # For NO positions: exit if price rises TOWARD strike
            # For YES positions: exit if price falls TOWARD strike
            buffer_amount = strike * self.exit_buffer
            
            if side == "NO":
                # Betting price stays BELOW strike
                # Exit if price gets within buffer of strike (from below)
                exit_trigger = strike - buffer_amount
            else:
                # Betting price stays ABOVE strike
                # Exit if price gets within buffer of strike (from above)
                exit_trigger = strike + buffer_amount
            
            monitored = MonitoredPosition(
                ticker=ticker,
                side=side,
                qty=qty,
                strike=strike,
                cost_basis=cost_basis,
                expiry=expiry,
                asset=asset,
                exit_trigger=exit_trigger,
            )
            
            self.positions[ticker] = monitored
            
            print(f"\n  {ticker}")
            print(f"  {qty} {side} @ ${strike:,.2f}")
            print(f"  Cost: ${cost_basis:.2f}/ea")
            print(f"  Exit trigger: ${exit_trigger:,.2f}")
            if side == "NO":
                print(f"  (Will sell if {asset} rises above ${exit_trigger:,.2f})")
            else:
                print(f"  (Will sell if {asset} falls below ${exit_trigger:,.2f})")
        
        print(f"\n  Monitoring {len(self.positions)} positions")
    
    async def check_and_protect(self) -> List[str]:
        """Check prices and sell if needed"""
        actions = []
        
        # Fetch current prices
        btc_price = await fetch_btc_price()
        eth_price = await fetch_eth_price()
        
        if not btc_price:
            print("  WARNING: Could not fetch BTC price")
            return actions
        
        prices = {"BTC": btc_price, "ETH": eth_price}
        
        for ticker, pos in list(self.positions.items()):
            current_price = prices.get(pos.asset)
            if not current_price:
                continue
            
            should_exit = False
            reason = ""
            
            if pos.side == "NO":
                # Betting price stays BELOW strike
                # Exit if price rises above our exit trigger
                if current_price >= pos.exit_trigger:
                    should_exit = True
                    reason = f"{pos.asset} ${current_price:,.2f} >= trigger ${pos.exit_trigger:,.2f}"
            else:
                # Betting price stays ABOVE strike
                # Exit if price falls below our exit trigger
                if current_price <= pos.exit_trigger:
                    should_exit = True
                    reason = f"{pos.asset} ${current_price:,.2f} <= trigger ${pos.exit_trigger:,.2f}"
            
            if should_exit:
                print(f"\n{'!'*60}")
                print(f"AUTO-EXIT TRIGGERED!")
                print(f"{'!'*60}")
                print(f"  Position: {ticker}")
                print(f"  Reason: {reason}")
                print(f"  Strike: ${pos.strike:,.2f}")
                print(f"  Current {pos.asset}: ${current_price:,.2f}")
                
                # Get current market bid
                try:
                    market = get_market(ticker)
                    market_data = market.get("market", {})
                    
                    if pos.side == "YES":
                        sell_price = market_data.get("yes_bid", 0) / 100
                    else:
                        sell_price = market_data.get("no_bid", 0) / 100
                    
                    if sell_price > 0:
                        print(f"  Selling {pos.qty} {pos.side} @ ${sell_price:.2f}")
                        
                        result = sell_position(ticker, pos.side, pos.qty, sell_price)
                        
                        if result.get("order"):
                            print(f"  SOLD! Order ID: {result['order'].get('order_id')}")
                            self.sold_positions.add(ticker)
                            del self.positions[ticker]
                            actions.append(f"SOLD {ticker}")
                        else:
                            error = result.get("error", result)
                            print(f"  SELL FAILED: {error}")
                            actions.append(f"SELL FAILED {ticker}: {error}")
                    else:
                        print(f"  No bid available for {pos.side}")
                        
                except Exception as e:
                    print(f"  Error selling: {e}")
                    actions.append(f"ERROR {ticker}: {e}")
        
        return actions
    
    async def run(self):
        """Main monitoring loop"""
        print(f"\n{'='*60}")
        print(f"POSITION GUARDIAN STARTED")
        print(f"Exit buffer: {self.exit_buffer*100:.1f}%")
        print(f"Check interval: {CHECK_INTERVAL}s")
        print(f"{'='*60}")
        
        self.load_positions()
        
        if not self.positions:
            print("\nNo positions to monitor!")
            return
        
        self.running = True
        check_count = 0
        
        while self.running and self.positions:
            try:
                # Fetch prices
                btc_price = await fetch_btc_price()
                eth_price = await fetch_eth_price()
                
                check_count += 1
                timestamp = datetime.now().strftime("%H:%M:%S")
                
                # Status line
                btc_str = f"${btc_price:,.0f}" if btc_price else "N/A"
                eth_str = f"${eth_price:,.0f}" if eth_price else "N/A"
                print(f"\r[{timestamp}] BTC: {btc_str} | ETH: {eth_str} | Monitoring {len(self.positions)} positions", end="", flush=True)
                
                # Check for exit triggers
                actions = await self.check_and_protect()
                
                if actions:
                    print()  # New line after status
                    for action in actions:
                        print(f"  ACTION: {action}")
                
                # Reload positions periodically
                if check_count % 30 == 0:  # Every ~60 seconds
                    print(f"\n  Reloading positions...")
                    self.load_positions()
                
                await asyncio.sleep(CHECK_INTERVAL)
                
            except KeyboardInterrupt:
                print("\n\nStopping guardian...")
                self.running = False
            except Exception as e:
                print(f"\n  Error in monitoring loop: {e}")
                await asyncio.sleep(5)
        
        print(f"\n{'='*60}")
        print(f"POSITION GUARDIAN STOPPED")
        print(f"{'='*60}")


def show_status():
    """Show current position status without monitoring"""
    print(f"\n{'='*60}")
    print(f"POSITION STATUS CHECK")
    print(f"{'='*60}")
    
    guardian = PositionGuardian()
    guardian.load_positions()
    
    # Fetch prices
    btc_price = asyncio.run(fetch_btc_price())
    eth_price = asyncio.run(fetch_eth_price())
    
    print(f"\n{'='*60}")
    print(f"CURRENT PRICES")
    print(f"{'='*60}")
    print(f"  BTC: ${btc_price:,.2f}" if btc_price else "  BTC: N/A")
    print(f"  ETH: ${eth_price:,.2f}" if eth_price else "  ETH: N/A")
    
    print(f"\n{'='*60}")
    print(f"EXIT TRIGGER ANALYSIS")
    print(f"{'='*60}")
    
    prices = {"BTC": btc_price, "ETH": eth_price}
    
    for ticker, pos in guardian.positions.items():
        current = prices.get(pos.asset)
        if not current:
            continue
        
        distance = abs(current - pos.strike)
        distance_pct = distance / pos.strike * 100
        trigger_distance = abs(current - pos.exit_trigger)
        
        print(f"\n  {ticker}")
        print(f"  {pos.qty} {pos.side} @ strike ${pos.strike:,.2f}")
        print(f"  Current {pos.asset}: ${current:,.2f}")
        print(f"  Distance to strike: ${distance:,.2f} ({distance_pct:.2f}%)")
        print(f"  Exit trigger: ${pos.exit_trigger:,.2f}")
        print(f"  Distance to trigger: ${trigger_distance:,.2f}")
        
        if pos.side == "NO":
            if current < pos.exit_trigger:
                print(f"  STATUS: SAFE (price below trigger)")
            else:
                print(f"  STATUS: DANGER! Would trigger exit!")
        else:
            if current > pos.exit_trigger:
                print(f"  STATUS: SAFE (price above trigger)")
            else:
                print(f"  STATUS: DANGER! Would trigger exit!")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "status":
            show_status()
        elif sys.argv[1] == "help":
            print("""
Position Guardian - Auto-Exit Protection

Usage:
    python position_guardian.py          # Start monitoring (default)
    python position_guardian.py monitor  # Start monitoring
    python position_guardian.py status   # Check status only
    python position_guardian.py help     # Show this help

Configuration (edit at top of file):
    EXIT_BUFFER_PERCENT = 0.005  # 0.5% buffer from strike
    CHECK_INTERVAL = 2           # Check every 2 seconds

Example:
    For a NO position at $97,500 strike with 0.5% buffer:
    - Exit trigger = $97,500 - ($97,500 * 0.005) = $97,012.50
    - If BTC rises above $97,012.50, position will be sold
            """)
        else:
            guardian = PositionGuardian()
            asyncio.run(guardian.run())
    else:
        guardian = PositionGuardian()
        asyncio.run(guardian.run())
