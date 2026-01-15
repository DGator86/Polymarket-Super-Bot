"""
Paper Trading Runner

Main orchestrator that runs the full paper trading loop:
1. Scan for opportunities using live Kalshi data
2. Enter paper positions based on signals
3. Track positions and update prices
4. Process settlements and record outcomes
5. Feed results to ML model for learning
6. Generate reports and analytics

This is the primary entry point for paper trading mode.
"""

import asyncio
import logging
import signal
import sys
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional, List, Dict
from pathlib import Path

from config import config
from core.models import TradingSignal, Side
from core.universe_engine import UniverseEngine
from core.probability_engine import ProbabilityEngine, Opportunity
from core.risk_manager import RiskManager
from connectors.kalshi import KalshiClient, create_kalshi_client
from connectors.fred import FREDClient, create_fred_client
from connectors.noaa import NOAAClient, create_noaa_client
from connectors.coinbase import CoinbaseClient, create_coinbase_client
from paper_trading.engine import PaperTradingEngine, PaperTrade, PaperPosition
from ml.predictor import TradePredictor, OnlineModelUpdater

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("paper_trading.log")
    ]
)
logger = logging.getLogger(__name__)


class PaperTradingRunner:
    """
    Complete paper trading system with ML integration.
    
    Simulates the full trading workflow against live market data
    while tracking virtual positions and learning from outcomes.
    
    Usage:
        runner = PaperTradingRunner(starting_capital=1000)
        await runner.run()
    """
    
    def __init__(
        self,
        starting_capital: Decimal = Decimal("1000"),
        data_dir: str = "./paper_trading_data",
        scan_interval: int = 60,
        max_positions: int = 10,
        min_ml_samples: int = 20,
    ):
        self.starting_capital = starting_capital
        self.data_dir = Path(data_dir)
        self.scan_interval = scan_interval
        self.max_positions = max_positions
        self.min_ml_samples = min_ml_samples
        
        # Components
        self.kalshi: Optional[KalshiClient] = None
        self.fred: Optional[FREDClient] = None
        self.noaa: Optional[NOAAClient] = None
        self.coinbase: Optional[CoinbaseClient] = None
        
        self.universe: Optional[UniverseEngine] = None
        self.probability: Optional[ProbabilityEngine] = None
        self.risk: Optional[RiskManager] = None
        
        self.paper_engine: Optional[PaperTradingEngine] = None
        self.ml_predictor: Optional[TradePredictor] = None
        self.ml_updater: Optional[OnlineModelUpdater] = None
        
        # State
        self._running = False
        self._cycle_count = 0
        self._last_report_time: Optional[datetime] = None
    
    async def initialize(self):
        """Initialize all components"""
        logger.info("=" * 70)
        logger.info("KALSHI PAPER TRADING SYSTEM - INITIALIZING")
        logger.info("=" * 70)
        
        # Connect to Kalshi
        logger.info("Connecting to Kalshi (read-only for paper trading)...")
        try:
            self.kalshi = await create_kalshi_client()
            logger.info("Kalshi connected")
        except Exception as e:
            logger.error(f"Failed to connect to Kalshi: {e}")
            raise
        
        # Connect to data sources
        logger.info("Connecting to data sources...")
        
        try:
            if config.data_sources.fred_api_key:
                self.fred = await create_fred_client()
                logger.info("FRED connected")
        except Exception as e:
            logger.warning(f"FRED connection failed: {e}")
        
        try:
            self.noaa = await create_noaa_client()
            logger.info("NOAA connected")
        except Exception as e:
            logger.warning(f"NOAA connection failed: {e}")
        
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
        
        # Initialize paper trading engine
        logger.info(f"Initializing paper trading with ${self.starting_capital} capital...")
        self.paper_engine = PaperTradingEngine(
            starting_capital=self.starting_capital,
            data_dir=str(self.data_dir)
        )
        await self.paper_engine.initialize(self.kalshi)
        
        # Initialize ML components
        logger.info("Initializing ML predictor...")
        self.ml_predictor = TradePredictor(
            model_dir=str(self.data_dir / "ml_models")
        )
        
        self.ml_updater = OnlineModelUpdater(
            self.ml_predictor,
            update_frequency=10
        )
        
        # Set up ML callback
        self.paper_engine.set_trade_callback(self._on_trade_complete)
        
        logger.info("Initialization complete")
        self._print_status()
    
    async def shutdown(self):
        """Clean shutdown"""
        logger.info("Shutting down...")
        self._running = False
        
        # Final report
        self._print_final_report()
        
        # Save state
        if self.paper_engine:
            self.paper_engine.take_snapshot()
            self.paper_engine.close()
        
        # Close connections
        if self.kalshi:
            await self.kalshi.close()
        if self.fred:
            await self.fred.close()
        if self.noaa:
            await self.noaa.close()
        if self.coinbase:
            await self.coinbase.close()
        
        logger.info("Shutdown complete")
    
    async def run(self):
        """Main paper trading loop"""
        await self.initialize()
        
        self._running = True
        logger.info("=" * 70)
        logger.info("PAPER TRADING STARTED - Press Ctrl+C to stop")
        logger.info("=" * 70)
        
        while self._running:
            try:
                await self._run_cycle()
                
                # Periodic reporting
                await self._maybe_print_report()
                
                if self._running:
                    logger.info(f"Next scan in {self.scan_interval}s...")
                    await asyncio.sleep(self.scan_interval)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in main loop: {e}", exc_info=True)
                await asyncio.sleep(10)
        
        await self.shutdown()
    
    async def _run_cycle(self):
        """Single scan/trade/update cycle"""
        self._cycle_count += 1
        cycle_start = datetime.now(timezone.utc)
        
        logger.info("-" * 50)
        logger.info(f"CYCLE {self._cycle_count} - {cycle_start.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        logger.info("-" * 50)
        
        # Step 1: Update existing positions
        logger.info("Updating position prices...")
        await self.paper_engine.update_prices()
        
        # Step 2: Check for settlements
        logger.info("Checking for settlements...")
        await self.paper_engine.process_settlements()
        
        # Step 3: Take snapshot
        snapshot = self.paper_engine.take_snapshot()
        logger.info(
            f"Portfolio: ${snapshot.total_equity:.2f} | "
            f"Cash: ${snapshot.cash:.2f} | "
            f"Positions: {snapshot.num_positions} | "
            f"P&L Today: ${snapshot.realized_pnl_today:.2f}"
        )
        
        # Step 4: Check if we can take more positions
        open_positions = len([p for p in self.paper_engine.positions.values() if not p.settled])
        
        if open_positions >= self.max_positions:
            logger.info(f"Max positions ({self.max_positions}) reached - skipping scan")
            return
        
        # Step 5: Scan for opportunities
        logger.info("Scanning market universe...")
        markets = await self.universe.scan()
        
        if not markets:
            logger.info("No tradeable markets found")
            return
        
        logger.info(f"Found {len(markets)} tradeable markets")
        
        # Step 6: Run probability models
        logger.info("Analyzing opportunities...")
        opportunities = await self.probability.analyze(markets)
        
        if not opportunities:
            logger.info("No opportunities with sufficient edge")
            return
        
        # Step 7: Apply ML calibration if model is trained
        if self.ml_predictor and self.ml_predictor.is_trained:
            opportunities = self._apply_ml_filter(opportunities)
        
        logger.info(f"Found {len(opportunities)} opportunities after filtering")
        
        # Step 8: Enter positions
        positions_to_add = self.max_positions - open_positions
        
        for opp in opportunities[:positions_to_add]:
            await self._enter_paper_position(opp)
        
        # Log cycle time
        cycle_time = (datetime.now(timezone.utc) - cycle_start).total_seconds()
        logger.info(f"Cycle complete in {cycle_time:.1f}s")
    
    def _apply_ml_filter(self, opportunities: List[Opportunity]) -> List[Opportunity]:
        """
        Apply ML predictions to filter/rank opportunities.
        """
        filtered = []
        
        for opp in opportunities:
            # Prepare features for ML model
            features = {
                "signal_edge": float(opp.edge),
                "signal_confidence": float(opp.signal.confidence),
                "model_probability": float(opp.signal.model_probability),
                "market_probability": float(opp.signal.market_probability),
                "entry_price": float(opp.market.best_ask if opp.side == Side.YES else (1 - opp.market.best_bid)),
                "time_held_hours": 24,  # Estimate
                "category": opp.market.category.value,
                "side": opp.side.value,
            }
            
            # Get ML prediction
            win_prob = self.ml_predictor.predict_win_probability(features)
            
            # Get calibrated edge
            calibrated_edge = self.ml_predictor.calibrate_edge(
                float(opp.edge),
                opp.market.category.value
            )
            
            logger.debug(
                f"{opp.market.ticker}: raw_edge={opp.edge:.1%}, "
                f"calibrated={calibrated_edge:.1%}, ml_win_prob={win_prob:.1%}"
            )
            
            # Filter: require ML win probability > 55%
            if win_prob > 0.55:
                # Update signal with calibrated edge
                opp.signal.edge = Decimal(str(calibrated_edge))
                filtered.append(opp)
        
        # Sort by ML win probability
        filtered.sort(key=lambda o: self.ml_predictor.predict_win_probability({
            "signal_edge": float(o.edge),
            "signal_confidence": float(o.signal.confidence),
            "model_probability": float(o.signal.model_probability),
            "market_probability": float(o.signal.market_probability),
            "entry_price": float(o.market.best_ask if o.side == Side.YES else (1 - o.market.best_bid)),
            "time_held_hours": 24,
            "category": o.market.category.value,
            "side": o.side.value,
        }), reverse=True)
        
        return filtered
    
    async def _enter_paper_position(self, opp: Opportunity):
        """Enter a paper position for an opportunity"""
        
        # Calculate position size (simplified)
        available_cash = self.paper_engine.cash
        max_per_trade = available_cash * Decimal("0.1")  # 10% max per trade
        
        if opp.side == Side.YES:
            entry_price = opp.market.best_ask
        else:
            entry_price = Decimal("1") - opp.market.best_bid
        
        size = int(max_per_trade / entry_price)
        size = max(1, min(size, 50))  # 1-50 contracts
        
        # Enter position
        position = await self.paper_engine.enter_position(
            signal=opp.signal,
            market=opp.market,
            size=size
        )
        
        if position:
            logger.info(
                f"PAPER ENTRY: {position.ticker} | "
                f"{position.side.value.upper()} x{position.quantity} @ {position.entry_price:.2%} | "
                f"Edge: {opp.edge:.1%}"
            )
    
    async def _on_trade_complete(self, trade: PaperTrade):
        """Callback when a paper trade settles"""
        logger.info(
            f"TRADE SETTLED: {trade.ticker} | "
            f"{trade.outcome.value.upper()} | "
            f"P&L: ${trade.pnl:.2f} ({trade.pnl_pct:.1%})"
        )
        
        # Feed to ML updater
        trade_data = trade.to_dict()
        trade_data["outcome"] = 1 if trade.outcome.value == "win" else 0
        await self.ml_updater.on_trade_complete(trade_data)
        
        # Check if we should retrain
        await self._maybe_retrain_ml()
    
    async def _maybe_retrain_ml(self):
        """Retrain ML model if we have enough new data"""
        training_data = self.paper_engine.get_ml_training_data()
        
        if len(training_data) >= self.min_ml_samples:
            if not self.ml_predictor.is_trained:
                logger.info(f"Training ML model on {len(training_data)} samples...")
                try:
                    metrics = self.ml_predictor.train(training_data)
                    logger.info(
                        f"ML Model trained: "
                        f"accuracy={metrics.accuracy:.1%}, "
                        f"AUC={metrics.auc_roc:.3f}"
                    )
                except Exception as e:
                    logger.error(f"ML training failed: {e}")
    
    async def _maybe_print_report(self):
        """Print periodic status report"""
        now = datetime.now(timezone.utc)
        
        if self._last_report_time is None:
            self._last_report_time = now
            return
        
        # Report every 10 cycles
        if self._cycle_count % 10 == 0:
            self._print_status()
            self._last_report_time = now
    
    def _print_status(self):
        """Print current status"""
        stats = self.paper_engine.get_performance_stats()
        
        logger.info("=" * 50)
        logger.info("PAPER TRADING STATUS")
        logger.info("=" * 50)
        logger.info(f"Total Trades: {stats.get('total_trades', 0)}")
        logger.info(f"Win Rate: {stats.get('win_rate', 0):.1%}")
        logger.info(f"Total P&L: ${stats.get('total_pnl', 0):.2f}")
        logger.info(f"Current Equity: ${stats.get('current_equity', 0):.2f}")
        logger.info(f"Return: {stats.get('return_pct', 0):.1%}")
        logger.info(f"Open Positions: {stats.get('open_positions', 0)}")
        
        if self.ml_predictor and self.ml_predictor.is_trained:
            metrics = self.ml_predictor.metrics
            if metrics:
                logger.info(f"ML Model Accuracy: {metrics.accuracy:.1%}")
                logger.info(f"ML Model AUC: {metrics.auc_roc:.3f}")
        
        logger.info("=" * 50)
    
    def _print_final_report(self):
        """Print comprehensive final report"""
        stats = self.paper_engine.get_performance_stats()
        
        logger.info("")
        logger.info("=" * 70)
        logger.info("FINAL PAPER TRADING REPORT")
        logger.info("=" * 70)
        logger.info("")
        logger.info(f"Starting Capital:  ${self.starting_capital:.2f}")
        logger.info(f"Final Equity:      ${stats.get('current_equity', 0):.2f}")
        logger.info(f"Total Return:      {stats.get('return_pct', 0):.1%}")
        logger.info("")
        logger.info(f"Total Trades:      {stats.get('total_trades', 0)}")
        logger.info(f"Wins:              {stats.get('wins', 0)}")
        logger.info(f"Losses:            {stats.get('losses', 0)}")
        logger.info(f"Win Rate:          {stats.get('win_rate', 0):.1%}")
        logger.info("")
        logger.info(f"Total P&L:         ${stats.get('total_pnl', 0):.2f}")
        logger.info(f"Avg Win:           ${stats.get('avg_win', 0):.2f}")
        logger.info(f"Avg Loss:          ${stats.get('avg_loss', 0):.2f}")
        logger.info(f"Profit Factor:     {stats.get('profit_factor', 0):.2f}")
        logger.info("")
        
        # Performance by category
        by_category = stats.get("by_category", {})
        if by_category:
            logger.info("Performance by Category:")
            for cat, cat_stats in by_category.items():
                logger.info(
                    f"  {cat}: {cat_stats['trades']} trades, "
                    f"{cat_stats['win_rate']:.1%} win rate, "
                    f"${cat_stats['pnl']:.2f} P&L"
                )
            logger.info("")
        
        # Performance by edge bucket
        by_edge = stats.get("by_edge_bucket", {})
        if by_edge:
            logger.info("Performance by Edge Bucket:")
            for bucket, bucket_stats in by_edge.items():
                logger.info(
                    f"  {bucket}: {bucket_stats['trades']} trades, "
                    f"{bucket_stats['win_rate']:.1%} win rate, "
                    f"${bucket_stats['avg_pnl']:.2f} avg P&L"
                )
            logger.info("")
        
        # ML Model performance
        if self.ml_predictor and self.ml_predictor.is_trained:
            metrics = self.ml_predictor.metrics
            if metrics:
                logger.info("ML Model Performance:")
                logger.info(f"  Accuracy:    {metrics.accuracy:.1%}")
                logger.info(f"  Precision:   {metrics.precision:.1%}")
                logger.info(f"  Recall:      {metrics.recall:.1%}")
                logger.info(f"  F1 Score:    {metrics.f1:.3f}")
                logger.info(f"  AUC-ROC:     {metrics.auc_roc:.3f}")
                logger.info("")
                
                # Feature importance
                if metrics.feature_importance:
                    logger.info("Feature Importance:")
                    sorted_features = sorted(
                        metrics.feature_importance.items(),
                        key=lambda x: x[1],
                        reverse=True
                    )
                    for feature, importance in sorted_features[:5]:
                        logger.info(f"  {feature}: {importance:.3f}")
        
        logger.info("")
        logger.info("=" * 70)


async def main():
    """Entry point for paper trading"""
    runner = PaperTradingRunner(
        starting_capital=Decimal("1000"),
        data_dir="./paper_trading_data",
        scan_interval=60,
        max_positions=10,
    )
    
    # Handle shutdown signals
    loop = asyncio.get_event_loop()
    
    def handle_shutdown(sig):
        logger.info(f"Received {sig.name}")
        runner._running = False
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: handle_shutdown(s))
    
    await runner.run()


if __name__ == "__main__":
    asyncio.run(main())
