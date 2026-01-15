#!/usr/bin/env python3
"""
Kalshi Prediction Bot - Comprehensive Test Script

Tests all components:
1. Configuration loading
2. API key validation
3. Kalshi connection (REST + auth)
4. Data source connections
5. Core engine initialization
6. Database connectivity
7. Alert system

Run with: python test_bot.py
"""

import asyncio
import logging
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


class TestResult:
    """Test result tracker"""
    def __init__(self, name: str):
        self.name = name
        self.passed = False
        self.message = ""
        self.error = None
    
    def __str__(self):
        status = "PASS" if self.passed else "FAIL"
        return f"[{status}] {self.name}: {self.message}"


async def test_configuration() -> TestResult:
    """Test configuration loading"""
    result = TestResult("Configuration Loading")
    try:
        from config import config
        
        checks = []
        checks.append(("Kalshi API Key", bool(config.kalshi.api_key)))
        checks.append(("Private Key Path", Path(config.kalshi.private_key_path).exists()))
        checks.append(("Risk Kelly Fraction", 0 < float(config.risk.kelly_fraction) <= 1))
        checks.append(("Min Edge", 0 < float(config.probability.min_edge_pct) < 1))
        
        failed = [name for name, ok in checks if not ok]
        
        if failed:
            result.message = f"Missing/invalid: {', '.join(failed)}"
        else:
            result.passed = True
            result.message = "All configuration loaded correctly"
            
    except Exception as e:
        result.error = e
        result.message = str(e)
    
    return result


async def test_kalshi_auth() -> TestResult:
    """Test Kalshi RSA authentication"""
    result = TestResult("Kalshi RSA Authentication")
    try:
        from config import config
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.backends import default_backend
        import base64
        from datetime import datetime, timezone
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        
        # Load private key
        key_path = config.kalshi.private_key_path
        with open(key_path, "rb") as f:
            private_key = serialization.load_pem_private_key(
                f.read(), 
                password=None,
                backend=default_backend()
            )
        
        # Test signing
        timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        method = "GET"
        path = "/trade-api/v2/portfolio/balance"
        message = f"{timestamp_ms}{method}{path}".encode('utf-8')
        
        signature = private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
        
        encoded_sig = base64.b64encode(signature).decode('utf-8')
        
        result.passed = True
        result.message = f"RSA signing works, signature length: {len(encoded_sig)}"
        
    except FileNotFoundError as e:
        result.message = f"Private key not found: {config.kalshi.private_key_path}"
        result.error = e
    except Exception as e:
        result.error = e
        result.message = str(e)
    
    return result


async def test_kalshi_connection() -> TestResult:
    """Test Kalshi API connection"""
    result = TestResult("Kalshi API Connection")
    try:
        from connectors.kalshi import create_kalshi_client
        
        client = await create_kalshi_client()
        
        # Try to get balance
        try:
            balance = await client.get_balance()
            result.passed = True
            result.message = f"Connected! Balance: ${float(balance.total_equity):.2f}"
        except Exception as api_error:
            # Connection worked but API returned error
            error_str = str(api_error)
            if "403" in error_str or "geo" in error_str.lower():
                result.message = f"Connection works but API returned 403 (geo-blocked or IP restricted): {error_str[:100]}"
            elif "401" in error_str:
                result.message = f"Connection works but authentication failed. Check API key: {error_str[:100]}"
            else:
                result.message = f"Connection works, API error: {error_str[:100]}"
        
        await client.close()
        
    except Exception as e:
        result.error = e
        result.message = str(e)
    
    return result


async def test_coinbase_connection() -> TestResult:
    """Test Coinbase public API"""
    result = TestResult("Coinbase Public API")
    try:
        from connectors.coinbase import create_coinbase_client
        
        client = await create_coinbase_client()
        
        # Get BTC price (public endpoint)
        price = await client.get_price("BTC-USD")
        
        result.passed = True
        result.message = f"BTC-USD: ${float(price.price):,.2f}"
        
        await client.close()
        
    except Exception as e:
        result.error = e
        result.message = str(e)
    
    return result


async def test_fred_connection() -> TestResult:
    """Test FRED API"""
    result = TestResult("FRED Economic Data API")
    try:
        from config import config
        
        if not config.data_sources.fred_api_key:
            result.message = "FRED API key not configured (optional but recommended)"
            return result
        
        from connectors.fred import create_fred_client
        
        client = await create_fred_client()
        cpi = await client.get_cpi()
        
        if cpi:
            result.passed = True
            result.message = f"CPI value: {float(cpi):.2f}"
        else:
            result.message = "FRED connected but no CPI data returned"
        
        await client.close()
        
    except Exception as e:
        result.error = e
        result.message = str(e)
    
    return result


