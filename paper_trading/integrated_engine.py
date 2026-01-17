"""
Integrated Paper Trading Engine with Maker + Taker Modes
Combines crypto aggregator, digital pricer, fee model, and trading strategies
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from enum import Enum
import json
import sqlite3
import os

# Import our modules
import sys
sys.path.insert(0, '/root/kalshi-bot')

from core.fee_model import calculate_taker_fee, calculate_maker_fee, minimum_profitable_edge_taker, minimum_profitable_spread_maker
from core.digital_pricer import price_15m_up_down, price_binary_above, PricerInput, PricerOutput
from core.orderbook import OrderbookManager
from connectors.crypto_aggregator import CryptoAggregator, AggregatedPrice

logger = logging.getLogger(__name__)


class TradeMode(Enum):
    TAKER = "taker"
    MAKER = "maker"


class TradeSide(Enum):
    YES = "yes"
    NO = "no"


@dataclass
class PaperOrder:
    """Paper order for simulation."""
    order_id: str
    ticker: str
    side: TradeSide
    mode: TradeMode
    price: int  # in cents
    quantity: int
    filled_qty: int = 0
    status: str = "open"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    filled_at: Optional[datetime] = None
    fees_paid: int = 0  # in cents


@dataclass
class PaperPosition:
    """Paper position tracking."""
    ticker: str
    side: TradeSide
    quantity: int
    avg_entry_price: Decimal
    unrealized_pnl: Decimal = Decimal(0)


@dataclass
class TradingOpportunity:
    """Detected trading opportunity."""
    ticker: str
    underlying: str  # BTC, ETH, SOL, etc.
    market_type: str  # "15m_up_down" or "hourly_strike"
    side: TradeSide
    mode: TradeMode
    fair_value: Decimal  # Our calculated fair value (0-1)
    market_price: Decimal  # Current market price (0-1)
    edge: Decimal  # Edge in cents
    confidence: float
    quantity: int
    expected_profit: Decimal
    strike: Optional[Decimal] = None  # For hourly markets
    expiry: Optional[datetime] = None


class IntegratedPaperEngine:
    """
    Paper trading engine with both maker and taker modes.
    Uses multi-source crypto prices for fair value estimation.
    """
    
    def __init__(
        self,
        initial_capital: Decimal = Decimal("1000"),
        data_dir: str = "paper_trading_data",
        maker_enabled: bool = True,
        taker_enabled: bool = True,
        min_edge_taker: int = 2,  # cents
        min_edge_maker: int = 1,  # cents
        max_position_per_market: Decimal = Decimal("0.15"),
        max_daily_loss: Decimal = Decimal("0.05"),
        kelly_fraction: Decimal = Decimal("0.5")
    ):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.data_dir = data_dir
        
        # Strategy settings
        self.maker_enabled = maker_enabled
        self.taker_enabled = taker_enabled
        self.min_edge_taker = min_edge_taker
        self.min_edge_maker = min_edge_maker
        self.max_position_per_market = max_position_per_market
        self.max_daily_loss = max_daily_loss
        self.kelly_fraction = kelly_fraction
        
        # Components
        # Fee model uses functions directly
        # Pricer uses functions directly
        self.crypto_agg = CryptoAggregator()
        self.orderbook_mgr = OrderbookManager()
        
        # State
        self.positions: Dict[str, PaperPosition] = {}
        self.open_orders: Dict[str, PaperOrder] = {}
        self.order_history: List[PaperOrder] = []
        self.daily_pnl: Decimal = Decimal(0)
        self.total_pnl: Decimal = Decimal(0)
        self.trade_count = 0
        self.win_count = 0
        
        # Kill switch
        self.kill_switch_active = False
        self.kill_switch_reason = ""
        
        # Initialize storage
        os.makedirs(data_dir, exist_ok=True)
        self._init_db()
        
    def _init_db(self):
        """Initialize SQLite database for paper trading."""
        db_path = os.path.join(self.data_dir, "paper_trades.db")
        self.conn = sqlite3.connect(db_path)
        cursor = self.conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY,
                order_id TEXT,
                ticker TEXT,
                side TEXT,
                mode TEXT,
                price INTEGER,
                quantity INTEGER,
                fees INTEGER,
                pnl REAL,
                created_at TEXT,
                filled_at TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                id INTEGER PRIMARY KEY,
                timestamp TEXT,
                cash REAL,
                positions_value REAL,
                total_value REAL,
                daily_pnl REAL,
                total_pnl REAL
            )
        ''')
        
        self.conn.commit()
        
    async def get_crypto_prices(self) -> Dict[str, AggregatedPrice]:
        """Get aggregated prices from all crypto sources."""
        return await self.crypto_agg.get_prices_for_all_coins()
        
    def _parse_ticker(self, ticker: str) -> Tuple[str, str, Optional[Decimal], Optional[datetime]]:
        """
        Parse Kalshi ticker to extract underlying, market type, strike, expiry.
        
        Examples:
        - KXBTC15M-26JAN170530-30 -> BTC, 15m_up_down, None, 2026-01-17 05:30
        - KXBTC-26JAN1717-B95250 -> BTC, hourly_strike, 95250, 2026-01-17 17:00
        - KXETH-26JAN1717-B3280 -> ETH, hourly_strike, 3280, 2026-01-17 17:00
        """
        underlying = "BTC"
        market_type = "unknown"
        strike = None
        expiry = None
        
        ticker_upper = ticker.upper()
        
        # Determine underlying
        if "ETH" in ticker_upper:
            underlying = "ETH"
        elif "SOL" in ticker_upper:
            underlying = "SOL"
        elif "DOGE" in ticker_upper:
            underlying = "DOGE"
        elif "BTC" in ticker_upper:
            underlying = "BTC"
            
        # Determine market type
        if "15M" in ticker_upper:
            market_type = "15m_up_down"
        elif "-B" in ticker_upper or "hourly" in ticker_upper.lower():
            market_type = "hourly_strike"
            # Extract strike price (e.g., B95250 -> 95250)
            parts = ticker.split("-")
            for part in parts:
                if part.startswith("B") and len(part) > 1:
                    try:
                        strike = Decimal(part[1:])
                    except:
                        pass
                        
        return underlying, market_type, strike, expiry
        
    async def calculate_fair_value(
        self, 
        ticker: str, 
        crypto_prices: Dict[str, AggregatedPrice]
    ) -> Optional[Tuple[Decimal, float]]:
        """
        Calculate fair value for a market using crypto aggregator + digital pricer.
        Returns (fair_value, confidence) where fair_value is 0-1.
        """
        underlying, market_type, strike, expiry = self._parse_ticker(ticker)
        
        if underlying not in crypto_prices:
            return None
            
        agg_price = crypto_prices[underlying]
        current_price = float(agg_price.fair_value)
        
        # Default volatility (can be enhanced with historical data)
        volatility = 0.60  # 60% annualized for crypto
        
        if market_type == "15m_up_down":
            # 15-minute up/down binary
            result = price_15m_up_down(
                current_price=current_price,
                volatility=volatility,
                orderbook_imbalance=0.0,
                recent_return_z=0.0
            )
            return Decimal(str(round(result.fair_value, 4))), 0.8
            
        elif market_type == "hourly_strike" and strike:
            pricer_input = PricerInput(
                current_price=current_price,
                strike=float(strike),
                time_to_expiry_hours=0.5,
                volatility=volatility
            )
            result = price_binary_above(pricer_input)
            return Decimal(str(round(result.fair_value, 4))), 0.8
        
        return None
    def _calculate_edge(
        self,
        fair_value: Decimal,
        market_bid: int,
        market_ask: int,
        mode: TradeMode
    ) -> Tuple[Optional[TradeSide], int, int]:
        """
        Calculate trading edge.
        Returns (side_to_trade, edge_in_cents, price_to_trade).
        """
        fair_cents = int(fair_value * 100)
        
        if mode == TradeMode.TAKER:
            # Taker: cross the spread
            # Buy YES if fair > ask
            yes_edge = fair_cents - market_ask
            # Buy NO if fair < bid (equivalent to selling YES)
            no_edge = market_bid - fair_cents
            
            if yes_edge >= self.min_edge_taker:
                return TradeSide.YES, yes_edge, market_ask
            elif no_edge >= self.min_edge_taker:
                return TradeSide.NO, no_edge, 100 - market_bid  # NO price
                
        elif mode == TradeMode.MAKER:
            # Maker: join the book
            # Quote YES bid below fair value
            yes_bid = fair_cents - self.min_edge_maker
            # Quote NO bid below 1-fair
            no_bid = (100 - fair_cents) - self.min_edge_maker
            
            # Check if we can improve the spread
            mid = (market_bid + market_ask) / 2
            
            if fair_cents > mid + self.min_edge_maker:
                return TradeSide.YES, self.min_edge_maker, max(market_bid + 1, yes_bid)
            elif fair_cents < mid - self.min_edge_maker:
                return TradeSide.NO, self.min_edge_maker, max(100 - market_ask + 1, no_bid)
                
        return None, 0, 0
        
    def _calculate_position_size(
        self,
        edge_cents: int,
        fair_value: Decimal,
        price_cents: int
    ) -> int:
        """Calculate position size using Kelly fraction."""
        # Kelly: f = p - q/b where p=win prob, q=lose prob, b=odds
        p = float(fair_value) if fair_value > Decimal("0.5") else 1 - float(fair_value)
        q = 1 - p
        
        # Odds: potential win / potential loss
        if price_cents <= 0 or price_cents >= 100:
            return 0
            
        potential_win = 100 - price_cents
        potential_loss = price_cents
        b = potential_win / potential_loss
        
        kelly = (p * b - q) / b
        kelly = max(0, min(kelly, 0.5))  # Cap at 50% for aggressive mode
        
        # Apply our fraction
        fraction = kelly * float(self.kelly_fraction)
        
        # Max position value
        max_value = float(self.cash) * float(self.max_position_per_market)
        
        # Contracts we can buy
        cost_per_contract = price_cents / 100
        max_contracts = int(max_value / cost_per_contract) if cost_per_contract > 0 else 0
        
        # Apply Kelly sizing
        contracts = int(max_contracts * fraction)
        
        return max(0, min(contracts, 250))  # Min 0, max 250 contracts for aggressive mode
        
    async def scan_for_opportunities(
        self,
        markets: List[dict]
    ) -> List[TradingOpportunity]:
        """Scan markets for trading opportunities."""
        if self.kill_switch_active:
            logger.warning(f"Kill switch active: {self.kill_switch_reason}")
            return []
            
        opportunities = []
        crypto_prices = await self.get_crypto_prices()
        
        for market in markets:
            ticker = market.get("ticker", "")
            
            # Skip if no orderbook data
            if not market.get("yes_bid") or not market.get("yes_ask"):
                continue
                
            yes_bid = int(market.get("yes_bid", 0) * 100)
            yes_ask = int(market.get("yes_ask", 0) * 100)
            
            if yes_bid <= 0 or yes_ask <= 0 or yes_ask <= yes_bid:
                continue
                
            # Get fair value
            result = await self.calculate_fair_value(ticker, crypto_prices)
            if not result:
                continue
                
            fair_value, confidence = result
            
            if confidence < 0.5:  # Skip low confidence
                continue
                
            # Check for taker opportunities
            if self.taker_enabled:
                side, edge, price = self._calculate_edge(
                    fair_value, yes_bid, yes_ask, TradeMode.TAKER
                )
                if side and edge >= self.min_edge_taker:
                    qty = self._calculate_position_size(edge, fair_value, price)
                    if qty > 0:
                        underlying, market_type, strike, _ = self._parse_ticker(ticker)
                        
                        # Calculate expected profit
                        fee = calculate_taker_fee(qty, price).total_fee_cents
                        expected = Decimal(str(edge * qty / 100)) - Decimal(str(fee / 100))
                        
                        opportunities.append(TradingOpportunity(
                            ticker=ticker,
                            underlying=underlying,
                            market_type=market_type,
                            side=side,
                            mode=TradeMode.TAKER,
                            fair_value=fair_value,
                            market_price=Decimal(str(price / 100)),
                            edge=Decimal(str(edge)),
                            confidence=confidence,
                            quantity=qty,
                            expected_profit=expected,
                            strike=strike
                        ))
                        
            # Check for maker opportunities
            if self.maker_enabled:
                side, edge, price = self._calculate_edge(
                    fair_value, yes_bid, yes_ask, TradeMode.MAKER
                )
                if side and edge >= self.min_edge_maker:
                    qty = self._calculate_position_size(edge, fair_value, price)
                    if qty > 0:
                        underlying, market_type, strike, _ = self._parse_ticker(ticker)
                        
                        # Calculate expected profit (maker fee is lower)
                        fee = calculate_maker_fee(qty, price).total_fee_cents
                        expected = Decimal(str(edge * qty / 100)) - Decimal(str(fee / 100))
                        
                        opportunities.append(TradingOpportunity(
                            ticker=ticker,
                            underlying=underlying,
                            market_type=market_type,
                            side=side,
                            mode=TradeMode.MAKER,
                            fair_value=fair_value,
                            market_price=Decimal(str(price / 100)),
                            edge=Decimal(str(edge)),
                            confidence=confidence,
                            quantity=qty,
                            expected_profit=expected,
                            strike=strike
                        ))
                        
        # Sort by expected profit
        opportunities.sort(key=lambda x: x.expected_profit, reverse=True)
        
        return opportunities
        
    def execute_paper_trade(self, opp: TradingOpportunity) -> Optional[PaperOrder]:
        """Execute a paper trade."""
        # Check risk limits
        if self.kill_switch_active:
            return None
            
        # Check daily loss limit
        if self.daily_pnl < -float(self.initial_capital) * float(self.max_daily_loss):
            self.kill_switch_active = True
            self.kill_switch_reason = "Daily loss limit exceeded"
            logger.error(f"KILL SWITCH: {self.kill_switch_reason}")
            return None
            
        # Calculate cost
        price_cents = int(opp.market_price * 100)
        cost = Decimal(str(price_cents * opp.quantity / 100))
        
        # Calculate fees
        if opp.mode == TradeMode.TAKER:
            fee_cents = calculate_taker_fee(opp.quantity, price_cents).total_fee_cents
        else:
            fee_cents = calculate_maker_fee(opp.quantity, price_cents).total_fee_cents
            
        fee = Decimal(str(fee_cents / 100))
        total_cost = cost + fee
        
        if total_cost > self.cash:
            logger.warning(f"Insufficient cash: need {total_cost}, have {self.cash}")
            return None
            
        # Create order
        self.trade_count += 1
        order = PaperOrder(
            order_id=f"paper_{self.trade_count:06d}",
            ticker=opp.ticker,
            side=opp.side,
            mode=opp.mode,
            price=price_cents,
            quantity=opp.quantity,
            filled_qty=opp.quantity,  # Assume immediate fill for paper
            status="filled",
            filled_at=datetime.now(timezone.utc),
            fees_paid=int(fee_cents)
        )
        
        # Update cash
        self.cash -= total_cost
        
        # Update position
        if opp.ticker in self.positions:
            pos = self.positions[opp.ticker]
            if pos.side == opp.side:
                # Add to position
                total_qty = pos.quantity + opp.quantity
                pos.avg_entry_price = (
                    pos.avg_entry_price * pos.quantity + opp.market_price * opp.quantity
                ) / total_qty
                pos.quantity = total_qty
            else:
                # Reduce position
                if opp.quantity >= pos.quantity:
                    del self.positions[opp.ticker]
                else:
                    pos.quantity -= opp.quantity
        else:
            self.positions[opp.ticker] = PaperPosition(
                ticker=opp.ticker,
                side=opp.side,
                quantity=opp.quantity,
                avg_entry_price=opp.market_price
            )
            
        # Save to database
        self._save_trade(order)
        self.order_history.append(order)
        
        logger.info(
            f"PAPER TRADE: {opp.mode.value.upper()} {opp.side.value.upper()} "
            f"{opp.quantity}x {opp.ticker} @ {price_cents}c "
            f"(edge: {opp.edge}c, fee: {fee_cents}c)"
        )
        
        return order
        
    def _save_trade(self, order: PaperOrder):
        """Save trade to database."""
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO trades (order_id, ticker, side, mode, price, quantity, fees, pnl, created_at, filled_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            order.order_id,
            order.ticker,
            str(order.side.value),
            str(order.mode.value),
            order.price,
            order.quantity,
            order.fees_paid,
            0,  # PnL calculated on settlement
            order.created_at.isoformat(),
            order.filled_at.isoformat() if order.filled_at else None
        ))
        self.conn.commit()
        
    def save_snapshot(self):
        """Save portfolio snapshot."""
        positions_value = sum(
            float(p.avg_entry_price) * p.quantity 
            for p in self.positions.values()
        )
        total_value = float(self.cash) + positions_value
        
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO portfolio_snapshots (timestamp, cash, positions_value, total_value, daily_pnl, total_pnl)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            datetime.now(timezone.utc).isoformat(),
            float(self.cash),
            positions_value,
            total_value,
            float(self.daily_pnl),
            float(self.total_pnl)
        ))
        self.conn.commit()
        
    def get_status(self) -> dict:
        """Get current status."""
        positions_value = sum(
            float(p.avg_entry_price) * p.quantity 
            for p in self.positions.values()
        )
        total_value = float(self.cash) + positions_value
        
        return {
            "cash": float(self.cash),
            "positions_value": positions_value,
            "total_value": total_value,
            "positions_count": len(self.positions),
            "total_trades": self.trade_count,
            "win_rate": self.win_count / self.trade_count * 100 if self.trade_count > 0 else 0,
            "daily_pnl": float(self.daily_pnl),
            "total_pnl": float(self.total_pnl),
            "return_pct": (total_value / float(self.initial_capital) - 1) * 100,
            "maker_enabled": self.maker_enabled,
            "taker_enabled": self.taker_enabled,
            "kill_switch": self.kill_switch_active
        }
        
    async def close(self):
        """Clean up resources."""
        await self.crypto_agg.close()
        self.conn.close()


async def test_engine():
    """Test the integrated engine."""
    print("=" * 60)
    print("INTEGRATED PAPER TRADING ENGINE TEST")
    print("=" * 60)
    
    engine = IntegratedPaperEngine(
        initial_capital=Decimal("1000"),
        maker_enabled=True,
        taker_enabled=True
    )
    
    # Test crypto price fetch
    print("\nFetching crypto prices...")
    prices = await engine.get_crypto_prices()
    for symbol, price in prices.items():
        print(f"  {symbol}: ${float(price.fair_value):,.2f} ({price.num_sources} sources)")
        
    # Test fair value calculation
    print("\nCalculating fair values...")
    test_tickers = [
        "KXBTC15M-26JAN170530-30",
        "KXBTC-26JAN1717-B95250",
        "KXETH-26JAN1717-B3280"
    ]
    
    for ticker in test_tickers:
        result = await engine.calculate_fair_value(ticker, prices)
        if result:
            fv, conf = result
            print(f"  {ticker}: {float(fv):.2%} fair value ({conf:.0%} confidence)")
        else:
            print(f"  {ticker}: Unable to price")
            
    # Test opportunity scanning with mock markets
    print("\nScanning for opportunities...")
    mock_markets = [
        {"ticker": "KXBTC15M-26JAN170530-30", "yes_bid": 0.45, "yes_ask": 0.48},
        {"ticker": "KXBTC-26JAN1717-B95250", "yes_bid": 0.40, "yes_ask": 0.43},
        {"ticker": "KXETH-26JAN1717-B3280", "yes_bid": 0.52, "yes_ask": 0.55}
    ]
    
    opps = await engine.scan_for_opportunities(mock_markets)
    print(f"  Found {len(opps)} opportunities")
    
    for opp in opps[:3]:
        print(f"    {opp.mode.value.upper()} {opp.side.value.upper()} {opp.ticker}")
        print(f"      Edge: {opp.edge}c, Qty: {opp.quantity}, Expected: ${float(opp.expected_profit):.2f}")
        
    # Get status
    print("\nEngine status:")
    status = engine.get_status()
    for k, v in status.items():
        print(f"  {k}: {v}")
        
    await engine.close()
    print("\n" + "=" * 60)
    print("TEST COMPLETE")


if __name__ == "__main__":
    asyncio.run(test_engine())
