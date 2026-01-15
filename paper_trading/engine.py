"""
Paper Trading Engine

Simulates trading against live Kalshi market data without real capital.
Tracks virtual positions, P&L, and trade history for strategy validation.

Features:
- Virtual portfolio with configurable starting capital
- Realistic fill simulation (slippage, partial fills)
- Position tracking through settlement
- Comprehensive trade history and analytics
- Integration with ML feedback loop
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional, List, Dict, Any, Callable, Awaitable
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
import sqlite3

from core.models import (
    Side, OrderType, OrderStatus, MarketCategory, Venue,
    NormalizedMarket, TradingSignal, Position
)

logger = logging.getLogger(__name__)


class TradeOutcome(Enum):
    """Final outcome of a settled trade"""
    WIN = "win"
    LOSS = "loss"
    PUSH = "push"  # Rare: exactly at threshold
    PENDING = "pending"


@dataclass
class PaperPosition:
    """A virtual position in a market"""
    position_id: str
    ticker: str
    side: Side
    quantity: int
    entry_price: Decimal
    entry_time: datetime
    market_question: str
    category: MarketCategory
    expiry: datetime
    
    # Updated as market moves
    current_price: Decimal = Decimal("0.50")
    last_update: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Set at settlement
    exit_price: Optional[Decimal] = None
    exit_time: Optional[datetime] = None
    outcome: TradeOutcome = TradeOutcome.PENDING
    settled: bool = False
    settlement_value: Optional[Decimal] = None  # 0 or 1
    
    # Signal metadata for ML
    signal_edge: Decimal = Decimal("0")
    signal_confidence: Decimal = Decimal("0")
    model_probability: Decimal = Decimal("0")
    
    @property
    def unrealized_pnl(self) -> Decimal:
        """Current unrealized P&L"""
        if self.settled:
            return Decimal("0")
        
        if self.side == Side.YES:
            return (self.current_price - self.entry_price) * self.quantity
        else:
            # For NO positions: profit when price drops
            return (self.entry_price - self.current_price) * self.quantity
    
    @property
    def realized_pnl(self) -> Decimal:
        """Realized P&L (only set after settlement)"""
        if not self.settled or self.settlement_value is None:
            return Decimal("0")
        
        if self.side == Side.YES:
            return (self.settlement_value - self.entry_price) * self.quantity
        else:
            return ((Decimal("1") - self.settlement_value) - (Decimal("1") - self.entry_price)) * self.quantity
    
    @property
    def cost_basis(self) -> Decimal:
        """Total cost to enter position"""
        if self.side == Side.YES:
            return self.entry_price * self.quantity
        else:
            return (Decimal("1") - self.entry_price) * self.quantity
    
    @property
    def market_value(self) -> Decimal:
        """Current market value of position"""
        if self.side == Side.YES:
            return self.current_price * self.quantity
        else:
            return (Decimal("1") - self.current_price) * self.quantity
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for storage"""
        return {
            "position_id": self.position_id,
            "ticker": self.ticker,
            "side": self.side.value,
            "quantity": self.quantity,
            "entry_price": str(self.entry_price),
            "entry_time": self.entry_time.isoformat(),
            "market_question": self.market_question,
            "category": self.category.value,
            "expiry": self.expiry.isoformat(),
            "current_price": str(self.current_price),
            "exit_price": str(self.exit_price) if self.exit_price else None,
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            "outcome": self.outcome.value,
            "settled": self.settled,
            "settlement_value": str(self.settlement_value) if self.settlement_value else None,
            "signal_edge": str(self.signal_edge),
            "signal_confidence": str(self.signal_confidence),
            "model_probability": str(self.model_probability),
            "realized_pnl": str(self.realized_pnl),
            "unrealized_pnl": str(self.unrealized_pnl),
        }


