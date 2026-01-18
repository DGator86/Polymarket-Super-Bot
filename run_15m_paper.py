#!/usr/bin/env python3
"""
15-Minute Crypto Paper Trading Bot
Focuses ONLY on 15-minute up/down markets for faster turnover and risk spreading.
Runs parallel to the main aggressive bot.
"""

import asyncio
import logging
import argparse
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent))

from connectors.kalshi import KalshiClient, create_kalshi_client
from connectors.crypto_aggregator import get_aggregator
from paper_trading.integrated_engine import IntegratedPaperEngine


class Fast15mPaperTrader:
    """Paper trader that ONLY trades 15-minute markets."""
    
    def __init__(
        self,
        initial_capital: float = 500,
        interval: int = 30,  # Faster cycles for 15m markets
        max_trades_per_cycle: int = 5,
        min_edge_taker: int = 2,
        min_edge_maker: int = 1
    ):
        self.initial_capital = Decimal(str(initial_capital))
        self.interval = interval
        self.max_trades_per_cycle = max_trades_per_cycle
        self.min_edge_taker = min_edge_taker
        self.min_edge_maker = min_edge_maker
        
        # Will be initialized later
        self.kalshi: KalshiClient = None
        self.crypto_agg = get_aggregator()
        self.engine = None
        
        self.cycle_count = 0
        
    async def initialize(self):
        """Initialize connections."""
        # Create Kalshi client
        self.kalshi = await create_kalshi_client(use_tor=True)
        await self.kalshi.connect()
        
        # Engine with separate data directory
        self.engine = IntegratedPaperEngine(
            initial_capital=self.initial_capital,
            data_dir="paper_15m_data",  # Separate from main bot
            maker_enabled=True,
            taker_enabled=True,
            min_edge_taker=self.min_edge_taker,
            min_edge_maker=self.min_edge_maker,
            max_position_per_market=Decimal("0.20"),  # 20% per market for 15m
            kelly_fraction=Decimal("0.5")
        )
        
        logger.info(f"15M Paper Trading initialized with ${self.initial_capital} capital")
        logger.info(f"Mode: MAKER+TAKER | Interval: {self.interval}s")
        logger.info(f"Min edge: Taker {self.min_edge_taker}c, Maker {self.min_edge_maker}c")
        
    async def fetch_15m_markets(self):
        """Fetch ONLY 15-minute crypto markets."""
        try:
            raw_markets = await self.kalshi.get_markets(status="open", limit=500)
            
            markets = []
            for raw in raw_markets:
                ticker = raw.get("ticker", "")
                
                # ONLY 15-minute markets
                if "15M" not in ticker.upper():
                    continue
                    
                # Only crypto
                if not any(x in ticker.upper() for x in ["KXBTC", "KXETH", "KXSOL", "KXDOGE"]):
                    continue
                
                # Get orderbook
                try:
                    data = await self.kalshi.get_orderbook(ticker, depth=3)
                    if data:
                        ob = data.get("orderbook", data)
                        yes_levels = ob.get("yes") or []
                        no_levels = ob.get("no") or []
                        
                        best_bid = 0
                        best_ask = 100
                        
                        if yes_levels:
                            best_bid = max(level[0] for level in yes_levels)
                            
                        if no_levels:
                            implied_ask = 100 - max(level[0] for level in no_levels)
                            best_ask = min(best_ask, implied_ask)
                        
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
            logger.error(f"Error fetching 15m markets: {e}")
            return []
    
    async def run_cycle(self):
        """Run one trading cycle."""
        self.cycle_count += 1
        logger.info(f"\n{'='*60}")
        logger.info(f"15M CYCLE {self.cycle_count} - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
        logger.info(f"{'='*60}")
        
        try:
            # Get crypto prices
            prices = await self.crypto_agg.get_prices_for_all_coins()
            btc_price = prices.get("BTC")
            eth_price = prices.get("ETH")
            sol_price = prices.get("SOL")
            
            if btc_price:
                logger.info(f"Crypto: BTC=${btc_price.fair_value:,.0f}, ETH=${eth_price.fair_value if eth_price else 0:,.0f}, SOL=${sol_price.fair_value if sol_price else 0:.2f}")
            
            # Get 15m markets only
            markets = await self.fetch_15m_markets()
            logger.info(f"Found {len(markets)} 15-minute markets with orderbook data")
            
            if not markets:
                logger.info("No 15m markets available")
                return
            
            # Scan for opportunities
            opportunities = await self.engine.scan_for_opportunities(markets, prices)
            logger.info(f"Found {len(opportunities)} trading opportunities")
            
            if opportunities:
                # Log opportunities
                for opp in opportunities[:5]:
                    logger.info(f"  {opp.mode.upper()} {opp.side.upper()} {opp.ticker}: "
                               f"Fair {opp.fair_value*100:.1f}%, Market {opp.market_price*100:.1f}%, "
                               f"Edge {opp.edge}c, Qty {opp.quantity}")
                
                # Execute trades
                trades_executed = 0
                for opp in opportunities:
                    if trades_executed >= self.max_trades_per_cycle:
                        break
                    
                    order = self.engine.execute_paper_trade(opp)
                    if order:
                        trades_executed += 1
                        logger.info(f"PAPER TRADE: {order.order_id} - {order.mode.upper()} {order.side.upper()} "
                                   f"{order.quantity}x {order.ticker} @ {order.price}c")
                
                logger.info(f"Executed {trades_executed} trades this cycle")
            
            # Portfolio status
            status = self.engine.get_portfolio_status()
            logger.info(f"\n15M PORTFOLIO STATUS:")
            logger.info(f"  Cash: ${status['cash']:.2f}")
            logger.info(f"  Positions: {status['positions_count']}")
            logger.info(f"  Total Value: ${status['total_value']:.2f}")
            logger.info(f"  Trades: {status['total_trades']}")
            logger.info(f"  Return: {status['return_pct']:.2f}%")
            
        except Exception as e:
            logger.error(f"Cycle error: {e}")
            import traceback
            traceback.print_exc()
    
    async def run(self):
        """Main run loop."""
        await self.initialize()
        
        logger.info("\n" + "="*60)
        logger.info("15-MINUTE PAPER TRADING BOT STARTED")
        logger.info("="*60)
        
        while True:
            try:
                await self.run_cycle()
                logger.info(f"\nNext cycle in {self.interval} seconds...")
                await asyncio.sleep(self.interval)
            except KeyboardInterrupt:
                logger.info("Shutting down...")
                break
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                await asyncio.sleep(self.interval)


async def main():
    parser = argparse.ArgumentParser(description="15-Minute Crypto Paper Trading Bot")
    parser.add_argument("--capital", type=float, default=500, help="Initial capital")
    parser.add_argument("--interval", type=int, default=30, help="Cycle interval in seconds")
    parser.add_argument("--max-trades", type=int, default=5, help="Max trades per cycle")
    parser.add_argument("--min-edge-taker", type=int, default=2, help="Min taker edge in cents")
    parser.add_argument("--min-edge-maker", type=int, default=1, help="Min maker edge in cents")
    
    args = parser.parse_args()
    
    trader = Fast15mPaperTrader(
        initial_capital=args.capital,
        interval=args.interval,
        max_trades_per_cycle=args.max_trades,
        min_edge_taker=args.min_edge_taker,
        min_edge_maker=args.min_edge_maker
    )
    
    await trader.run()


if __name__ == "__main__":
    asyncio.run(main())
