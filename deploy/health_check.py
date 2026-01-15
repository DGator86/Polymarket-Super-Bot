#!/usr/bin/env python3
"""
Kalshi Prediction Bot - Health Check Script

Checks:
- Bot process running
- Kalshi API connectivity
- Database accessibility
- Recent activity

Usage:
    python health_check.py
    python health_check.py --json
"""

import asyncio
import json
import sys
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import config


class HealthCheck:
    """Health check runner"""
    
    def __init__(self):
        self.checks = {}
        self.overall_status = "healthy"
    
    async def run_all(self):
        """Run all health checks"""
        await self.check_kalshi_api()
        await self.check_database()
        await self.check_data_sources()
        await self.check_disk_space()
        self.check_config()
        
        # Determine overall status
        statuses = [c.get("status") for c in self.checks.values()]
        if "error" in statuses:
            self.overall_status = "unhealthy"
        elif "warning" in statuses:
            self.overall_status = "degraded"
        
        return self.overall_status
    
    async def check_kalshi_api(self):
        """Check Kalshi API connectivity"""
        try:
            from connectors.kalshi import KalshiClient
            
            client = KalshiClient()
            await client.connect()
            balance = await client.get_balance()
            await client.close()
            
            self.checks["kalshi_api"] = {
                "status": "ok",
                "message": f"Connected. Balance: ${balance.total_equity:.2f}",
                "details": {
                    "balance": float(balance.total_equity),
                    "available": float(balance.available_balance)
                }
            }
        except Exception as e:
            self.checks["kalshi_api"] = {
                "status": "error",
                "message": f"Connection failed: {str(e)}"
            }
    
    async def check_database(self):
        """Check database accessibility"""
        try:
            import aiosqlite
            
            db_path = config.database.path
            
            if not Path(db_path).exists():
                self.checks["database"] = {
                    "status": "warning",
                    "message": "Database file not found (will be created on first run)"
                }
                return
            
            async with aiosqlite.connect(db_path) as db:
                # Check tables exist
                cursor = await db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
                tables = [row[0] for row in await cursor.fetchall()]
                
                # Count recent trades
                cursor = await db.execute(
                    "SELECT COUNT(*) FROM trades WHERE entry_time > datetime('now', '-24 hours')"
                )
                recent_trades = (await cursor.fetchone())[0]
                
                # Get database size
                db_size = Path(db_path).stat().st_size / (1024 * 1024)  # MB
            
            self.checks["database"] = {
                "status": "ok",
                "message": f"Connected. {len(tables)} tables, {recent_trades} trades in 24h",
                "details": {
                    "tables": tables,
                    "recent_trades": recent_trades,
                    "size_mb": round(db_size, 2)
                }
            }
        except Exception as e:
            self.checks["database"] = {
                "status": "error",
                "message": f"Database error: {str(e)}"
            }
    
    async def check_data_sources(self):
        """Check external data source connectivity"""
        data_sources = {}
        
        # FRED
        if config.data_sources.fred_api_key:
            try:
                from connectors.fred import FREDClient
                client = FREDClient()
                await client.connect()
                cpi = await client.get_cpi()
                await client.close()
                data_sources["fred"] = {
                    "status": "ok",
                    "message": f"CPI: {cpi.value}" if cpi else "Connected"
                }
            except Exception as e:
                data_sources["fred"] = {"status": "error", "message": str(e)}
        else:
            data_sources["fred"] = {"status": "warning", "message": "Not configured"}
        
        # Coinbase (public API)
        try:
            from connectors.coinbase import CoinbaseClient
            client = CoinbaseClient()
            await client.connect()
            price = await client.get_btc_price()
            await client.close()
            data_sources["coinbase"] = {
                "status": "ok",
                "message": f"BTC: ${price.price:,.0f}"
            }
        except Exception as e:
            data_sources["coinbase"] = {"status": "error", "message": str(e)}
        
        # NOAA (public API)
        try:
            from connectors.noaa import NOAAClient
            client = NOAAClient()
            await client.connect()
            # Just verify we can connect
            await client.close()
            data_sources["noaa"] = {"status": "ok", "message": "Connected"}
        except Exception as e:
            data_sources["noaa"] = {"status": "warning", "message": str(e)}
        
        self.checks["data_sources"] = {
            "status": "ok" if all(d.get("status") == "ok" for d in data_sources.values()) else "warning",
            "details": data_sources
        }
    
    async def check_disk_space(self):
        """Check disk space"""
        try:
            import shutil
            
            total, used, free = shutil.disk_usage("/")
            free_gb = free / (1024 ** 3)
            free_pct = (free / total) * 100
            
            if free_pct < 5:
                status = "error"
                message = f"Critical: Only {free_pct:.1f}% free ({free_gb:.1f} GB)"
            elif free_pct < 10:
                status = "warning"
                message = f"Low disk space: {free_pct:.1f}% free ({free_gb:.1f} GB)"
            else:
                status = "ok"
                message = f"{free_pct:.1f}% free ({free_gb:.1f} GB)"
            
            self.checks["disk_space"] = {
                "status": status,
                "message": message,
                "details": {
                    "free_gb": round(free_gb, 2),
                    "free_pct": round(free_pct, 2)
                }
            }
        except Exception as e:
            self.checks["disk_space"] = {
                "status": "warning",
                "message": f"Could not check disk space: {e}"
            }
    
    def check_config(self):
        """Check configuration"""
        issues = []
        
        if not config.kalshi.api_key:
            issues.append("KALSHI_API_KEY not set")
        
        if not Path(config.kalshi.private_key_path).exists():
            issues.append(f"Private key not found: {config.kalshi.private_key_path}")
        
        if issues:
            self.checks["config"] = {
                "status": "error",
                "message": "; ".join(issues)
            }
        else:
            self.checks["config"] = {
                "status": "ok",
                "message": "All required configuration present"
            }
    
    def to_dict(self):
        """Convert to dictionary"""
        return {
            "status": self.overall_status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "checks": self.checks
        }
    
    def print_report(self, json_output=False):
        """Print health check report"""
        if json_output:
            print(json.dumps(self.to_dict(), indent=2))
            return
        
        # Status emoji
        status_emoji = {
            "healthy": "✅",
            "degraded": "⚠️",
            "unhealthy": "❌"
        }
        
        check_emoji = {
            "ok": "✓",
            "warning": "⚠",
            "error": "✗"
        }
        
        print("=" * 50)
        print(f"Health Check: {status_emoji.get(self.overall_status, '?')} {self.overall_status.upper()}")
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 50)
        
        for name, check in self.checks.items():
            emoji = check_emoji.get(check.get("status"), "?")
            print(f"\n{emoji} {name.replace('_', ' ').title()}")
            print(f"  Status: {check.get('status', 'unknown')}")
            if check.get("message"):
                print(f"  {check['message']}")
        
        print("\n" + "=" * 50)


async def main():
    """Main entry point"""
    json_output = "--json" in sys.argv
    
    health = HealthCheck()
    status = await health.run_all()
    health.print_report(json_output=json_output)
    
    # Exit code: 0 = healthy, 1 = degraded, 2 = unhealthy
    exit_codes = {"healthy": 0, "degraded": 1, "unhealthy": 2}
    sys.exit(exit_codes.get(status, 2))


if __name__ == "__main__":
    asyncio.run(main())