@dataclass
class PaperTrade:
    """Record of a completed trade"""
    trade_id: str
    position_id: str
    ticker: str
    side: Side
    quantity: int
    entry_price: Decimal
    entry_time: datetime
    exit_price: Decimal
    exit_time: datetime
    pnl: Decimal
    pnl_pct: Decimal
    outcome: TradeOutcome
    
    # ML features
    signal_edge: Decimal
    signal_confidence: Decimal
    model_probability: Decimal
    market_probability: Decimal
    category: MarketCategory
    time_held_hours: float
    
    def to_dict(self) -> Dict:
        return {
            "trade_id": self.trade_id,
            "position_id": self.position_id,
            "ticker": self.ticker,
            "side": self.side.value,
            "quantity": self.quantity,
            "entry_price": str(self.entry_price),
            "entry_time": self.entry_time.isoformat(),
            "exit_price": str(self.exit_price),
            "exit_time": self.exit_time.isoformat(),
            "pnl": str(self.pnl),
            "pnl_pct": str(self.pnl_pct),
            "outcome": self.outcome.value,
            "signal_edge": str(self.signal_edge),
            "signal_confidence": str(self.signal_confidence),
            "model_probability": str(self.model_probability),
            "market_probability": str(self.market_probability),
            "category": self.category.value,
            "time_held_hours": self.time_held_hours,
        }


@dataclass
class PortfolioSnapshot:
    """Point-in-time portfolio state"""
    timestamp: datetime
    cash: Decimal
    positions_value: Decimal
    total_equity: Decimal
    num_positions: int
    unrealized_pnl: Decimal
    realized_pnl_today: Decimal
    trades_today: int
    win_rate: float
    
    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "cash": str(self.cash),
            "positions_value": str(self.positions_value),
            "total_equity": str(self.total_equity),
            "num_positions": self.num_positions,
            "unrealized_pnl": str(self.unrealized_pnl),
            "realized_pnl_today": str(self.realized_pnl_today),
            "trades_today": self.trades_today,
            "win_rate": self.win_rate,
        }


