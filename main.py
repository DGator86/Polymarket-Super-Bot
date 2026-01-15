"""
Kalshi Prediction Bot - Main Entry Point

Enhanced version with all features:
- Universe Engine (market filtering)
- Data Connectors (Kalshi, FRED, BLS, NOAA, Coinbase)
- Probability Engine (edge detection)
- ML Volatility Forecasting
- Multi-Timeframe Analysis
- Risk Manager (position sizing)
- Telegram/Discord Alerts
- Historical Database
- Execution Engine (order management)

Run with: python main.py
"""

import asyncio
import logging
import signal
import sys
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import List, Optional
from pathlib import Path

from config import config
from core.models import NormalizedMarket, TradingSignal, OrderRequest, Side, OrderType
from core.universe_engine import UniverseEngine
from core.probability_engine import ProbabilityEngine, Opportunity
from core.risk_manager import RiskManager, SizedOrder
from core.ml_volatility import get_volatility_forecaster, PriceObservation
from connectors.kalshi import KalshiClient, create_kalshi_client
from connectors.fred import FREDClient, create_fred_client
from connectors.noaa import NOAAClient, create_noaa_client
from connectors.coinbase import CoinbaseClient, create_coinbase_client
from connectors.bls import BLSClient, create_bls_client
from strategies.latency_arb import LatencyArbStrategy, signal_to_trading_signal
from strategies.multi_timeframe import MultiTimeframeStrategy
from utils.alerts import get_alert_manager, AlertManager
from utils.database import get_database, record_trade, record_signal, DatabaseManager

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.logging.log_level),
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(config.logging.log_file)
    ]
)
logger = logging.getLogger(__name__)


