#!/usr/bin/env python3
"""
Quick validation script - checks imports and configuration only (no network calls)
"""

import sys
import os

# Set timeout for any blocking calls
os.environ.setdefault('AIOHTTP_TIMEOUT', '5')

def main():
    print("=" * 60)
    print("KALSHI PREDICTION BOT - SETUP VALIDATION")
    print("=" * 60)
    print()
    
    results = []
    
    # Test 1: Configuration
    print("1. Testing configuration loading...")
    try:
        from config import config
        assert config.kalshi.api_key, "Kalshi API key not set"
        print(f"   Kalshi API Key: {config.kalshi.api_key[:8]}...{config.kalshi.api_key[-4:]}")
        print(f"   Private Key Path: {config.kalshi.private_key_path}")
        print(f"   Demo Mode: {config.kalshi.use_demo}")
        results.append(("Configuration", True, "Loaded successfully"))
    except Exception as e:
        results.append(("Configuration", False, str(e)))
    
    # Test 2: RSA Key
    print("\n2. Testing RSA private key...")
    try:
        from pathlib import Path
        key_path = config.kalshi.private_key_path
        assert Path(key_path).exists(), f"Key file not found: {key_path}"
        
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.backends import default_backend
        with open(key_path, "rb") as f:
            private_key = serialization.load_pem_private_key(
                f.read(), password=None, backend=default_backend()
            )
        print(f"   Key loaded: {type(private_key).__name__}")
        results.append(("RSA Key", True, "Valid private key"))
    except Exception as e:
        results.append(("RSA Key", False, str(e)))
    
    # Test 3: Core imports
    print("\n3. Testing core module imports...")
    try:
        from core.models import NormalizedMarket, TradingSignal, OrderRequest
        from core.universe_engine import UniverseEngine
        from core.probability_engine import ProbabilityEngine
        from core.risk_manager import RiskManager
        from core.ml_volatility import VolatilityForecaster
        print("   All core modules imported successfully")
        results.append(("Core Modules", True, "All imports OK"))
    except Exception as e:
        results.append(("Core Modules", False, str(e)))
    
    # Test 4: Connector imports
    print("\n4. Testing connector imports...")
    try:
        from connectors.kalshi import KalshiClient
        from connectors.fred import FREDClient
        from connectors.noaa import NOAAClient
        from connectors.coinbase import CoinbaseClient
        from connectors.bls import BLSClient
        print("   All connectors imported successfully")
        results.append(("Connectors", True, "All imports OK"))
    except Exception as e:
        results.append(("Connectors", False, str(e)))
    
    # Test 5: Strategy imports
    print("\n5. Testing strategy imports...")
    try:
        from strategies.latency_arb import LatencyArbStrategy
        from strategies.multi_timeframe import MultiTimeframeStrategy
        print("   All strategies imported successfully")
        results.append(("Strategies", True, "All imports OK"))
    except Exception as e:
        results.append(("Strategies", False, str(e)))
    
    # Test 6: Utils imports
    print("\n6. Testing utility imports...")
    try:
        from utils.alerts import AlertManager
        from utils.database import DatabaseManager
        print("   All utilities imported successfully")
        results.append(("Utilities", True, "All imports OK"))
    except Exception as e:
        results.append(("Utilities", False, str(e)))
    
    # Test 7: Main entry point
    print("\n7. Testing main entry point...")
    try:
        from main import PredictionBot
        bot = PredictionBot()
        assert bot.dry_run == True, "Dry run should be True by default"
        print(f"   PredictionBot created (dry_run={bot.dry_run})")
        results.append(("Main Entry", True, "Bot class instantiates"))
    except Exception as e:
        results.append(("Main Entry", False, str(e)))
    
    # Summary
    print("\n" + "=" * 60)
    print("VALIDATION SUMMARY")
    print("=" * 60)
    
    passed = 0
    for name, success, msg in results:
        status = "PASS" if success else "FAIL"
        print(f"  [{status}] {name}: {msg}")
        if success:
            passed += 1
    
    print(f"\nResult: {passed}/{len(results)} checks passed")
    
    if passed == len(results):
        print("\n" + "=" * 60)
        print("ALL VALIDATIONS PASSED!")
        print("=" * 60)
        print("\nNext steps:")
        print("  1. Run in dry-run mode: python3 main.py")
        print("  2. Monitor logs: tail -f bot.log")
        print("  3. When confident, set dry_run=False in main.py line 115")
        print("\nAPI Keys that YOU must provide (cannot be auto-generated):")
        print("  - FRED_API_KEY: https://fred.stlouisfed.org/docs/api/api_key.html")
        print("  - BLS_API_KEY: https://www.bls.gov/developers/")
        print("  - COINBASE_API_KEY/SECRET: https://www.coinbase.com/settings/api")
        print("  - TELEGRAM_BOT_TOKEN: Create via @BotFather on Telegram")
        print("  - DISCORD_WEBHOOK_URL: Create in Discord channel settings")
    else:
        print("\nSome validations failed. Please fix the issues above.")
    
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