class PaperTradingEngine:
    """
    Paper trading simulation engine.
    
    Manages virtual portfolio, simulates fills, tracks positions through
    settlement, and records everything for ML training.
    
    Usage:
        engine = PaperTradingEngine(starting_capital=1000)
        await engine.initialize(kalshi_client)
        
        # Enter position
        position = await engine.enter_position(signal, market, size=10)
        
        # Update prices
        await engine.update_prices()
        
        # Check for settlements
        await engine.process_settlements()
        
        # Get analytics
        stats = engine.get_performance_stats()
    """
    
    def __init__(
        self,
        starting_capital: Decimal = Decimal("1000"),
        data_dir: str = "./paper_trading_data",
        slippage_pct: Decimal = Decimal("0.005"),  # 0.5% slippage simulation
        fee_pct: Decimal = Decimal("0.01"),         # 1% fee assumption
    ):
        self.starting_capital = starting_capital
        self.data_dir = Path(data_dir)
        self.slippage_pct = slippage_pct
        self.fee_pct = fee_pct
        
        # Portfolio state
        self.cash = starting_capital
        self.positions: Dict[str, PaperPosition] = {}  # position_id -> position
        self.trades: List[PaperTrade] = []
        self.snapshots: List[PortfolioSnapshot] = []
        
        # Daily tracking
        self._daily_realized_pnl = Decimal("0")
        self._daily_trades = 0
        self._last_reset_date: Optional[datetime] = None
        
        # Kalshi client reference
        self._kalshi = None
        
        # Database for persistence
        self._db_path = self.data_dir / "paper_trades.db"
        self._db: Optional[sqlite3.Connection] = None
        
        # Callbacks for ML integration
        self._on_trade_complete: Optional[Callable[[PaperTrade], Awaitable[None]]] = None
    
    async def initialize(self, kalshi_client=None):
        """Initialize engine with Kalshi client and database"""
        self._kalshi = kalshi_client
        
        # Create data directory
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize database
        self._init_database()
        
        # Load existing state if any
        self._load_state()
        
        logger.info(f"Paper trading engine initialized with ${self.starting_capital} capital")
        logger.info(f"Data directory: {self.data_dir}")
    
    def _init_database(self):
        """Initialize SQLite database for trade history"""
        self._db = sqlite3.connect(str(self._db_path))
        
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS positions (
                position_id TEXT PRIMARY KEY,
                ticker TEXT,
                side TEXT,
                quantity INTEGER,
                entry_price TEXT,
                entry_time TEXT,
                market_question TEXT,
                category TEXT,
                expiry TEXT,
                current_price TEXT,
                exit_price TEXT,
                exit_time TEXT,
                outcome TEXT,
                settled INTEGER,
                settlement_value TEXT,
                signal_edge TEXT,
                signal_confidence TEXT,
                model_probability TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE TABLE IF NOT EXISTS trades (
                trade_id TEXT PRIMARY KEY,
                position_id TEXT,
                ticker TEXT,
                side TEXT,
                quantity INTEGER,
                entry_price TEXT,
                entry_time TEXT,
                exit_price TEXT,
                exit_time TEXT,
                pnl TEXT,
                pnl_pct TEXT,
                outcome TEXT,
                signal_edge TEXT,
                signal_confidence TEXT,
                model_probability TEXT,
                market_probability TEXT,
                category TEXT,
                time_held_hours REAL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                cash TEXT,
                positions_value TEXT,
                total_equity TEXT,
                num_positions INTEGER,
                unrealized_pnl TEXT,
                realized_pnl_today TEXT,
                trades_today INTEGER,
                win_rate REAL
            );
            
            CREATE INDEX IF NOT EXISTS idx_positions_ticker ON positions(ticker);
            CREATE INDEX IF NOT EXISTS idx_positions_settled ON positions(settled);
            CREATE INDEX IF NOT EXISTS idx_trades_outcome ON trades(outcome);
            CREATE INDEX IF NOT EXISTS idx_trades_category ON trades(category);
        """)
        
        self._db.commit()
    
    def _load_state(self):
        """Load existing positions and state from database"""
        if not self._db:
            return
        
        # Load open positions
        cursor = self._db.execute(
            "SELECT * FROM positions WHERE settled = 0"
        )
        
        for row in cursor.fetchall():
            pos = self._row_to_position(row)
            self.positions[pos.position_id] = pos
        
        # Calculate current cash from trades
        cursor = self._db.execute("SELECT SUM(CAST(pnl AS REAL)) FROM trades")
        total_pnl = cursor.fetchone()[0] or 0
        
        # Cash = starting - cost basis of open positions + realized P&L
        open_cost = sum(p.cost_basis for p in self.positions.values())
        self.cash = self.starting_capital - open_cost + Decimal(str(total_pnl))
        
        logger.info(f"Loaded {len(self.positions)} open positions, cash: ${self.cash:.2f}")
    
    def _row_to_position(self, row) -> PaperPosition:
        """Convert database row to PaperPosition"""
        return PaperPosition(
            position_id=row[0],
            ticker=row[1],
            side=Side(row[2]),
            quantity=row[3],
            entry_price=Decimal(row[4]),
            entry_time=datetime.fromisoformat(row[5]),
            market_question=row[6],
            category=MarketCategory(row[7]),
            expiry=datetime.fromisoformat(row[8]),
            current_price=Decimal(row[9]) if row[9] else Decimal("0.5"),
            exit_price=Decimal(row[10]) if row[10] else None,
            exit_time=datetime.fromisoformat(row[11]) if row[11] else None,
            outcome=TradeOutcome(row[12]) if row[12] else TradeOutcome.PENDING,
            settled=bool(row[13]),
            settlement_value=Decimal(row[14]) if row[14] else None,
            signal_edge=Decimal(row[15]) if row[15] else Decimal("0"),
            signal_confidence=Decimal(row[16]) if row[16] else Decimal("0"),
            model_probability=Decimal(row[17]) if row[17] else Decimal("0"),
        )
    
    async def enter_position(
        self,
        signal: TradingSignal,
        market: NormalizedMarket,
        size: int,
        use_slippage: bool = True
    ) -> Optional[PaperPosition]:
        """
        Enter a new paper position.
        
        Args:
            signal: Trading signal with edge/confidence info
            market: Current market data
            size: Number of contracts
            use_slippage: Simulate slippage on entry
        
        Returns:
            PaperPosition if successful, None if insufficient funds
        """
        # Calculate entry price with slippage
        if signal.side == Side.YES:
            base_price = market.best_ask
            if use_slippage:
                entry_price = base_price * (Decimal("1") + self.slippage_pct)
        else:
            base_price = Decimal("1") - market.best_bid
            if use_slippage:
                entry_price = base_price * (Decimal("1") + self.slippage_pct)
        
        entry_price = min(Decimal("0.99"), max(Decimal("0.01"), entry_price))
        
        # Calculate cost
        cost = entry_price * size
        
        # Check funds
        if cost > self.cash:
            logger.warning(f"Insufficient funds: need ${cost:.2f}, have ${self.cash:.2f}")
            return None
        
        # Create position
        position = PaperPosition(
            position_id=str(uuid.uuid4()),
            ticker=market.ticker,
            side=signal.side,
            quantity=size,
            entry_price=entry_price,
            entry_time=datetime.now(timezone.utc),
            market_question=market.question,
            category=market.category,
            expiry=market.expiry,
            current_price=market.implied_prob_mid,
            signal_edge=signal.edge,
            signal_confidence=signal.confidence,
            model_probability=signal.model_probability,
        )
        
        # Deduct cash
        self.cash -= cost
        
        # Store position
        self.positions[position.position_id] = position
        self._save_position(position)
        
        logger.info(
            f"PAPER ENTRY: {position.ticker} {position.side.value.upper()} "
            f"x{position.quantity} @ {position.entry_price:.2%} "
            f"(cost: ${cost:.2f})"
        )
        
        return position
    
    async def update_prices(self):
        """Update current prices for all open positions"""
        if not self._kalshi:
            logger.warning("No Kalshi client - cannot update prices")
            return
        
        for position in self.positions.values():
            if position.settled:
                continue
            
            try:
                orderbook = await self._kalshi.get_orderbook(position.ticker, depth=1)
                
                yes_bids = orderbook.get("orderbook", {}).get("yes", {}).get("bids", [])
                yes_asks = orderbook.get("orderbook", {}).get("yes", {}).get("asks", [])
                
                if yes_bids and yes_asks:
                    bid = Decimal(str(yes_bids[0][0])) / 100
                    ask = Decimal(str(yes_asks[0][0])) / 100
                    position.current_price = (bid + ask) / 2
                    position.last_update = datetime.now(timezone.utc)
                    
            except Exception as e:
                logger.debug(f"Failed to update price for {position.ticker}: {e}")
    
    async def process_settlements(self):
        """Check for and process settled markets"""
        if not self._kalshi:
            return
        
        settled_positions = []
        
        for position in self.positions.values():
            if position.settled:
                continue
            
            # Check if market has settled
            try:
                market_data = await self._kalshi.get_market(position.ticker)
                status = market_data.get("status", "")
                
                if status == "settled":
                    result = market_data.get("result", "")
                    
                    if result == "yes":
                        position.settlement_value = Decimal("1")
                    elif result == "no":
                        position.settlement_value = Decimal("0")
                    else:
                        continue  # Unknown result
                    
                    position.settled = True
                    position.exit_time = datetime.now(timezone.utc)
                    position.exit_price = position.settlement_value
                    
                    # Determine outcome
                    if position.side == Side.YES:
                        position.outcome = TradeOutcome.WIN if position.settlement_value == Decimal("1") else TradeOutcome.LOSS
                    else:
                        position.outcome = TradeOutcome.WIN if position.settlement_value == Decimal("0") else TradeOutcome.LOSS
                    
                    settled_positions.append(position)
                    
            except Exception as e:
                logger.debug(f"Failed to check settlement for {position.ticker}: {e}")
        
        # Process settled positions
        for position in settled_positions:
            await self._finalize_position(position)
    
    async def _finalize_position(self, position: PaperPosition):
        """Finalize a settled position and record trade"""
        pnl = position.realized_pnl
        
        # Return settlement value to cash
        if position.side == Side.YES:
            self.cash += position.settlement_value * position.quantity
        else:
            self.cash += (Decimal("1") - position.settlement_value) * position.quantity
        
        # Calculate P&L percentage
        cost_basis = position.cost_basis
        pnl_pct = pnl / cost_basis if cost_basis > 0 else Decimal("0")
        
        # Calculate time held
        time_held = (position.exit_time - position.entry_time).total_seconds() / 3600
        
        # Create trade record
        trade = PaperTrade(
            trade_id=str(uuid.uuid4()),
            position_id=position.position_id,
            ticker=position.ticker,
            side=position.side,
            quantity=position.quantity,
            entry_price=position.entry_price,
            entry_time=position.entry_time,
            exit_price=position.exit_price,
            exit_time=position.exit_time,
            pnl=pnl,
            pnl_pct=pnl_pct,
            outcome=position.outcome,
            signal_edge=position.signal_edge,
            signal_confidence=position.signal_confidence,
            model_probability=position.model_probability,
            market_probability=position.entry_price,
            category=position.category,
            time_held_hours=time_held,
        )
        
        self.trades.append(trade)
        self._daily_realized_pnl += pnl
        self._daily_trades += 1
        
        # Save to database
        self._save_trade(trade)
        self._update_position(position)
        
        logger.info(
            f"PAPER SETTLED: {position.ticker} {position.outcome.value.upper()} "
            f"P&L: ${pnl:.2f} ({pnl_pct:.1%})"
        )
        
        # Trigger ML callback
        if self._on_trade_complete:
            await self._on_trade_complete(trade)
    
    def _save_position(self, position: PaperPosition):
        """Save position to database"""
        if not self._db:
            return
        
        self._db.execute("""
            INSERT OR REPLACE INTO positions 
            (position_id, ticker, side, quantity, entry_price, entry_time,
             market_question, category, expiry, current_price, exit_price,
             exit_time, outcome, settled, settlement_value, signal_edge,
             signal_confidence, model_probability)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            position.position_id, position.ticker, position.side.value,
            position.quantity, str(position.entry_price), position.entry_time.isoformat(),
            position.market_question, position.category.value, position.expiry.isoformat(),
            str(position.current_price), 
            str(position.exit_price) if position.exit_price else None,
            position.exit_time.isoformat() if position.exit_time else None,
            position.outcome.value, int(position.settled),
            str(position.settlement_value) if position.settlement_value else None,
            str(position.signal_edge), str(position.signal_confidence),
            str(position.model_probability)
        ))
        self._db.commit()
    
    def _update_position(self, position: PaperPosition):
        """Update existing position in database"""
        self._save_position(position)  # Same as save with OR REPLACE
    
    def _save_trade(self, trade: PaperTrade):
        """Save completed trade to database"""
        if not self._db:
            return
        
        self._db.execute("""
            INSERT INTO trades 
            (trade_id, position_id, ticker, side, quantity, entry_price,
             entry_time, exit_price, exit_time, pnl, pnl_pct, outcome,
             signal_edge, signal_confidence, model_probability,
             market_probability, category, time_held_hours)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            trade.trade_id, trade.position_id, trade.ticker, trade.side.value,
            trade.quantity, str(trade.entry_price), trade.entry_time.isoformat(),
            str(trade.exit_price), trade.exit_time.isoformat(),
            str(trade.pnl), str(trade.pnl_pct), trade.outcome.value,
            str(trade.signal_edge), str(trade.signal_confidence),
            str(trade.model_probability), str(trade.market_probability),
            trade.category.value, trade.time_held_hours
        ))
        self._db.commit()
    
    def take_snapshot(self) -> PortfolioSnapshot:
        """Take a snapshot of current portfolio state"""
        positions_value = sum(p.market_value for p in self.positions.values() if not p.settled)
        unrealized_pnl = sum(p.unrealized_pnl for p in self.positions.values() if not p.settled)
        
        wins = sum(1 for t in self.trades if t.outcome == TradeOutcome.WIN)
        total = len(self.trades)
        win_rate = wins / total if total > 0 else 0.0
        
        snapshot = PortfolioSnapshot(
            timestamp=datetime.now(timezone.utc),
            cash=self.cash,
            positions_value=positions_value,
            total_equity=self.cash + positions_value,
            num_positions=len([p for p in self.positions.values() if not p.settled]),
            unrealized_pnl=unrealized_pnl,
            realized_pnl_today=self._daily_realized_pnl,
            trades_today=self._daily_trades,
            win_rate=win_rate,
        )
        
        self.snapshots.append(snapshot)
        
        # Save to database
        if self._db:
            self._db.execute("""
                INSERT INTO snapshots 
                (timestamp, cash, positions_value, total_equity, num_positions,
                 unrealized_pnl, realized_pnl_today, trades_today, win_rate)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                snapshot.timestamp.isoformat(), str(snapshot.cash),
                str(snapshot.positions_value), str(snapshot.total_equity),
                snapshot.num_positions, str(snapshot.unrealized_pnl),
                str(snapshot.realized_pnl_today), snapshot.trades_today,
                snapshot.win_rate
            ))
            self._db.commit()
        
        return snapshot
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """Get comprehensive performance statistics"""
        if not self.trades:
            return {
                "total_trades": 0,
                "total_pnl": 0,
                "win_rate": 0,
                "message": "No completed trades yet"
            }
        
        wins = [t for t in self.trades if t.outcome == TradeOutcome.WIN]
        losses = [t for t in self.trades if t.outcome == TradeOutcome.LOSS]
        
        total_pnl = sum(t.pnl for t in self.trades)
        avg_win = sum(t.pnl for t in wins) / len(wins) if wins else Decimal("0")
        avg_loss = sum(t.pnl for t in losses) / len(losses) if losses else Decimal("0")
        
        # Calculate by category
        by_category = {}
        for cat in MarketCategory:
            cat_trades = [t for t in self.trades if t.category == cat]
            if cat_trades:
                cat_wins = sum(1 for t in cat_trades if t.outcome == TradeOutcome.WIN)
                by_category[cat.value] = {
                    "trades": len(cat_trades),
                    "win_rate": cat_wins / len(cat_trades),
                    "pnl": float(sum(t.pnl for t in cat_trades)),
                }
        
        # Edge calibration
        edge_buckets = {"0-5%": [], "5-10%": [], "10-20%": [], "20%+": []}
        for t in self.trades:
            edge = float(t.signal_edge) * 100
            if edge < 5:
                edge_buckets["0-5%"].append(t)
            elif edge < 10:
                edge_buckets["5-10%"].append(t)
            elif edge < 20:
                edge_buckets["10-20%"].append(t)
            else:
                edge_buckets["20%+"].append(t)
        
        edge_performance = {}
        for bucket, trades in edge_buckets.items():
            if trades:
                wins = sum(1 for t in trades if t.outcome == TradeOutcome.WIN)
                edge_performance[bucket] = {
                    "trades": len(trades),
                    "win_rate": wins / len(trades),
                    "avg_pnl": float(sum(t.pnl for t in trades)) / len(trades),
                }
        
        return {
            "total_trades": len(self.trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(self.trades),
            "total_pnl": float(total_pnl),
            "avg_win": float(avg_win),
            "avg_loss": float(avg_loss),
            "profit_factor": float(abs(avg_win / avg_loss)) if avg_loss != 0 else float("inf"),
            "current_equity": float(self.cash + sum(p.market_value for p in self.positions.values() if not p.settled)),
            "return_pct": float((self.cash + sum(p.market_value for p in self.positions.values() if not p.settled) - self.starting_capital) / self.starting_capital),
            "by_category": by_category,
            "by_edge_bucket": edge_performance,
            "open_positions": len([p for p in self.positions.values() if not p.settled]),
        }
    
    def get_ml_training_data(self) -> List[Dict]:
        """
        Export trade data in format suitable for ML training.
        
        Returns list of feature dictionaries with outcome labels.
        """
        training_data = []
        
        for trade in self.trades:
            features = {
                # Input features
                "signal_edge": float(trade.signal_edge),
                "signal_confidence": float(trade.signal_confidence),
                "model_probability": float(trade.model_probability),
                "market_probability": float(trade.market_probability),
                "entry_price": float(trade.entry_price),
                "time_held_hours": trade.time_held_hours,
                "category": trade.category.value,
                "side": trade.side.value,
                "quantity": trade.quantity,
                
                # Labels
                "outcome": 1 if trade.outcome == TradeOutcome.WIN else 0,
                "pnl": float(trade.pnl),
                "pnl_pct": float(trade.pnl_pct),
            }
            training_data.append(features)
        
        return training_data
    
    def set_trade_callback(self, callback: Callable[[PaperTrade], Awaitable[None]]):
        """Set callback for ML integration on trade completion"""
        self._on_trade_complete = callback
    
    def reset(self):
        """Reset paper trading state (keeps history)"""
        self.cash = self.starting_capital
        self.positions.clear()
        self._daily_realized_pnl = Decimal("0")
        self._daily_trades = 0
        logger.info(f"Paper trading reset to ${self.starting_capital}")
    
    def close(self):
        """Close database connection"""
        if self._db:
            self._db.close()
