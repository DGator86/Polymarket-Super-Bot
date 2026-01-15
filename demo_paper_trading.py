#!/usr/bin/env python3
"""
Demo Paper Trading Mode

Demonstrates the paper trading system with simulated market data
when Kalshi API credentials are not fully configured.

This shows:
- Paper trading engine functionality
- ML predictor integration
- Analytics and reporting
- Virtual portfolio management
"""

import asyncio
import logging
import random
import uuid
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'
)
logger = logging.getLogger(__name__)

# Import paper trading components
from paper_trading.engine import (
    PaperTradingEngine, PaperPosition, PaperTrade, TradeOutcome
)
from paper_trading.analytics import AnalyticsEngine
from core.models import (
    Side, MarketCategory, NormalizedMarket, TradingSignal, SignalType, Venue
)

try:
    from ml.predictor import TradePredictor, OnlineModelUpdater
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
    logger.warning("ML predictor not available - continuing without ML")


class MockKalshiClient:
    """Mock Kalshi client for demonstration"""
    
    async def connect(self):
        logger.info("Mock Kalshi client connected")
        
    async def close(self):
        logger.info("Mock Kalshi client disconnected")
    
    async def get_orderbook(self, ticker: str):
        """Generate mock orderbook data"""
        mid = Decimal(str(random.uniform(0.30, 0.70)))
        spread = Decimal(str(random.uniform(0.02, 0.08)))
        return {
            'ticker': ticker,
            'bids': [{'price': float(mid - spread/2), 'size': random.randint(50, 200)}],
            'asks': [{'price': float(mid + spread/2), 'size': random.randint(50, 200)}]
        }


def generate_mock_markets(count: int = 20) -> list:
    """Generate mock market data for demonstration"""
    categories = list(MarketCategory)
    markets = []
    
    market_templates = [
        ("BTC price above ${} by {}", MarketCategory.CRYPTO),
        ("ETH price above ${} by {}", MarketCategory.CRYPTO),
        ("Fed rate decision {}", MarketCategory.ECONOMICS),
        ("CPI YoY above {}%", MarketCategory.ECONOMICS),
        ("Hurricane {} makes landfall", MarketCategory.WEATHER),
        ("Temperature in NYC above {}F", MarketCategory.WEATHER),
        ("{} wins election", MarketCategory.POLITICS),
        ("Bill {} passes", MarketCategory.POLITICS),
    ]
    
    for i in range(count):
        template, category = random.choice(market_templates)
        
        # Generate realistic-looking ticker
        ticker = f"MOCK-{uuid.uuid4().hex[:8].upper()}"
        
        # Generate question
        if category == MarketCategory.CRYPTO:
            question = template.format(
                random.randint(40000, 60000) if 'BTC' in template else random.randint(2000, 4000),
                (datetime.now() + timedelta(hours=random.randint(1, 48))).strftime("%b %d")
            )
        elif category == MarketCategory.ECONOMICS:
            if 'CPI' in template:
                question = template.format(random.uniform(2.0, 4.0))
            else:
                question = template.format(random.choice(['hike', 'hold', 'cut']))
        elif category == MarketCategory.WEATHER:
            if 'Hurricane' in template:
                question = template.format(random.choice(['Alpha', 'Beta', 'Gamma']))
            else:
                question = template.format(random.randint(70, 90))
        else:
            question = template.format(random.choice(['A', 'B', 'C']))
        
        # Generate prices
        mid = Decimal(str(round(random.uniform(0.25, 0.75), 2)))
        spread = Decimal(str(round(random.uniform(0.02, 0.08), 2)))
        
        market = NormalizedMarket(
            venue=Venue.KALSHI,
            ticker=ticker,
            question=question,
            category=category,
            expiry=datetime.now(timezone.utc) + timedelta(hours=random.randint(2, 72)),
            best_bid=mid - spread/2,
            best_ask=mid + spread/2,
            bid_size=random.randint(50, 300),
            ask_size=random.randint(50, 300),
            last_price=mid,
            volume_24h=Decimal(str(random.randint(1000, 50000))),
            open_interest=random.randint(100, 5000),
            last_update=datetime.now(timezone.utc)
        )
        markets.append(market)
    
    return markets