class PredictionBot:
    """
    Main bot orchestrator with all enhancements.
    
    Features:
    - Multi-strategy support (value betting, latency arb, multi-timeframe)
    - ML-based volatility forecasting
    - Real-time alerts (Telegram/Discord)
    - Trade history database
    - Daily P&L summaries
    
    Lifecycle:
    1. Initialize and connect to all services
    2. Main loop:
       a. Scan universe for tradeable markets
       b. Run probability models on candidates
       c. Apply ML volatility adjustments
       d. Size opportunities through risk manager
       e. Execute trades
       f. Send alerts and log to database
       g. Sleep and repeat
    3. Send daily summary
    4. Graceful shutdown
    
    Usage:
        bot = PredictionBot()
        await bot.run()
    """
    
    def __init__(self):
        # Connectors
        self.kalshi: Optional[KalshiClient] = None
        self.fred: Optional[FREDClient] = None
        self.bls: Optional[BLSClient] = None
        self.noaa: Optional[NOAAClient] = None
        self.coinbase: Optional[CoinbaseClient] = None
        
        # Engines
        self.universe: Optional[UniverseEngine] = None
        self.probability: Optional[ProbabilityEngine] = None
        self.risk: Optional[RiskManager] = None
        self.vol_forecaster = get_volatility_forecaster()
        
        # Strategies
        self.latency_arb: Optional[LatencyArbStrategy] = None
        self.multi_timeframe: Optional[MultiTimeframeStrategy] = None
        
        # Services
        self.alerts: Optional[AlertManager] = None
        self.database: Optional[DatabaseManager] = None
        
        # State
        self._running = False
        self._cycle_count = 0
        self._trades_today = 0
        self._pnl_today = Decimal("0")
        self._last_summary_date = None
        
        # Configuration
        self.scan_interval_seconds = 60  # How often to scan for opportunities
        self.dry_run = True              # Set False to execute real trades
        self.enable_alerts = True        # Send Telegram/Discord alerts
        self.enable_database = True      # Log to database
        self.enable_multi_timeframe = config.multi_timeframe.enabled
        self.enable_latency_arb = config.latency_arb.enabled
    
    async def initialize(self):
        """Connect to all services and initialize engines"""
        logger.info("=" * 60)
        logger.info("KALSHI PREDICTION BOT - INITIALIZING")
        logger.info("=" * 60)
        
        # Ensure data directory exists
        Path("./data").mkdir(exist_ok=True)
        
        # Connect to Kalshi (required)
        logger.info("Connecting to Kalshi...")
        try:
            self.kalshi = await create_kalshi_client()
            balance = await self.kalshi.get_balance()
            logger.info(f"Kalshi connected. Balance: ${balance.total_equity:.2f}")
        except Exception as e:
            logger.error(f"Failed to connect to Kalshi: {e}")
            raise
        
        # Connect to data sources (optional but recommended)
        logger.info("Connecting to data sources...")
        
        # FRED
        try:
            if config.data_sources.fred_api_key:
                self.fred = await create_fred_client()
                logger.info("FRED connected")
            else:
                logger.warning("FRED API key not configured - economic models disabled")
        except Exception as e:
            logger.warning(f"FRED connection failed: {e}")
        
        # BLS
        try:
            if config.data_sources.bls_api_key:
                self.bls = await create_bls_client()
                logger.info("BLS connected")
            else:
                logger.warning("BLS API key not configured - detailed CPI components disabled")
        except Exception as e:
            logger.warning(f"BLS connection failed: {e}")
        
        # NOAA
        try:
            self.noaa = await create_noaa_client()
            logger.info("NOAA connected")
        except Exception as e:
            logger.warning(f"NOAA connection failed: {e}")
        
        # Coinbase
        try:
            self.coinbase = await create_coinbase_client()
            logger.info("Coinbase connected")
        except Exception as e:
            logger.warning(f"Coinbase connection failed: {e}")
        
        # Initialize engines
        self.universe = UniverseEngine(self.kalshi)
        self.probability = ProbabilityEngine(
            fred_client=self.fred,
            noaa_client=self.noaa,
            coinbase_client=self.coinbase
        )
        self.risk = RiskManager()
        
        # Initialize strategies
        if self.enable_latency_arb and self.coinbase:
            self.latency_arb = LatencyArbStrategy(self.kalshi, self.coinbase)
            logger.info("Latency arbitrage strategy enabled")
        
        if self.enable_multi_timeframe and self.coinbase:
            self.multi_timeframe = MultiTimeframeStrategy(self.kalshi, self.coinbase)
            await self.multi_timeframe.initialize()
            logger.info("Multi-timeframe strategy enabled")
        
        # Initialize alerts
        if self.enable_alerts:
            self.alerts = await get_alert_manager()
            if self.alerts.telegram.enabled or self.alerts.discord.enabled:
                logger.info("Alerts enabled")
                await self.alerts.send_system_alert(
                    "Bot Started",
                    f"Kalshi Prediction Bot initialized. Dry run: {self.dry_run}"
                )
        
        # Initialize database
        if self.enable_database:
            self.database = await get_database()
            logger.info("Database connected")
        
        logger.info("Initialization complete")
    
    async def shutdown(self):
        """Graceful shutdown"""
        logger.info("Shutting down...")
        self._running = False
        
        # Send final summary if trading
        if not self.dry_run and self._trades_today > 0:
            await self._send_daily_summary()
        
        # Send shutdown alert
        if self.alerts:
            await self.alerts.send_system_alert(
                "Bot Stopped",
                f"Kalshi Prediction Bot shutdown. Trades today: {self._trades_today}"
            )
        
        # Close all connections
        if self.kalshi:
            await self.kalshi.close()
        if self.fred:
            await self.fred.close()
        if self.bls:
            await self.bls.close()
        if self.noaa:
            await self.noaa.close()
        if self.coinbase:
            await self.coinbase.close()
        if self.alerts:
            await self.alerts.close()
        if self.database:
            await self.database.close()
        
        logger.info("Shutdown complete")
    
    async def run(self):
        """Main bot loop"""
        await self.initialize()
        
        self._running = True
        logger.info("=" * 60)
        logger.info("BOT RUNNING - Press Ctrl+C to stop")
        logger.info(f"Mode: {'DRY RUN' if self.dry_run else 'LIVE TRADING'}")
        logger.info("=" * 60)
        
        while self._running:
            try:
                # Check if we need to send daily summary
                await self._check_daily_summary()
                
                # Run main trading cycle
                await self._run_cycle()
                
                if self._running:
                    logger.info(f"Sleeping {self.scan_interval_seconds}s until next cycle...")
                    await asyncio.sleep(self.scan_interval_seconds)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in main loop: {e}", exc_info=True)
                
                if self.alerts:
                    await self.alerts.send_error_alert(
                        "Main Loop Error",
                        str(e),
                        {"cycle": self._cycle_count}
                    )
                
                await asyncio.sleep(10)  # Back off on errors
        
        await self.shutdown()
    
    async def _run_cycle(self):
        """Single scan/analyze/trade cycle"""
        self._cycle_count += 1
        cycle_start = datetime.now(timezone.utc)
        
        logger.info("-" * 40)
        logger.info(f"CYCLE {self._cycle_count} - {cycle_start.strftime('%H:%M:%S')}")
        logger.info("-" * 40)
        
        # Step 1: Update portfolio state
        balance = await self.kalshi.get_balance()
        positions = await self.kalshi.get_positions()
        self.risk.update_portfolio(balance, positions)
        
        summary = self.risk.get_portfolio_summary()
        logger.info(f"Portfolio: ${summary['total_equity']:.2f} | "
                   f"P&L: {summary['daily_pnl_pct']:.2%} | "
                   f"Trades: {summary['trades_today']}")
        
        if self.risk.is_circuit_breaker_active:
            logger.warning("Circuit breaker active - skipping cycle")
            
            if self.alerts:
                await self.alerts.send_circuit_breaker_alert(
                    "Daily loss limit exceeded",
                    summary['daily_pnl_pct'],
                    float(config.risk.max_daily_loss_pct)
                )
            return
        
        # Collect all opportunities from different strategies
        all_sized_orders: List[SizedOrder] = []
        
        # Step 2: Run value betting strategy (probability model)
        await self._run_value_betting(all_sized_orders)
        
        # Step 3: Run multi-timeframe strategy
        if self.multi_timeframe:
            await self._run_multi_timeframe(all_sized_orders)
        
        # Step 4: Sort and limit orders
        all_sized_orders.sort(key=lambda so: so.signal.edge, reverse=True)
        all_sized_orders = all_sized_orders[:5]  # Max 5 trades per cycle
        
        # Step 5: Execute trades
        if not all_sized_orders:
            logger.info("No opportunities passed risk filters")
        elif self.dry_run:
            logger.info(f"DRY RUN - Would execute {len(all_sized_orders)} orders")
            for so in all_sized_orders:
                logger.info(f"  [DRY] {so.signal.ticker}: {so.signal.side.value} x{so.size} "
                          f"edge={so.signal.edge:.1%}")
                
                # Log signal to database even in dry run
                if self.database:
                    await record_signal(so.signal, was_traded=False, rejection_reason="dry_run")
        else:
            await self._execute_orders(all_sized_orders)
        
        # Log cycle stats
        cycle_time = (datetime.now(timezone.utc) - cycle_start).total_seconds()
        logger.info(f"Cycle complete in {cycle_time:.1f}s")
    
    async def _run_value_betting(self, sized_orders: List[SizedOrder]):
        """Run value betting strategy using probability models"""
        logger.info("Scanning market universe...")
        markets = await self.universe.scan()
        
        if not markets:
            logger.info("No tradeable markets found")
            return
        
        logger.info(f"Found {len(markets)} tradeable markets")
        
        # Run probability models
        logger.info("Analyzing opportunities...")
        opportunities = await self.probability.analyze(markets)
        
        if not opportunities:
            logger.info("No opportunities with sufficient edge")
            return
        
        logger.info(f"Found {len(opportunities)} opportunities")
        
        # Size and filter through risk manager
        for opp in opportunities:
            # Apply ML volatility adjustment
            symbol = self._extract_symbol(opp.market.ticker)
            if symbol:
                adjusted_kelly = self.vol_forecaster.get_adjusted_kelly(
                    symbol,
                    float(config.risk.kelly_fraction),
                    float(opp.edge)
                )
                # Temporarily adjust risk manager's Kelly fraction
                original_kelly = self.risk.kelly_fraction
                self.risk.kelly_fraction = Decimal(str(adjusted_kelly))
            
            sized = self.risk.size_order(opp.signal)
            
            if symbol:
                self.risk.kelly_fraction = original_kelly
            
            if sized:
                sized_orders.append(sized)
                logger.info(
                    f"  {opp.market.ticker}: {opp.side.value.upper()} "
                    f"size={sized.size} edge={opp.edge:.1%} EV={opp.expected_value:.3f}"
                )
    
    async def _run_multi_timeframe(self, sized_orders: List[SizedOrder]):
        """Run multi-timeframe analysis strategy"""
        if not self.multi_timeframe:
            return
        
        logger.info("Running multi-timeframe analysis...")
        
        try:
            signals = await self.multi_timeframe.analyze()
            
            for mtf_signal in signals:
                # Convert to trading signal
                trading_signal = mtf_signal.to_trading_signal()
                
                # Size through risk manager
                sized = self.risk.size_order(trading_signal)
                
                if sized:
                    sized_orders.append(sized)
                    logger.info(
                        f"  [MTF] {mtf_signal.ticker}: {mtf_signal.side.value.upper()} "
                        f"size={sized.size} edge={mtf_signal.edge:.1%} "
                        f"confluence={mtf_signal.confluence_score:.0%}"
                    )
        except Exception as e:
            logger.warning(f"Multi-timeframe analysis failed: {e}")
    
    async def _execute_orders(self, orders: List[SizedOrder]):
        """Execute a list of sized orders"""
        for sized in orders:
            sig = sized.signal
            
            # Determine price (use best available quote with small buffer)
            if sig.side == Side.YES:
                # Want to buy YES - use ask price
                price_cents = int(sig.market_probability * 100) + 1  # Slightly above mid
            else:
                # Want to buy NO - convert to yes_price
                price_cents = int(sig.market_probability * 100) - 1  # Slightly below mid
            
            price_cents = max(1, min(99, price_cents))
            
            order = OrderRequest(
                ticker=sig.ticker,
                side=sig.side,
                count=sized.size,
                price=price_cents,
                order_type=OrderType.LIMIT
            )
            
            try:
                result = await self.kalshi.place_order(order)
                logger.info(
                    f"ORDER PLACED: {result.ticker} {result.side.value} "
                    f"x{result.requested_count} @ {price_cents}¢ "
                    f"[{result.status.value}]"
                )
                
                self._trades_today += 1
                
                # Log to database
                if self.database:
                    await record_trade(sig, result)
                    await record_signal(sig, was_traded=True)
                
                # Send alert
                if self.alerts:
                    await self.alerts.send_trade_alert(sig, result)
                
            except Exception as e:
                logger.error(f"Order failed for {sig.ticker}: {e}")
                
                # Log failed signal
                if self.database:
                    await record_signal(sig, was_traded=False, rejection_reason=str(e))
                
                # Alert on error
                if self.alerts:
                    await self.alerts.send_error_alert(
                        "Order Failed",
                        str(e),
                        {"ticker": sig.ticker, "side": sig.side.value}
                    )
    
    async def _check_daily_summary(self):
        """Check if we need to send daily summary"""
        if not config.alerts.send_daily_summary:
            return
        
        now = datetime.now(timezone.utc)
        summary_hour = config.alerts.daily_summary_hour
        
        # Check if it's time for summary and we haven't sent one today
        if now.hour == summary_hour and self._last_summary_date != now.date():
            await self._send_daily_summary()
            self._last_summary_date = now.date()
    
    async def _send_daily_summary(self):
        """Send daily trading summary"""
        if not self.alerts or not self.database:
            return
        
        try:
            summary = await self.database.get_performance_summary(days=1)
            
            if summary.get('total_trades', 0) > 0:
                await self.alerts.send_daily_summary(
                    total_pnl=summary.get('total_pnl', 0),
                    trades_count=summary.get('total_trades', 0),
                    win_rate=summary.get('win_rate', 0),
                    best_trade=f"{summary.get('best_trade', {}).get('ticker', 'N/A')}",
                    worst_trade=f"{summary.get('worst_trade', {}).get('ticker', 'N/A')}"
                )
        except Exception as e:
            logger.warning(f"Failed to send daily summary: {e}")
    
    def _extract_symbol(self, ticker: str) -> Optional[str]:
        """Extract crypto symbol from ticker if applicable"""
        ticker_upper = ticker.upper()
        if "BTC" in ticker_upper or "BITCOIN" in ticker_upper:
            return "BTC-USD"
        elif "ETH" in ticker_upper or "ETHEREUM" in ticker_upper:
            return "ETH-USD"
        return None


async def main():
    """Entry point"""
    bot = PredictionBot()
    
    # Handle shutdown signals
    loop = asyncio.get_event_loop()
    
    def handle_shutdown(sig):
        logger.info(f"Received {sig.name}")
        bot._running = False
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: handle_shutdown(s))
    
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
