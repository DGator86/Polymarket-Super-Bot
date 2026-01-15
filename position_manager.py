#!/usr/bin/env python3
"""
Position Manager for Kalshi - Early Exit / Sell Positions
Allows selling positions before settlement to lock in profits or cut losses.
"""

import os
import time
import base64
import requests
from pathlib import Path
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


def get_balance() -> dict:
    """Get account balance"""
    path = "/portfolio/balance"
    r = requests.get(BASE_URL + path, headers=get_headers("GET", path))
    return r.json()


def get_positions() -> list:
    """Get all positions"""
    path = "/portfolio/positions"
    r = requests.get(BASE_URL + path, headers=get_headers("GET", path))
    return r.json().get("market_positions", [])


def get_market(ticker: str) -> dict:
    """Get current market data"""
    path = f"/markets/{ticker}"
    r = requests.get(BASE_URL + path, headers=get_headers("GET", path))
    return r.json()


def sell_position(ticker: str, side: str, quantity: int, price: float) -> dict:
    """
    Sell a position by placing a sell order.
    
    Args:
        ticker: Market ticker (e.g., KXBTCD-26JAN1617-T97499.99)
        side: 'yes' or 'no' - which contracts you own
        quantity: Number of contracts to sell
        price: Limit price (use current bid to sell immediately)
    """
    path = "/portfolio/orders"
    
    order_data = {
        "ticker": ticker,
        "type": "limit",
        "action": "sell",
        "side": side.lower(),
        "count": quantity,
    }
    
    # Add the correct price field
    price_cents = int(price * 100)
    if side.lower() == "yes":
        order_data["yes_price"] = price_cents
    else:
        order_data["no_price"] = price_cents
    
    print(f"\n{'='*60}")
    print(f"PLACING SELL ORDER")
    print(f"{'='*60}")
    print(f"  Ticker: {ticker}")
    print(f"  Side: {side.upper()}")
    print(f"  Quantity: {quantity}")
    print(f"  Price: ${price:.2f}")
    print(f"  Order data: {order_data}")
    
    r = requests.post(
        BASE_URL + path,
        headers=get_headers("POST", path),
        json=order_data
    )
    
    data = r.json()
    
    if r.status_code in [200, 201]:
        order = data.get("order", {})
        print(f"\n  SELL ORDER PLACED!")
        print(f"  Order ID: {order.get('order_id', 'unknown')}")
        print(f"  Status: {order.get('status', 'unknown')}")
        return {"success": True, "order": order}
    else:
        error = data.get("error", data)
        print(f"\n  SELL ORDER FAILED!")
        print(f"  Status: {r.status_code}")
        print(f"  Error: {error}")
        return {"success": False, "error": error}


def analyze_positions():
    """Analyze all positions with current market data"""
    bal = get_balance()
    cash = bal.get("balance", 0) / 100
    portfolio = bal.get("portfolio_value", 0) / 100
    
    print(f"\n{'='*60}")
    print(f"ACCOUNT STATUS")
    print(f"{'='*60}")
    print(f"  Cash: ${cash:.2f}")
    print(f"  Portfolio: ${portfolio:.2f}")
    print(f"  Total: ${cash + portfolio:.2f}")
    
    positions = get_positions()
    
    print(f"\n{'='*60}")
    print(f"POSITION ANALYSIS")
    print(f"{'='*60}")
    
    positions_data = []
    total_sell_pnl = 0
    total_win_pnl = 0
    
    for pos in positions:
        ticker = pos.get("ticker", "")
        position_qty = pos.get("position", 0)
        market_exposure = pos.get("market_exposure", 0) / 100
        
        if position_qty == 0:
            continue
        
        # Determine side
        if position_qty > 0:
            side = "YES"
            qty = position_qty
        else:
            side = "NO"
            qty = abs(position_qty)
        
        # Get current market prices
        try:
            market = get_market(ticker)
            market_data = market.get("market", {})
            
            yes_bid = market_data.get("yes_bid", 0) / 100
            yes_ask = market_data.get("yes_ask", 0) / 100
            no_bid = market_data.get("no_bid", 0) / 100
            no_ask = market_data.get("no_ask", 0) / 100
            
            # Cost basis
            cost_basis = market_exposure / qty if qty > 0 else 0
            
            # Current sell price
            sell_price = yes_bid if side == "YES" else no_bid
            
            # P/L if sell now
            sell_value = qty * sell_price
            sell_pnl = sell_value - market_exposure
            total_sell_pnl += sell_pnl
            
            # P/L if win at settlement
            win_value = qty * 1.0
            win_pnl = win_value - market_exposure
            total_win_pnl += win_pnl
            
            # Parse ticker for info
            parts = ticker.split("-")
            expiry = parts[1] if len(parts) > 1 else "unknown"
            strike_str = parts[2] if len(parts) > 2 else "0"
            strike = float(strike_str[1:]) if strike_str[0] in ['T', 'B'] else 0
            
            print(f"\n  {ticker}")
            print(f"  Strike: ${strike:,.2f} | Expires: {expiry}")
            print(f"  Position: {qty} {side}")
            print(f"  Cost: ${cost_basis:.2f}/ea (${market_exposure:.2f} total)")
            print(f"  Current {side} bid: ${sell_price:.2f}")
            print(f"  Sell now: ${sell_value:.2f} | P/L: ${sell_pnl:+.2f}")
            print(f"  Win at settlement: ${win_value:.2f} | P/L: ${win_pnl:+.2f}")
            
            # Status indicator
            if sell_pnl > 0:
                print(f"  >>> PROFITABLE TO SELL NOW!")
            elif sell_price >= cost_basis * 0.95:
                print(f"  >>> Near break-even")
            else:
                print(f"  >>> Underwater (hold if confident)")
            
            positions_data.append({
                "ticker": ticker,
                "side": side,
                "qty": qty,
                "strike": strike,
                "expiry": expiry,
                "cost_basis": cost_basis,
                "market_exposure": market_exposure,
                "sell_price": sell_price,
                "sell_value": sell_value,
                "sell_pnl": sell_pnl,
                "win_pnl": win_pnl,
            })
            
        except Exception as e:
            print(f"  Error getting market data for {ticker}: {e}")
    
    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    print(f"  Total P/L if sell all now: ${total_sell_pnl:+.2f}")
    print(f"  Total P/L if ALL positions win: ${total_win_pnl:+.2f}")
    
    return positions_data


