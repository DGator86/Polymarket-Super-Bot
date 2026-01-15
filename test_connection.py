#!/usr/bin/env python3
"""Quick test script to verify Kalshi API connection"""

import asyncio
import os
import sys
from pathlib import Path

# Load environment
from dotenv import load_dotenv
load_dotenv()

async def test_kalshi_connection():
    """Test Kalshi API connection with provided credentials"""
    
    print("=" * 50)
    print("Kalshi API Connection Test")
    print("=" * 50)
    
    # Check credentials
    api_key = os.getenv("KALSHI_API_KEY")
    key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH", "./kalshi_private_key.pem")
    
    print(f"\nAPI Key: {api_key[:20]}..." if api_key else "API Key: NOT SET")
    print(f"Key Path: {key_path}")
    print(f"Key Exists: {Path(key_path).exists()}")
    
    if not api_key or not Path(key_path).exists():
        print("\n❌ Missing credentials!")
        return False
    
    # Import connector
    try:
        from connectors.kalshi import KalshiClient
    except ImportError as e:
        print(f"\n❌ Import error: {e}")
        return False
    
    # Test connection
    print("\nConnecting to Kalshi...")
    
    try:
        client = KalshiClient()
        await client.connect()
        
        print("✅ Authentication successful!")
        
        # Get balance
        balance = await client.get_balance()
        print(f"\n📊 Account Balance:")
        print(f"   Available: ${balance.available_balance:.2f}")
        print(f"   Portfolio: ${balance.portfolio_value:.2f}")
        print(f"   Total:     ${balance.total_equity:.2f}")
        
        # Get some markets
        print("\n📈 Fetching open markets...")
        markets = await client.get_markets(status="open", limit=5)
        print(f"   Found {len(markets)} markets (showing first 5)")
        
        for m in markets[:5]:
            ticker = m.get("ticker", "?")
            title = m.get("title", "?")[:50]
            print(f"   - {ticker}: {title}...")
        
        # Get positions
        print("\n📋 Current Positions:")
        positions = await client.get_positions()
        if positions:
            for pos in positions:
                print(f"   - {pos.ticker}: {pos.side.value} x{pos.quantity}")
        else:
            print("   No open positions")
        
        await client.close()
        
        print("\n" + "=" * 50)
        print("✅ All tests passed! API connection working.")
        print("=" * 50)
        return True
        
    except Exception as e:
        print(f"\n❌ Connection failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(test_kalshi_connection())
    sys.exit(0 if success else 1)