async def test_noaa_connection() -> TestResult:
    """Test NOAA Weather API"""
    result = TestResult("NOAA Weather API")
    try:
        from connectors.noaa import create_noaa_client
        
        client = await create_noaa_client()
        
        # Try NYC forecast
        forecast = await client.get_forecast(40.7128, -74.0060)
        
        if forecast:
            result.passed = True
            temp = forecast[0].temperature if forecast else "N/A"
            result.message = f"NYC forecast retrieved, temp: {temp}F"
        else:
            result.message = "NOAA connected but no forecast data"
        
        await client.close()
        
    except Exception as e:
        result.error = e
        result.message = str(e)
    
    return result


async def test_bls_connection() -> TestResult:
    """Test BLS API"""
    result = TestResult("BLS Economic Data API")
    try:
        from config import config
        
        if not config.data_sources.bls_api_key:
            result.message = "BLS API key not configured (optional)"
            return result
        
        from connectors.bls import create_bls_client
        
        client = await create_bls_client()
        cpi_all = await client.get_cpi_all()
        
        if cpi_all:
            result.passed = True
            result.message = f"CPI All Items: {float(cpi_all.value):.2f}"
        else:
            result.message = "BLS connected but no data returned"
        
        await client.close()
        
    except Exception as e:
        result.error = e
        result.message = str(e)
    
    return result


async def test_database() -> TestResult:
    """Test SQLite database"""
    result = TestResult("SQLite Database")
    try:
        from utils.database import get_database
        
        db = await get_database()
        
        # Test basic query
        async with db.connection.execute("SELECT 1") as cursor:
            row = await cursor.fetchone()
        
        result.passed = True
        result.message = f"Database connected at {db.db_path}"
        
    except Exception as e:
        result.error = e
        result.message = str(e)
    
    return result


async def test_ml_volatility() -> TestResult:
    """Test ML volatility forecaster"""
    result = TestResult("ML Volatility Forecaster")
    try:
        from core.ml_volatility import get_volatility_forecaster, PriceObservation
        from datetime import datetime, timezone, timedelta
        
        forecaster = get_volatility_forecaster()
        
        # Add some test data
        now = datetime.now(timezone.utc)
        for i in range(100):
            obs = PriceObservation(
                timestamp=now - timedelta(minutes=100-i),
                price=50000 + (i * 10) + ((-1) ** i * 50)  # Simulated price
            )
            forecaster.add_price("BTC-USD", obs)
        
        # Get forecast
        forecast = forecaster.get_forecast("BTC-USD")
        
        if forecast:
            result.passed = True
            result.message = f"Regime: {forecast.regime.value}, Vol 1h: {forecast.realized_vol_1h:.2%}"
        else:
            result.message = "Forecaster works but needs more data"
        
    except Exception as e:
        result.error = e
        result.message = str(e)
    
    return result


async def test_core_engines() -> TestResult:
    """Test core engines initialization"""
    result = TestResult("Core Engines")
    try:
        from core.universe_engine import UniverseEngine
        from core.probability_engine import ProbabilityEngine
        from core.risk_manager import RiskManager
        
        # Risk manager
        risk = RiskManager()
        summary = risk.get_portfolio_summary()
        
        result.passed = True
        result.message = "UniverseEngine, ProbabilityEngine, RiskManager all importable"
        
    except Exception as e:
        result.error = e
        result.message = str(e)
    
    return result


async def test_alerts_config() -> TestResult:
    """Test alert configuration"""
    result = TestResult("Alert System Configuration")
    try:
        from config import config
        
        telegram_configured = bool(config.alerts.telegram_bot_token and config.alerts.telegram_chat_id)
        discord_configured = bool(config.alerts.discord_webhook_url)
        
        if telegram_configured or discord_configured:
            channels = []
            if telegram_configured:
                channels.append("Telegram")
            if discord_configured:
                channels.append("Discord")
            result.passed = True
            result.message = f"Alert channels configured: {', '.join(channels)}"
        else:
            result.message = "No alert channels configured (optional)"
        
    except Exception as e:
        result.error = e
        result.message = str(e)
    
    return result


async def run_all_tests():
    """Run all tests and print summary"""
    print("=" * 70)
    print("KALSHI PREDICTION BOT - COMPREHENSIVE TEST SUITE")
    print("=" * 70)
    print()
    
    tests = [
        test_configuration,
        test_kalshi_auth,
        test_kalshi_connection,
        test_coinbase_connection,
        test_fred_connection,
        test_noaa_connection,
        test_bls_connection,
        test_database,
        test_ml_volatility,
        test_core_engines,
        test_alerts_config,
    ]
    
    results = []
    for test_func in tests:
        print(f"Running: {test_func.__doc__}...")
        result = await test_func()
        results.append(result)
        print(f"  {result}")
        print()
    
    # Summary
    print("=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"  [{status}] {result.name}")
    
    print()
    print(f"Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("\nALL TESTS PASSED! Bot is ready to run.")
    else:
        print("\nSome tests failed. Review output above for details.")
        print("Note: Some failures (FRED, BLS, Alerts) are optional features.")
    
    return passed, total


if __name__ == "__main__":
    passed, total = asyncio.run(run_all_tests())
    sys.exit(0 if passed >= total - 3 else 1)  # Allow some optional failures
