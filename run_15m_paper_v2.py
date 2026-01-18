#!/usr/bin/env python3
"""
15-Minute Crypto Paper Trading Bot v2
Directly queries 15m series with proper "active" status filter.
"""

import asyncio
import logging
import argparse
import sys
import aiohttp
from aiohttp_socks import ProxyConnector
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).parent))

from connectors.kalshi import create_kalshi_client
from connectors.crypto_aggregator import get_aggregator
from paper_trading.integrated_engine import IntegratedPaperEngine

# 15-minute series
SERIES_15M = ["KXBTC15M", "KXETH15M", "KXSOL15M"]


class Fast15mPaperTrader:
    """Paper trader that ONLY trades 15-minute markets."""
    
    def __init__(
        self,
        initial_capital: float = 500,
        interval: int = 30,
        max_trades_per_cycle: int = 5,
        min_edge_taker: int = 2,
        min_edge_maker: int = 1
    ):
        self.initial_capital = Decimal(str(initial_capital))
        self.interval = interval
        self.max_trades_per_cycle = max_trades_per_cycle
        self.min_edge_taker = min_edge_taker
        self.min_edge_maker = min_edge_maker
        
        self.kalshi = None
        self.crypto_agg = get_aggregator()
        self.engine = None
        self.cycle_count = 0
        
    async def initialize(self):
        """Initialize connections."""
        self.kalshi = await create_kalshi_client(use_tor=True)
        await self.kalshi.connect()
        
        self.engine = IntegratedPaperEngine(
            initial_capital=self.initial_capital,
            data_dir="paper_15m_data",
            maker_enabled=True,
            taker_enabled=True,
            min_edge_taker=self.min_edge_taker,
            min_edge_maker=self.min_edge_maker,
            max_position_per_market=Decimal("0.20"),
            kelly_fraction=Decimal("0.5")
        )
        
        logger.info(f"15M Paper Trading initialized with ${self.initial_capital} capital")
        logger.info(f"Mode: MAKER+TAKER | Interval: {self.interval}s")
        
    async def fetch_15m_markets_direct(self):
        """Fetch 15-minute markets directly from API with 'active' status."""
        markets = []
        
        connector = ProxyConnector.from_url("socks5://127.0.0.1:9050")
        
        try:
            async with aiohttp.ClientSession(connector=connector) as session:
                for series in SERIES_15M:
                    url = "https://api.elections.kalshi.com/trade-api/v2/markets"
                    # Key fix: use status=open for 15m markets
                    params = {"series_ticker": series, "status": "open", "limit": 50}
                    
                    try:
                        async with session.get(url, params=params) as resp:
                            data = await resp.json()
                            series_markets = data.get("markets", [])
                            
                            for m in series_markets:
                                ticker = m.get("ticker", "")
                                yes_bid = m.get("yes_bid", 0)
                                yes_ask = m.get("yes_ask", 0)
                                no_bid = m.get("no_bid", 0)
                                
                                # Calculate implied ask from NO bid
                                if no_bid > 0:
                                    implied_ask = 100 - no_bid
                                    if implied_ask < yes_ask or yes_ask == 0:
                                        yes_ask = implied_ask
                                
                                if yes_bid > 0 and yes_ask > 0 and yes_ask > yes_bid:
                                    markets.append({
                                        "ticker": ticker,
                                        "yes_bid": yes_bid / 100,
                                        "yes_ask": yes_ask / 100,
                                        "volume": m.get("volume", 0)
                                    })
                                    logger.debug(f"Found active 15m market: {ticker} bid={yes_bid}c ask={yes_ask}c")
                    except Exception as e:
                        logger.debug(f"Error fetching {series}: {e}")
                        
        except Exception as e:
            logger.error(f"Error in direct API call: {e}")
        
        return markets
    
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
            
            # Get 15m markets with direct API call
            markets = await self.fetch_15m_markets_direct()
            logger.info(f"Found {len(markets)} active 15-minute markets")
            
            if not markets:
                logger.info("No active 15m markets found")
                return
            
            for m in markets:
                logger.info(f"  {m['ticker']}: bid={m['yes_bid']*100:.0f}c ask={m['yes_ask']*100:.0f}c")
            
            # Scan for opportunities
            opportunities = await self.engine.scan_for_opportunities(markets)
            logger.info(f"Found {len(opportunities)} trading opportunities")
            
            if opportunities:
                for opp in opportunities[:5]:
                    logger.info(f"  {opp.mode.value.upper()} {opp.side.value.upper()} {opp.ticker}: "
                               f"Fair {opp.fair_value*100:.1f}%, Edge {opp.edge}c, Qty {opp.quantity}")
                
                # Execute trades
                trades_executed = 0
                for opp in opportunities:
                    if trades_executed >= self.max_trades_per_cycle:
                        break
                    
                    order = self.engine.execute_paper_trade(opp)
                    if order:
                        trades_executed += 1
                        logger.info(f"PAPER TRADE: {order.order_id} - {order.mode.value.upper()} {order.side.value.upper()} "
                                   f"{order.quantity}x {order.ticker} @ {order.price}c")
                
                logger.info(f"Executed {trades_executed} trades this cycle")
            
            # Portfolio status
            status = self.engine.get_status()
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
        logger.info("15-MINUTE PAPER TRADING BOT v2 STARTED")
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
    parser = argparse.ArgumentParser(description="15-Minute Crypto Paper Trading Bot v2")
    parser.add_argument("--capital", type=float, default=500, help="Initial capital")
    parser.add_argument("--interval", type=int, default=30, help="Cycle interval")
    parser.add_argument("--max-trades", type=int, default=5, help="Max trades per cycle")
    parser.add_argument("--min-edge-taker", type=int, default=2, help="Min taker edge")
    parser.add_argument("--min-edge-maker", type=int, default=1, help="Min maker edge")
    
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
