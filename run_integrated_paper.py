#!/usr/bin/env python3
"""
Run Integrated Paper Trading with Maker + Taker modes
Uses multi-source crypto prices for fair value estimation
"""

import asyncio
import argparse
import logging
import signal
import sys
from datetime import datetime, timezone
from decimal import Decimal

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('paper_trading.log')
    ]
)
logger = logging.getLogger(__name__)

# Add project root to path
sys.path.insert(0, '/root/kalshi-bot')

from paper_trading.integrated_engine import IntegratedPaperEngine, TradingOpportunity
from connectors.kalshi import KalshiClient, create_kalshi_client


class PaperTradingRunner:
    """Runs the integrated paper trading system."""
    
    def __init__(
        self,
        capital: float = 1000.0,
        interval: int = 60,
        max_trades_per_cycle: int = 3,
        maker_enabled: bool = True,
        taker_enabled: bool = True,
        min_edge_taker: int = 3,
        min_edge_maker: int = 2,
        data_dir: str = "integrated_paper_data"
    ):
        self.capital = Decimal(str(capital))
        self.interval = interval
        self.max_trades_per_cycle = max_trades_per_cycle
        self.maker_enabled = maker_enabled
        self.taker_enabled = taker_enabled
        self.min_edge_taker = min_edge_taker
        self.min_edge_maker = min_edge_maker
        self.data_dir = data_dir
        
        self.engine: IntegratedPaperEngine = None
        self.kalshi: KalshiClient = None
        self.running = False
        self.cycle_count = 0
        
    async def initialize(self):
        """Initialize all components."""
        logger.info("Initializing paper trading system...")
        
        # Create integrated engine
        self.engine = IntegratedPaperEngine(
            initial_capital=self.capital,
            data_dir=self.data_dir,
            maker_enabled=self.maker_enabled,
            taker_enabled=self.taker_enabled,
            min_edge_taker=self.min_edge_taker,
            min_edge_maker=self.min_edge_maker
        )
        
        # Create Kalshi client
        self.kalshi = await create_kalshi_client(use_tor=True)
        await self.kalshi.connect()
        
        logger.info(f"Paper trading initialized with ${self.capital} capital")
        logger.info(f"Maker: {self.maker_enabled}, Taker: {self.taker_enabled}")
        logger.info(f"Min edge: Taker {self.min_edge_taker}c, Maker {self.min_edge_maker}c")
        
    async def fetch_markets(self) -> list:
        """Fetch markets from Kalshi with orderbook data."""
        try:
            # Get markets from allowed series
            raw_markets = await self.kalshi.get_markets(status="open", limit=500)
            
            markets = []
            processed = 0
            for raw in raw_markets:
                if processed >= 50:  # Limit to 50 for speed
                    break
                    
                ticker = raw.get("ticker", "")
                
                # Only process crypto 15m and hourly markets
                if not any(x in ticker.upper() for x in ["KXBTC", "KXETH", "KXSOL", "KXDOGE"]):
                    continue
                    
                processed += 1
                    
                # Get orderbook
                try:
                    data = await self.kalshi.get_orderbook(ticker, depth=3)
                    if data:
                        # Kalshi format: {'orderbook': {'yes': [[price, size], ...], 'no': [[price, size], ...]}}
                        ob = data.get("orderbook", data)  # Handle both formats
                        
                        # YES side: bids are what we want to buy at
                        yes_levels = ob.get("yes") or []  # [[price, size], ...]
                        # NO side: bids here imply YES asks (100 - no_bid)
                        no_levels = ob.get("no") or []
                        
                        best_bid = 0
                        best_ask = 100
                        
                        # YES bids (we can sell YES at these prices)
                        if yes_levels:
                            best_bid = max(level[0] for level in yes_levels)
                            
                        # NO bids imply YES asks: if someone bids 79c for NO, 
                        # that's equivalent to offering YES at (100-79)=21c
                        if no_levels:
                            implied_ask = 100 - max(level[0] for level in no_levels)
                            best_ask = min(best_ask, implied_ask)
                            
                        # Also check direct YES asks if present
                        # (Kalshi sometimes has direct YES asks too)
                            
                        if best_bid > 0 and best_ask < 100 and best_ask > best_bid:
                            markets.append({
                                "ticker": ticker,
                                "yes_bid": best_bid / 100,
                                "yes_ask": best_ask / 100,
                                "volume": raw.get("volume", 0)
                            })
                except Exception as e:
                    logger.debug(f"Orderbook error for {ticker}: {e}")
                    
            return markets
            
        except Exception as e:
            logger.error(f"Error fetching markets: {e}")
            return []
            
    async def run_cycle(self):
        """Run one trading cycle."""
        self.cycle_count += 1
        logger.info(f"\n{'='*60}")
        logger.info(f"CYCLE {self.cycle_count} - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
        logger.info(f"{'='*60}")
        
        # Get current crypto prices
        prices = await self.engine.get_crypto_prices()
        btc_price = prices.get('BTC')
        eth_price = prices.get('ETH')
        btc_val = float(btc_price.fair_value) if btc_price else 0
        eth_val = float(eth_price.fair_value) if eth_price else 0
        logger.info(f"Crypto prices: BTC=${btc_val:,.0f}, ETH=${eth_val:,.0f}")
        
        # Fetch markets
        markets = await self.fetch_markets()
        logger.info(f"Found {len(markets)} markets with orderbook data")
        
        if not markets:
            logger.info("No tradeable markets found")
            return
            
        # Scan for opportunities
        opportunities = await self.engine.scan_for_opportunities(markets)
        logger.info(f"Found {len(opportunities)} trading opportunities")
        
        # Execute top opportunities
        trades_executed = 0
        for opp in opportunities[:self.max_trades_per_cycle]:
            if trades_executed >= self.max_trades_per_cycle:
                break
                
            logger.info(f"\nOpportunity: {opp.mode.value.upper()} {opp.side.value.upper()} {opp.ticker}")
            logger.info(f"  Fair: {float(opp.fair_value):.2%}, Market: {float(opp.market_price):.2%}")
            logger.info(f"  Edge: {opp.edge}c, Qty: {opp.quantity}, Expected: ${float(opp.expected_profit):.2f}")
            
            # Execute paper trade
            order = self.engine.execute_paper_trade(opp)
            if order:
                trades_executed += 1
                logger.info(f"  -> EXECUTED: {order.order_id}")
            else:
                logger.info(f"  -> SKIPPED (risk limits)")
                
        # Save snapshot
        self.engine.save_snapshot()
        
        # Print status
        status = self.engine.get_status()
        logger.info(f"\nPORTFOLIO STATUS:")
        logger.info(f"  Cash: ${status['cash']:.2f}")
        logger.info(f"  Positions: {status['positions_count']}")
        logger.info(f"  Total Value: ${status['total_value']:.2f}")
        logger.info(f"  Trades: {status['total_trades']}")
        logger.info(f"  Return: {status['return_pct']:.2f}%")
        
    async def run(self):
        """Run the main trading loop."""
        await self.initialize()
        
        self.running = True
        logger.info("\n" + "="*60)
        logger.info("INTEGRATED PAPER TRADING STARTED")
        if self.maker_enabled and self.taker_enabled:
            mode_str = "MAKER+TAKER"
        elif self.maker_enabled:
            mode_str = "MAKER"
        else:
            mode_str = "TAKER"
        logger.info(f"Mode: {mode_str}")
        logger.info(f"Interval: {self.interval}s")
        logger.info("="*60)
        
        try:
            while self.running:
                try:
                    await self.run_cycle()
                except Exception as e:
                    logger.error(f"Cycle error: {e}")
                    import traceback
                    traceback.print_exc()
                    
                # Wait for next cycle
                logger.info(f"\nNext cycle in {self.interval} seconds...")
                await asyncio.sleep(self.interval)
                
        except asyncio.CancelledError:
            logger.info("Trading loop cancelled")
        finally:
            await self.shutdown()
            
    async def shutdown(self):
        """Cleanup on shutdown."""
        logger.info("Shutting down...")
        self.running = False
        
        if self.engine:
            # Print final status
            status = self.engine.get_status()
            logger.info("\nFINAL STATUS:")
            logger.info(f"  Total Trades: {status['total_trades']}")
            logger.info(f"  Final Value: ${status['total_value']:.2f}")
            logger.info(f"  Return: {status['return_pct']:.2f}%")
            
            await self.engine.close()
            
        if self.kalshi:
            await self.kalshi.close()
            
        logger.info("Shutdown complete")


def main():
    parser = argparse.ArgumentParser(description="Integrated Paper Trading with Maker+Taker")
    parser.add_argument("--capital", type=float, default=1000, help="Starting capital")
    parser.add_argument("--interval", type=int, default=60, help="Seconds between cycles")
    parser.add_argument("--max-trades", type=int, default=3, help="Max trades per cycle")
    parser.add_argument("--maker", action="store_true", default=True, help="Enable maker mode")
    parser.add_argument("--no-maker", action="store_false", dest="maker", help="Disable maker mode")
    parser.add_argument("--taker", action="store_true", default=True, help="Enable taker mode")
    parser.add_argument("--no-taker", action="store_false", dest="taker", help="Disable taker mode")
    parser.add_argument("--min-edge-taker", type=int, default=3, help="Min taker edge in cents")
    parser.add_argument("--min-edge-maker", type=int, default=2, help="Min maker edge in cents")
    parser.add_argument("--data-dir", type=str, default="integrated_paper_data", help="Data directory")
    
    args = parser.parse_args()
    
    runner = PaperTradingRunner(
        capital=args.capital,
        interval=args.interval,
        max_trades_per_cycle=args.max_trades,
        maker_enabled=args.maker,
        taker_enabled=args.taker,
        min_edge_taker=args.min_edge_taker,
        min_edge_maker=args.min_edge_maker,
        data_dir=args.data_dir
    )
    
    # Handle signals
    def signal_handler(sig, frame):
        logger.info("\nReceived shutdown signal")
        runner.running = False
        
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Run
    asyncio.run(runner.run())


if __name__ == "__main__":
    main()
