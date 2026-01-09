"""
Main orchestrator for the Polymarket hybrid bot.
"""
import sys
import time
import signal
from datetime import datetime
from typing import Optional

from src.config import load_config
from src.logging_setup import setup_logging, get_logger
from src.market_registry import MarketRegistry
from src.feeds.polymarket_ws import PolymarketBookFeed, SimulatedBookFeed
from src.feeds.spot_ws import SpotPriceFeed, SimulatedSpotFeed, BinanceSpotFeed
from src.strategy.fair_price import FairPriceCalculator
from src.strategy.lag_arb import LagArbStrategy
from src.strategy.market_maker import MarketMakerStrategy
from src.strategy.hybrid_router import HybridRouter
from src.risk.limits import RiskLimits
from src.risk.kill_switch import KillSwitch
from src.risk.risk_engine import RiskEngine
from src.execution.clob_client import CLOBClient
from src.execution.order_manager import OrderManager
from src.state.db import Database
from src.state.repositories import (
    OrderRepository,
    FillRepository,
    PositionRepository,
    DecisionRepository
)
from src.state.pnl import PnLTracker

logger = get_logger("app")


class PolymarketBot:
    """
    Main bot orchestrator.

    Responsibilities:
    1. Initialize all components
    2. Start feeds
    3. Main loop: generate intents -> risk check -> execute -> persist
    4. Handle shutdown gracefully
    """

    def __init__(self):
        self.config = None
        self.registry = None
        self.book_feed = None
        self.spot_feed = None
        self.hybrid_router = None
        self.risk_engine = None
        self.kill_switch = None
        self.clob_client = None
        self.order_manager = None
        self.db = None
        self.pnl_tracker = None
        self.running = False

    def initialize(self) -> None:
        """Initialize all components."""
        logger.info("Initializing Polymarket bot...")

        # Load configuration
        self.config = load_config()
        logger.info(f"Configuration loaded (dry_run={self.config.execution.dry_run})")

        # Setup logging
        setup_logging(self.config.log_level, self.config.log_file)

        # Initialize database
        self.db = Database(self.config.db_path)
        self.db.connect()

        # Initialize repositories
        order_repo = OrderRepository(self.db)
        fill_repo = FillRepository(self.db)
        position_repo = PositionRepository(self.db)
        decision_repo = DecisionRepository(self.db)

        # Initialize PnL tracker
        self.pnl_tracker = PnLTracker(position_repo, fill_repo)

        # Initialize kill switch
        self.kill_switch = KillSwitch()
        if self.config.kill_switch:
            self.kill_switch.activate("Kill switch enabled in config")

        # Initialize market registry
        self.registry = MarketRegistry(self.config.market_registry_path)

        # Initialize feeds
        # For now, use simulated feeds - replace with real ones in production
        self.book_feed = SimulatedBookFeed()
        self.spot_feed = SimulatedSpotFeed()

        # Subscribe to markets
        markets = self.registry.get_all_markets()
        token_ids = []
        for market in markets.values():
            token_ids.extend([market.yes_token_id, market.no_token_id])
        self.book_feed.subscribe(token_ids)

        # Initialize strategy components
        fair_price_calc = FairPriceCalculator(
            sigma_floor=self.config.strategy.sigma_floor,
            use_normal_cdf=self.config.strategy.use_normal_cdf
        )

        lag_arb = LagArbStrategy(
            edge_threshold=self.config.strategy.taker_edge_threshold,
            max_slippage=self.config.risk.max_taker_slippage
        )

        market_maker = MarketMakerStrategy(
            half_spread=self.config.strategy.maker_half_spread,
            quote_ttl_ms=self.config.strategy.quote_refresh_ttl_ms,
            inventory_skew_factor=self.config.strategy.inventory_skew_factor,
            max_inventory=self.config.risk.max_inventory_per_token
        )

        self.hybrid_router = HybridRouter(
            fair_price_calc=fair_price_calc,
            lag_arb=lag_arb,
            market_maker=market_maker
        )

        # Initialize risk engine
        risk_limits = RiskLimits(
            max_notional_per_market=self.config.risk.max_notional_per_market,
            max_inventory_per_token=self.config.risk.max_inventory_per_token,
            max_open_orders_total=self.config.risk.max_open_orders_total,
            max_orders_per_min=self.config.risk.max_orders_per_min,
            max_daily_loss=self.config.risk.max_daily_loss,
            max_taker_slippage=self.config.risk.max_taker_slippage,
            feed_stale_ms=self.config.risk.feed_stale_ms
        )

        self.risk_engine = RiskEngine(risk_limits, self.kill_switch)

        # Initialize CLOB client
        self.clob_client = CLOBClient(
            private_key=self.config.execution.private_key,
            chain_id=self.config.execution.chain_id,
            clob_url=self.config.execution.clob_url,
            api_key=self.config.execution.api_key,
            api_secret=self.config.execution.api_secret,
            api_passphrase=self.config.execution.api_passphrase,
            dry_run=self.config.execution.dry_run
        )

        # Initialize order manager
        self.order_manager = OrderManager(self.clob_client)

        # Register kill switch callback to cancel all orders
        self.kill_switch.register_callback(self._emergency_shutdown)

        # Store repositories for later use
        self.order_repo = order_repo
        self.fill_repo = fill_repo
        self.position_repo = position_repo
        self.decision_repo = decision_repo

        logger.info("Bot initialization complete")

    def start(self) -> None:
        """Start the bot."""
        logger.info("Starting Polymarket bot...")

        # Start feeds
        self.book_feed.start()
        self.spot_feed.start()

        # For simulated feeds, set some initial data
        if isinstance(self.book_feed, SimulatedBookFeed):
            markets = self.registry.get_all_markets()
            for market in markets.values():
                self.book_feed.set_simulated_price(market.yes_token_id, 0.50, 0.02)

        if isinstance(self.spot_feed, SimulatedSpotFeed):
            self.spot_feed.set_price("BTCUSDT", 100000.0)
            self.spot_feed.set_price("ETHUSDT", 5000.0)

        self.running = True
        logger.info("Bot started")

    def stop(self) -> None:
        """Stop the bot."""
        logger.info("Stopping Polymarket bot...")
        self.running = False

        # Stop feeds
        if self.book_feed:
            self.book_feed.stop()
        if self.spot_feed:
            self.spot_feed.stop()

        # Close database
        if self.db:
            self.db.close()

        logger.info("Bot stopped")

    def _emergency_shutdown(self) -> None:
        """Emergency shutdown callback for kill switch."""
        logger.critical("EMERGENCY SHUTDOWN TRIGGERED")
        try:
            # Cancel all open orders
            self.order_manager.cancel_all_orders()
        except Exception as e:
            logger.error(f"Error during emergency shutdown: {e}", exc_info=True)

    def run_loop(self) -> None:
        """Main bot loop."""
        loop_interval_seconds = self.config.loop_interval_ms / 1000.0

        while self.running:
            try:
                loop_start = time.time()

                # Run one iteration
                self._run_iteration()

                # Sleep for remainder of interval
                elapsed = time.time() - loop_start
                sleep_time = max(0, loop_interval_seconds - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)

            except KeyboardInterrupt:
                logger.info("Received interrupt signal, shutting down...")
                break
            except Exception as e:
                logger.error(f"Error in main loop: {e}", exc_info=True)
                time.sleep(1)  # Brief pause before retrying

    def _run_iteration(self) -> None:
        """Run one iteration of the main loop."""
        # Check kill switch
        if self.kill_switch.is_active():
            logger.warning("Kill switch active, skipping iteration")
            return

        current_ts = int(datetime.now().timestamp())

        # Get active markets
        markets = self.registry.get_active_markets(current_ts)
        if not markets:
            logger.debug("No active markets")
            return

        # Get current orderbooks and reference prices
        books = self.book_feed.get_all_books()
        ref_prices = self.spot_feed.get_all_prices()

        # Get current positions
        positions = self.pnl_tracker.get_all_positions()

        # Get current open orders
        open_orders = self.order_repo.get_open_orders()

        # Generate intents
        intents = self.hybrid_router.generate_all_intents(
            markets=markets,
            books=books,
            ref_prices=ref_prices,
            positions=positions,
            current_ts=current_ts
        )

        # Risk check and execute each intent
        for intent in intents:
            try:
                # Get current mid for risk check
                book = books.get(intent.token_id)
                current_mid = book.mid if book and book.mid else 0.5

                # Risk check
                self.risk_engine.check_intent(
                    intent=intent,
                    positions=positions,
                    open_orders=open_orders,
                    current_mid=current_mid
                )

                # Log accepted decision
                self.decision_repo.log_decision(intent, accepted=True)

            except Exception as e:
                # Risk check failed
                logger.warning(f"Intent rejected by risk engine: {e}")
                self.decision_repo.log_decision(intent, accepted=False, rejection_reason=str(e))
                continue

        # Reconcile intents with open orders (place/cancel/replace)
        # Only pass intents that passed risk checks
        accepted_intents = [i for i in intents]  # TODO: filter only accepted
        self.order_manager.reconcile(accepted_intents, open_orders)

        # Log metrics
        current_mids = {token_id: book.mid for token_id, book in books.items() if book.mid}
        pnl = self.pnl_tracker.calculate_total_pnl(current_mids)
        metrics = self.risk_engine.get_metrics(positions, open_orders, current_mids)

        logger.info(
            f"Loop complete: {len(intents)} intents, {metrics.num_open_orders} open orders, "
            f"PnL={pnl['total']:.2f} (realized={pnl['realized']:.2f}, unrealized={pnl['unrealized']:.2f})"
        )


def signal_handler(signum, frame):
    """Handle shutdown signals."""
    logger.info(f"Received signal {signum}, initiating shutdown...")
    sys.exit(0)


def main():
    """Main entry point."""
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Create and run bot
    bot = PolymarketBot()

    try:
        bot.initialize()
        bot.start()
        bot.run_loop()
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        bot.stop()


if __name__ == "__main__":
    main()
