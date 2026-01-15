#!/usr/bin/env python3
"""
Kalshi Prediction Bot - Local Component Test
Tests components without network calls
"""

import sys
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

def test_imports():
    """Test all module imports"""
    print("Testing module imports...")
    errors = []
    
    try:
        from config import config
        print("  [OK] config")
    except Exception as e:
        errors.append(f"config: {e}")
    
    try:
        from core.models import NormalizedMarket, TradingSignal, Side
        print("  [OK] core.models")
    except Exception as e:
        errors.append(f"core.models: {e}")
    
    try:
        from core.universe_engine import UniverseEngine
        print("  [OK] core.universe_engine")
    except Exception as e:
        errors.append(f"core.universe_engine: {e}")
    
    try:
        from core.probability_engine import ProbabilityEngine
        print("  [OK] core.probability_engine")
    except Exception as e:
        errors.append(f"core.probability_engine: {e}")
    
    try:
        from core.risk_manager import RiskManager
        print("  [OK] core.risk_manager")
    except Exception as e:
        errors.append(f"core.risk_manager: {e}")
    
    try:
        from core.ml_volatility import VolatilityForecaster, get_volatility_forecaster
        print("  [OK] core.ml_volatility")
    except Exception as e:
        errors.append(f"core.ml_volatility: {e}")
    
    try:
        from connectors.kalshi import KalshiClient
        print("  [OK] connectors.kalshi")
    except Exception as e:
        errors.append(f"connectors.kalshi: {e}")
    
    try:
        from connectors.fred import FREDClient
        print("  [OK] connectors.fred")
    except Exception as e:
        errors.append(f"connectors.fred: {e}")
    
    try:
        from connectors.noaa import NOAAClient
        print("  [OK] connectors.noaa")
    except Exception as e:
        errors.append(f"connectors.noaa: {e}")
    
    try:
        from connectors.coinbase import CoinbaseClient
        print("  [OK] connectors.coinbase")
    except Exception as e:
        errors.append(f"connectors.coinbase: {e}")
    
    try:
        from connectors.bls import BLSClient
        print("  [OK] connectors.bls")
    except Exception as e:
        errors.append(f"connectors.bls: {e}")
    
    try:
        from strategies.latency_arb import LatencyArbStrategy
        print("  [OK] strategies.latency_arb")
    except Exception as e:
        errors.append(f"strategies.latency_arb: {e}")
    
    try:
        from strategies.multi_timeframe import MultiTimeframeStrategy
        print("  [OK] strategies.multi_timeframe")
    except Exception as e:
        errors.append(f"strategies.multi_timeframe: {e}")
    
    try:
        from utils.alerts import AlertManager
        print("  [OK] utils.alerts")
    except Exception as e:
        errors.append(f"utils.alerts: {e}")
    
    try:
        from utils.database import DatabaseManager
        print("  [OK] utils.database")
    except Exception as e:
        errors.append(f"utils.database: {e}")
    
    return errors


def test_configuration():
    """Test configuration loading"""
    print("\nTesting configuration...")
    from config import config
    
    checks = {
        "Kalshi API Key": bool(config.kalshi.api_key),
        "Private Key Path Exists": Path(config.kalshi.private_key_path).exists(),
        "Min Edge Valid": 0 < float(config.probability.min_edge_pct) < 1,
        "Kelly Fraction Valid": 0 < float(config.risk.kelly_fraction) <= 1,
        "Max Position Valid": 0 < float(config.risk.max_position_pct) <= 1,
    }
    
    for name, ok in checks.items():
        status = "[OK]" if ok else "[!!]"
        print(f"  {status} {name}")
    
    return sum(not ok for ok in checks.values())


def test_rsa_signing():
    """Test RSA signing capability"""
    print("\nTesting RSA signing...")
    try:
        from config import config
        from cryptography.hazmat.primitives import serialization, hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.backends import default_backend
        import base64
        from datetime import datetime, timezone
        
        key_path = config.kalshi.private_key_path
        with open(key_path, "rb") as f:
            private_key = serialization.load_pem_private_key(
                f.read(), password=None, backend=default_backend()
            )
        
        # Test signing
        timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        message = f"{timestamp_ms}GET/trade-api/v2/portfolio/balance".encode('utf-8')
        
        signature = private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
        
        encoded = base64.b64encode(signature).decode('utf-8')
        print(f"  [OK] RSA-PSS signing works (sig length: {len(encoded)})")
        return 0
    except Exception as e:
        print(f"  [FAIL] RSA signing: {e}")
        return 1


def test_ml_volatility():
    """Test ML volatility forecaster"""
    print("\nTesting ML volatility forecaster...")
    try:
        from core.ml_volatility import get_volatility_forecaster, PriceObservation
        from datetime import datetime, timezone, timedelta
        
        forecaster = get_volatility_forecaster()
        
        # Add simulated data
        now = datetime.now(timezone.utc)
        for i in range(100):
            obs = PriceObservation(
                timestamp=now - timedelta(minutes=100-i),
                price=50000 + (i * 10) + ((-1) ** i * 50)
            )
            forecaster.add_price("BTC-USD", obs)
        
        forecast = forecaster.get_forecast("BTC-USD")
        
        if forecast:
            print(f"  [OK] Forecast: Regime={forecast.regime.value}, Vol={forecast.realized_vol_1h:.2%}")
            return 0
        else:
            print("  [OK] Forecaster initialized (needs more data for full forecast)")
            return 0
    except Exception as e:
        print(f"  [FAIL] ML Volatility: {e}")
        return 1


def test_risk_manager():
    """Test risk manager"""
    print("\nTesting risk manager...")
    try:
        from core.risk_manager import RiskManager
        from core.models import TradingSignal, AccountBalance, Side, SignalType, Venue
        from decimal import Decimal
        from datetime import datetime, timezone
        
        risk = RiskManager()
        
        # Mock balance
        balance = AccountBalance(
            venue=Venue.KALSHI,
            available_balance=Decimal("1000"),
            portfolio_value=Decimal("0"),
            total_equity=Decimal("1000")
        )
        
        risk.update_portfolio(balance, [])
        
        summary = risk.get_portfolio_summary()
        print(f"  [OK] Risk manager initialized")
        print(f"       Total equity: ${summary['total_equity']:.2f}")
        print(f"       Circuit breaker: {summary['circuit_breaker']}")
        return 0
    except Exception as e:
        print(f"  [FAIL] Risk Manager: {e}")
        return 1


def main():
    print("=" * 60)
    print("KALSHI PREDICTION BOT - LOCAL COMPONENT TEST")
    print("=" * 60)
    
    errors = 0
    
    # Test imports
    import_errors = test_imports()
    if import_errors:
        print(f"\nImport errors: {len(import_errors)}")
        for e in import_errors:
            print(f"  - {e}")
        errors += len(import_errors)
    else:
        print("\nAll modules imported successfully!")
    
    # Test configuration
    errors += test_configuration()
    
    # Test RSA signing
    errors += test_rsa_signing()
    
    # Test ML volatility
    errors += test_ml_volatility()
    
    # Test risk manager
    errors += test_risk_manager()
    
    # Summary
    print("\n" + "=" * 60)
    if errors == 0:
        print("ALL LOCAL TESTS PASSED!")
        print("=" * 60)
        print("\nBot is configured correctly.")
        print("Run 'python3 main.py' to start in dry-run mode.")
    else:
        print(f"COMPLETED WITH {errors} ISSUE(S)")
        print("=" * 60)
    
    return errors


if __name__ == "__main__":
    sys.exit(main())