def generate_mock_signal(market: NormalizedMarket) -> TradingSignal:
    """Generate a mock trading signal for a market"""
    model_prob = Decimal(str(round(random.uniform(0.35, 0.65), 3)))
    market_prob = market.implied_prob_mid
    
    # Determine side based on model vs market
    if model_prob > market_prob + Decimal("0.05"):
        side = Side.YES
        edge = model_prob - market_prob
    elif model_prob < market_prob - Decimal("0.05"):
        side = Side.NO
        edge = market_prob - model_prob
    else:
        side = random.choice([Side.YES, Side.NO])
        edge = Decimal(str(round(random.uniform(0.03, 0.10), 3)))
    
    return TradingSignal(
        signal_id=str(uuid.uuid4()),
        signal_type=SignalType.MODEL,
        ticker=market.ticker,
        venue=Venue.KALSHI,
        side=side,
        model_probability=model_prob,
        market_probability=market_prob,
        confidence=Decimal(str(round(random.uniform(0.60, 0.95), 2))),
        edge=edge,
        urgency=Decimal(str(round(random.uniform(0.3, 0.9), 2))),
        max_position=random.randint(10, 100),
        reason=f"Model edge: {edge:.1%} | Confidence: {random.uniform(0.6, 0.95):.0%}",
        metadata={
            "model_version": "demo_v1",
            "features": ["price_momentum", "volume", "sentiment"]
        },
        created_at=datetime.now(timezone.utc)
    )