def interactive_sell():
    """Interactive sell mode"""
    positions = analyze_positions()
    
    if not positions:
        print("\nNo positions to sell!")
        return
    
    print(f"\n{'='*60}")
    print(f"SELL MENU")
    print(f"{'='*60}")
    
    for i, pos in enumerate(positions):
        pnl_str = f"${pos['sell_pnl']:+.2f}" if pos['sell_pnl'] >= 0 else f"${pos['sell_pnl']:.2f}"
        print(f"  {i+1}. {pos['ticker']}")
        print(f"     {pos['qty']} {pos['side']} @ ${pos['strike']:,.2f}")
        print(f"     Sell @ ${pos['sell_price']:.2f} -> P/L: {pnl_str}")
    
    print(f"\n  0. Exit without selling")
    print(f"  A. Sell ALL positions")
    
    choice = input("\nEnter number to sell (or 'A' for all): ").strip()
    
    if choice.lower() == 'a':
        confirm = input("Sell ALL positions? Type 'CONFIRM' to proceed: ")
        if confirm.upper() == 'CONFIRM':
            for pos in positions:
                sell_position(
                    pos['ticker'],
                    pos['side'].lower(),
                    pos['qty'],
                    pos['sell_price']
                )
                time.sleep(0.3)  # Rate limit
    elif choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(positions):
            pos = positions[idx]
            
            # Ask for quantity
            qty_str = input(f"Quantity (1-{pos['qty']}, Enter for all): ").strip()
            qty = int(qty_str) if qty_str else pos['qty']
            qty = min(max(1, qty), pos['qty'])
            
            # Ask for price
            price_str = input(f"Price (Enter for ${pos['sell_price']:.2f}): ").strip()
            price = float(price_str) if price_str else pos['sell_price']
            
            confirm = input(f"Sell {qty} {pos['side']} @ ${price:.2f}? (y/n): ").strip()
            if confirm.lower() == 'y':
                sell_position(pos['ticker'], pos['side'].lower(), qty, price)
    
    # Show updated positions
    print("\nUpdated positions:")
    analyze_positions()


def quick_sell(ticker: str, side: str, qty: int, price: float):
    """Quick sell a specific position"""
    print(f"Quick sell: {ticker} {side} {qty} @ ${price:.2f}")
    return sell_position(ticker, side, qty, price)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2 or sys.argv[1] == "analyze":
        analyze_positions()
    elif sys.argv[1] == "interactive":
        interactive_sell()
    elif sys.argv[1] == "sell" and len(sys.argv) >= 6:
        # python position_manager.py sell TICKER SIDE QTY PRICE
        quick_sell(sys.argv[2], sys.argv[3], int(sys.argv[4]), float(sys.argv[5]))
    elif sys.argv[1] == "help":
        print("""
Position Manager for Kalshi

Usage:
    python position_manager.py              # Analyze positions
    python position_manager.py analyze      # Analyze positions  
    python position_manager.py interactive  # Interactive sell mode
    python position_manager.py sell TICKER SIDE QTY PRICE  # Direct sell

Examples:
    python position_manager.py analyze
    python position_manager.py interactive
    python position_manager.py sell KXBTCD-26JAN1617-T97499.99 no 23 0.69
        """)
    else:
        print("Unknown command. Use 'help' for usage.")