async def demo_paper_trading():
    """Run paper trading demonstration"""
    print("=" * 70)
    print("KALSHI PAPER TRADING SYSTEM - DEMO MODE")
    print("=" * 70)
    print()
    print("This demo shows the paper trading system with simulated data.")
    print("The full system requires Kalshi API credentials to be configured.")
    print("See KALSHI_SETUP.md for instructions on uploading your public key.")
    print()
    print("=" * 70)
    
    # Initialize paper trading engine
    data_dir = Path("./paper_trading_demo_data")
    engine = PaperTradingEngine(
        starting_capital=Decimal("1000"),
        data_dir=str(data_dir)
    )
    
    # Use mock Kalshi client
    mock_client = MockKalshiClient()
    await mock_client.connect()
    await engine.initialize(mock_client)
    
    logger.info("Paper trading engine initialized with $1000 virtual capital")
    
    # Initialize ML predictor if available
    ml_predictor = None
    if ML_AVAILABLE:
        try:
            ml_predictor = TradePredictor(model_dir=str(data_dir / "ml_models"))
            logger.info("ML predictor initialized")
        except Exception as e:
            logger.warning(f"ML predictor initialization failed: {e}")
    
    # Generate mock markets
    markets = generate_mock_markets(15)
    logger.info(f"Generated {len(markets)} mock markets for simulation")
    
    # Run simulation cycles
    num_cycles = 5
    positions_per_cycle = 2
    
    for cycle in range(1, num_cycles + 1):
        print()
        logger.info(f"{'='*20} CYCLE {cycle}/{num_cycles} {'='*20}")
        
        # Update existing position prices (simulate price movement)
        for pos in engine.positions.values():
            if not pos.settled:
                # Random price movement
                move = Decimal(str(round(random.uniform(-0.05, 0.05), 2)))
                pos.current_price = max(Decimal("0.01"), min(Decimal("0.99"), pos.current_price + move))
                pos.last_update = datetime.now(timezone.utc)
        
        open_count = len([p for p in engine.positions.values() if not p.settled])
        logger.info(f"Updated {open_count} position prices")
        
        # Check for settlements (positions near expiry)
        settled_count = 0
        for pos in list(engine.positions.values()):
            if not pos.settled and pos.expiry <= datetime.now(timezone.utc) + timedelta(minutes=5):
                # Simulate settlement
                settlement_value = Decimal("1") if random.random() > 0.5 else Decimal("0")
                pos.settlement_value = settlement_value
                pos.settled = True
                pos.exit_time = datetime.now(timezone.utc)
                
                if pos.side == Side.YES:
                    pos.outcome = TradeOutcome.WIN if settlement_value == Decimal("1") else TradeOutcome.LOSS
                else:
                    pos.outcome = TradeOutcome.WIN if settlement_value == Decimal("0") else TradeOutcome.LOSS
                
                settled_count += 1
        
        if settled_count > 0:
            logger.info(f"Settled {settled_count} positions")
        
        # Process settlements (finalize P&L)
        await engine.process_settlements()
        
        # Take snapshot
        engine.take_snapshot()
        
        # Print portfolio status
        stats = engine.get_performance_stats()
        open_positions_count = len([p for p in engine.positions.values() if not p.settled])
        logger.info(f"Portfolio: ${engine.cash:.2f} cash | {open_positions_count} open positions")
        logger.info(f"Total P&L: ${stats['total_pnl']:.2f} | Win Rate: {stats['win_rate']:.1%}")
        
        # Enter new positions if room
        available_slots = 10 - open_positions_count
        if available_slots > 0:
            # Filter to unexpired markets
            active_markets = [m for m in markets if m.expiry > datetime.now(timezone.utc)]
            
            # Generate signals and enter positions
            entries = 0
            for market in random.sample(active_markets, min(positions_per_cycle, len(active_markets), available_slots)):
                signal = generate_mock_signal(market)
                
                # Calculate position size
                max_per_trade = engine.cash * Decimal("0.10")  # 10% max
                entry_price = market.best_ask if signal.side == Side.YES else (Decimal("1") - market.best_bid)
                size = min(50, max(1, int(max_per_trade / entry_price)))
                
                # Apply ML filter if available
                should_enter = True
                win_prob = None
                
                if ml_predictor and ml_predictor.is_trained:
                    features = {
                        'signal_edge': float(signal.edge),
                        'signal_confidence': float(signal.confidence),
                        'model_probability': float(signal.model_probability),
                        'market_probability': float(signal.market_probability),
                        'entry_price': float(entry_price),
                        'time_held_hours': 24,
                        'category': market.category.value,
                        'side': signal.side.value
                    }
                    win_prob = ml_predictor.predict_win_probability(features)
                    should_enter = win_prob > 0.55
                
                if should_enter:
                    success = await engine.enter_position(signal, market, size)
                    if success:
                        entries += 1
                        logger.info(f"Entered position: {market.ticker} | {signal.side.value} | {size} contracts @ ${entry_price:.2f}")
            
            if entries > 0:
                logger.info(f"Entered {entries} new positions")
        
        # Small delay between cycles
        await asyncio.sleep(0.5)
    
    # Final report
    print()
    print("=" * 70)
    print("DEMO SIMULATION COMPLETE")
    print("=" * 70)
    
    stats = engine.get_performance_stats()
    
    # Handle case when no trades have completed yet
    current_equity = stats.get('current_equity', float(engine.cash))
    total_trades = stats.get('total_trades', 0)
    wins = stats.get('wins', 0)
    losses = stats.get('losses', 0)
    win_rate = stats.get('win_rate', 0)
    total_pnl = stats.get('total_pnl', 0)
    open_pos_count = len([p for p in engine.positions.values() if not p.settled])
    
    print(f"""
Final Results:
--------------
Starting Capital:  $1,000.00
Final Equity:      ${current_equity:.2f}
Return:            {((current_equity - 1000) / 1000 * 100):.1f}%

Total Trades:      {total_trades}
Wins:              {wins}
Losses:            {losses}
Win Rate:          {win_rate:.1%}

Total P&L:         ${total_pnl:.2f}
Open Positions:    {open_pos_count}
""")
    
    # Analytics
    db_path = data_dir / "paper_trades.db"
    analytics = AnalyticsEngine(db_path=str(db_path))
    report = analytics.generate_report(days=7)
    
    print(f"""
Performance Report:
-------------------
Period:           {report.period_start} to {report.period_end}
Total Trades:     {report.total_trades}
Win Rate:         {report.win_rate:.1%}
Profit Factor:    {report.profit_factor:.2f}
""")
    
    # Clean up
    engine.close()
    analytics.close()
    await mock_client.close()
    
    print()
    print("To run with live Kalshi data:")
    print("1. Upload public key to Kalshi dashboard (see KALSHI_SETUP.md)")
    print("2. Run: python3 run_paper_trading.py --capital 1000")
    print()


if __name__ == "__main__":
    asyncio.run(demo_paper_trading())
