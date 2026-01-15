"""
Historical Database for Trade Storage and Analytics

SQLite-based storage for:
- Trade history
- Signal logs
- P&L tracking
- Performance analytics

Provides:
- Async database operations
- Automatic schema migrations
- Query helpers for analytics
- Export functionality
"""

import asyncio
import aiosqlite
import logging
import json
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, asdict
from pathlib import Path
from enum import Enum

from config import config
from core.models import TradingSignal, OrderResponse, Position, Side, OrderStatus, SignalType

logger = logging.getLogger(__name__)


# =============================================================================
# DATABASE MODELS
# =============================================================================

@dataclass
class TradeRecord:
    """Stored trade record"""
    id: Optional[int]
    signal_id: str
    order_id: str
    ticker: str
    side: str
    signal_type: str
    
    # Prices
    model_probability: float
    market_probability: float
    edge: float
    entry_price: float
    exit_price: Optional[float]
    
    # Quantities
    requested_quantity: int
    filled_quantity: int
    
    # P&L
    realized_pnl: Optional[float]
    fees: float
    
    # Timestamps
    signal_time: datetime
    entry_time: datetime
    exit_time: Optional[datetime]
    
    # Status
    status: str  # "open", "closed", "cancelled"
    
    # Metadata
    metadata: Dict[str, Any]
    
    def to_dict(self) -> Dict:
        d = asdict(self)
        d['signal_time'] = self.signal_time.isoformat()
        d['entry_time'] = self.entry_time.isoformat()
        d['exit_time'] = self.exit_time.isoformat() if self.exit_time else None
        return d


@dataclass
class SignalRecord:
    """Stored signal record (including non-traded)"""
    id: Optional[int]
    signal_id: str
    ticker: str
    side: str
    signal_type: str
    model_probability: float
    market_probability: float
    edge: float
    confidence: float
    reason: str
    timestamp: datetime
    was_traded: bool
    rejection_reason: Optional[str]
    metadata: Dict[str, Any]


@dataclass
class DailyStats:
    """Daily performance statistics"""
    date: datetime
    starting_equity: float
    ending_equity: float
    realized_pnl: float
    unrealized_pnl: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_edge: float
    max_drawdown: float
    sharpe_estimate: float


# =============================================================================
# DATABASE MANAGER
# =============================================================================

class DatabaseManager:
    """
    Async SQLite database manager for trade history.
    
    Usage:
        db = DatabaseManager("trades.db")
        await db.connect()
        await db.insert_trade(trade_record)
        stats = await db.get_daily_stats(date)
    """
    
    SCHEMA_VERSION = 1
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or config.database.path
        self.connection: Optional[aiosqlite.Connection] = None
    
    async def connect(self):
        """Connect to database and initialize schema"""
        # Ensure directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        
        self.connection = await aiosqlite.connect(self.db_path)
        self.connection.row_factory = aiosqlite.Row
        
        # Enable foreign keys
        await self.connection.execute("PRAGMA foreign_keys = ON")
        
        # Initialize schema
        await self._init_schema()
        
        logger.info(f"Database connected: {self.db_path}")
    
    async def close(self):
        """Close database connection"""
        if self.connection:
            await self.connection.close()
            logger.info("Database connection closed")
    
    async def _init_schema(self):
        """Initialize database schema"""
        await self.connection.executescript("""
            -- Trades table
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id TEXT NOT NULL,
                order_id TEXT NOT NULL UNIQUE,
                ticker TEXT NOT NULL,
                side TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                
                model_probability REAL NOT NULL,
                market_probability REAL NOT NULL,
                edge REAL NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL,
                
                requested_quantity INTEGER NOT NULL,
                filled_quantity INTEGER NOT NULL,
                
                realized_pnl REAL,
                fees REAL DEFAULT 0,
                
                signal_time TEXT NOT NULL,
                entry_time TEXT NOT NULL,
                exit_time TEXT,
                
                status TEXT NOT NULL DEFAULT 'open',
                metadata TEXT,
                
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            
            -- Signals table (all signals, traded or not)
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id TEXT NOT NULL UNIQUE,
                ticker TEXT NOT NULL,
                side TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                
                model_probability REAL NOT NULL,
                market_probability REAL NOT NULL,
                edge REAL NOT NULL,
                confidence REAL NOT NULL,
                reason TEXT,
                
                timestamp TEXT NOT NULL,
                was_traded INTEGER DEFAULT 0,
                rejection_reason TEXT,
                metadata TEXT,
                
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            
            -- Daily stats table
            CREATE TABLE IF NOT EXISTS daily_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL UNIQUE,
                starting_equity REAL NOT NULL,
                ending_equity REAL NOT NULL,
                realized_pnl REAL NOT NULL,
                unrealized_pnl REAL DEFAULT 0,
                total_trades INTEGER DEFAULT 0,
                winning_trades INTEGER DEFAULT 0,
                losing_trades INTEGER DEFAULT 0,
                avg_edge REAL DEFAULT 0,
                max_drawdown REAL DEFAULT 0,
                sharpe_estimate REAL DEFAULT 0,
                
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            
            -- Price history for backtesting
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                price REAL NOT NULL,
                bid REAL,
                ask REAL,
                volume REAL,
                source TEXT,
                
                UNIQUE(symbol, timestamp)
            );
            
            -- Indexes
            CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker);
            CREATE INDEX IF NOT EXISTS idx_trades_entry_time ON trades(entry_time);
            CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
            CREATE INDEX IF NOT EXISTS idx_signals_ticker ON signals(ticker);
            CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON signals(timestamp);
            CREATE INDEX IF NOT EXISTS idx_price_history_symbol ON price_history(symbol);
            CREATE INDEX IF NOT EXISTS idx_price_history_timestamp ON price_history(timestamp);
            
            -- Schema version
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY
            );
        """)
        
        # Check/update schema version
        async with self.connection.execute("SELECT version FROM schema_version") as cursor:
            row = await cursor.fetchone()
            if not row:
                await self.connection.execute(
                    "INSERT INTO schema_version (version) VALUES (?)",
                    (self.SCHEMA_VERSION,)
                )
        
        await self.connection.commit()
    
    # =========================================================================
    # TRADE OPERATIONS
    # =========================================================================
    
    async def insert_trade(self, trade: TradeRecord) -> int:
        """Insert new trade record"""
        cursor = await self.connection.execute("""
            INSERT INTO trades (
                signal_id, order_id, ticker, side, signal_type,
                model_probability, market_probability, edge, entry_price, exit_price,
                requested_quantity, filled_quantity, realized_pnl, fees,
                signal_time, entry_time, exit_time, status, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            trade.signal_id, trade.order_id, trade.ticker, trade.side, trade.signal_type,
            trade.model_probability, trade.market_probability, trade.edge,
            trade.entry_price, trade.exit_price,
            trade.requested_quantity, trade.filled_quantity,
            trade.realized_pnl, trade.fees,
            trade.signal_time.isoformat(), trade.entry_time.isoformat(),
            trade.exit_time.isoformat() if trade.exit_time else None,
            trade.status, json.dumps(trade.metadata)
        ))
        await self.connection.commit()
        return cursor.lastrowid
    
    async def update_trade(self, order_id: str, updates: Dict[str, Any]):
        """Update existing trade"""
        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        values = list(updates.values()) + [order_id]
        
        await self.connection.execute(
            f"UPDATE trades SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE order_id = ?",
            values
        )
        await self.connection.commit()
    
    async def close_trade(
        self,
        order_id: str,
        exit_price: float,
        realized_pnl: float,
        exit_time: datetime = None
    ):
        """Mark trade as closed with P&L"""
        await self.update_trade(order_id, {
            "exit_price": exit_price,
            "realized_pnl": realized_pnl,
            "exit_time": (exit_time or datetime.now(timezone.utc)).isoformat(),
            "status": "closed"
        })
    
    async def get_trade(self, order_id: str) -> Optional[TradeRecord]:
        """Get trade by order ID"""
        async with self.connection.execute(
            "SELECT * FROM trades WHERE order_id = ?", (order_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return self._row_to_trade(row)
        return None
    
    async def get_open_trades(self) -> List[TradeRecord]:
        """Get all open trades"""
        async with self.connection.execute(
            "SELECT * FROM trades WHERE status = 'open' ORDER BY entry_time DESC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_trade(row) for row in rows]
    
    async def get_trades_by_ticker(self, ticker: str, limit: int = 100) -> List[TradeRecord]:
        """Get trades for a specific ticker"""
        async with self.connection.execute(
            "SELECT * FROM trades WHERE ticker = ? ORDER BY entry_time DESC LIMIT ?",
            (ticker, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_trade(row) for row in rows]
    
    async def get_trades_by_date_range(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> List[TradeRecord]:
        """Get trades within date range"""
        async with self.connection.execute(
            """SELECT * FROM trades 
               WHERE entry_time >= ? AND entry_time <= ?
               ORDER BY entry_time DESC""",
            (start_date.isoformat(), end_date.isoformat())
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_trade(row) for row in rows]
    
    def _row_to_trade(self, row) -> TradeRecord:
        """Convert database row to TradeRecord"""
        return TradeRecord(
            id=row['id'],
            signal_id=row['signal_id'],
            order_id=row['order_id'],
            ticker=row['ticker'],
            side=row['side'],
            signal_type=row['signal_type'],
            model_probability=row['model_probability'],
            market_probability=row['market_probability'],
            edge=row['edge'],
            entry_price=row['entry_price'],
            exit_price=row['exit_price'],
            requested_quantity=row['requested_quantity'],
            filled_quantity=row['filled_quantity'],
            realized_pnl=row['realized_pnl'],
            fees=row['fees'],
            signal_time=datetime.fromisoformat(row['signal_time']),
            entry_time=datetime.fromisoformat(row['entry_time']),
            exit_time=datetime.fromisoformat(row['exit_time']) if row['exit_time'] else None,
            status=row['status'],
            metadata=json.loads(row['metadata']) if row['metadata'] else {}
        )
    
    # =========================================================================
    # SIGNAL OPERATIONS
    # =========================================================================
    
    async def insert_signal(self, signal: TradingSignal, was_traded: bool = False, rejection_reason: str = None):
        """Insert signal record"""
        await self.connection.execute("""
            INSERT OR REPLACE INTO signals (
                signal_id, ticker, side, signal_type,
                model_probability, market_probability, edge, confidence, reason,
                timestamp, was_traded, rejection_reason, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            signal.signal_id, signal.ticker, signal.side.value, signal.signal_type.value,
            float(signal.model_probability), float(signal.market_probability),
            float(signal.edge), float(signal.confidence), signal.reason,
            signal.created_at.isoformat(), int(was_traded), rejection_reason,
            json.dumps(signal.metadata)
        ))
        await self.connection.commit()
    
    async def get_signals_by_date(self, date: datetime) -> List[Dict]:
        """Get all signals for a date"""
        start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        
        async with self.connection.execute(
            """SELECT * FROM signals 
               WHERE timestamp >= ? AND timestamp < ?
               ORDER BY timestamp DESC""",
            (start.isoformat(), end.isoformat())
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    # =========================================================================
    # ANALYTICS
    # =========================================================================
    
    async def calculate_daily_stats(self, date: datetime) -> DailyStats:
        """Calculate statistics for a specific day"""
        start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        
        # Get trades for the day
        trades = await self.get_trades_by_date_range(start, end)
        
        if not trades:
            return DailyStats(
                date=start,
                starting_equity=0, ending_equity=0,
                realized_pnl=0, unrealized_pnl=0,
                total_trades=0, winning_trades=0, losing_trades=0,
                avg_edge=0, max_drawdown=0, sharpe_estimate=0
            )
        
        closed_trades = [t for t in trades if t.status == 'closed']
        
        total_pnl = sum(t.realized_pnl or 0 for t in closed_trades)
        winning = len([t for t in closed_trades if (t.realized_pnl or 0) > 0])
        losing = len([t for t in closed_trades if (t.realized_pnl or 0) < 0])
        avg_edge = sum(t.edge for t in trades) / len(trades) if trades else 0
        
        # Calculate Sharpe estimate (simplified)
        returns = [t.realized_pnl or 0 for t in closed_trades if t.realized_pnl is not None]
        if len(returns) > 1:
            import statistics
            mean_return = statistics.mean(returns)
            std_return = statistics.stdev(returns)
            sharpe = (mean_return / std_return * (252 ** 0.5)) if std_return > 0 else 0
        else:
            sharpe = 0
        
        return DailyStats(
            date=start,
            starting_equity=0,  # Would need account balance tracking
            ending_equity=0,
            realized_pnl=total_pnl,
            unrealized_pnl=0,
            total_trades=len(trades),
            winning_trades=winning,
            losing_trades=losing,
            avg_edge=avg_edge,
            max_drawdown=0,  # Would need equity curve
            sharpe_estimate=sharpe
        )
    
    async def save_daily_stats(self, stats: DailyStats):
        """Save daily statistics"""
        await self.connection.execute("""
            INSERT OR REPLACE INTO daily_stats (
                date, starting_equity, ending_equity, realized_pnl, unrealized_pnl,
                total_trades, winning_trades, losing_trades, avg_edge, max_drawdown, sharpe_estimate
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            stats.date.strftime("%Y-%m-%d"),
            stats.starting_equity, stats.ending_equity,
            stats.realized_pnl, stats.unrealized_pnl,
            stats.total_trades, stats.winning_trades, stats.losing_trades,
            stats.avg_edge, stats.max_drawdown, stats.sharpe_estimate
        ))
        await self.connection.commit()
    
    async def get_performance_summary(self, days: int = 30) -> Dict[str, Any]:
        """Get performance summary for recent period"""
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)
        
        trades = await self.get_trades_by_date_range(start_date, end_date)
        closed_trades = [t for t in trades if t.status == 'closed']
        
        if not closed_trades:
            return {
                "period_days": days,
                "total_trades": 0,
                "message": "No closed trades in period"
            }
        
        total_pnl = sum(t.realized_pnl or 0 for t in closed_trades)
        winning = [t for t in closed_trades if (t.realized_pnl or 0) > 0]
        losing = [t for t in closed_trades if (t.realized_pnl or 0) < 0]
        
        avg_win = sum(t.realized_pnl for t in winning) / len(winning) if winning else 0
        avg_loss = sum(t.realized_pnl for t in losing) / len(losing) if losing else 0
        
        # By ticker
        ticker_pnl = {}
        for t in closed_trades:
            if t.ticker not in ticker_pnl:
                ticker_pnl[t.ticker] = 0
            ticker_pnl[t.ticker] += t.realized_pnl or 0
        
        # By signal type
        type_pnl = {}
        for t in closed_trades:
            if t.signal_type not in type_pnl:
                type_pnl[t.signal_type] = 0
            type_pnl[t.signal_type] += t.realized_pnl or 0
        
        return {
            "period_days": days,
            "total_trades": len(closed_trades),
            "total_pnl": total_pnl,
            "winning_trades": len(winning),
            "losing_trades": len(losing),
            "win_rate": len(winning) / len(closed_trades) if closed_trades else 0,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": abs(sum(t.realized_pnl for t in winning) / sum(t.realized_pnl for t in losing)) if losing and sum(t.realized_pnl for t in losing) != 0 else 0,
            "avg_edge": sum(t.edge for t in closed_trades) / len(closed_trades),
            "pnl_by_ticker": ticker_pnl,
            "pnl_by_type": type_pnl,
            "best_trade": max(closed_trades, key=lambda t: t.realized_pnl or 0).to_dict(),
            "worst_trade": min(closed_trades, key=lambda t: t.realized_pnl or 0).to_dict()
        }
    
    # =========================================================================
    # PRICE HISTORY
    # =========================================================================
    
    async def insert_price(
        self,
        symbol: str,
        timestamp: datetime,
        price: float,
        bid: float = None,
        ask: float = None,
        volume: float = None,
        source: str = None
    ):
        """Insert price observation"""
        await self.connection.execute("""
            INSERT OR REPLACE INTO price_history (symbol, timestamp, price, bid, ask, volume, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (symbol, timestamp.isoformat(), price, bid, ask, volume, source))
        await self.connection.commit()
    
    async def insert_prices_batch(self, prices: List[Dict]):
        """Insert multiple price observations efficiently"""
        await self.connection.executemany("""
            INSERT OR REPLACE INTO price_history (symbol, timestamp, price, bid, ask, volume, source)
            VALUES (:symbol, :timestamp, :price, :bid, :ask, :volume, :source)
        """, prices)
        await self.connection.commit()
    
    async def get_price_history(
        self,
        symbol: str,
        start_time: datetime,
        end_time: datetime = None
    ) -> List[Dict]:
        """Get price history for a symbol"""
        end_time = end_time or datetime.now(timezone.utc)
        
        async with self.connection.execute(
            """SELECT * FROM price_history 
               WHERE symbol = ? AND timestamp >= ? AND timestamp <= ?
               ORDER BY timestamp ASC""",
            (symbol, start_time.isoformat(), end_time.isoformat())
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    # =========================================================================
    # EXPORT
    # =========================================================================
    
    async def export_trades_csv(self, filepath: str, start_date: datetime = None, end_date: datetime = None):
        """Export trades to CSV file"""
        import csv
        
        if start_date and end_date:
            trades = await self.get_trades_by_date_range(start_date, end_date)
        else:
            async with self.connection.execute("SELECT * FROM trades ORDER BY entry_time DESC") as cursor:
                rows = await cursor.fetchall()
                trades = [self._row_to_trade(row) for row in rows]
        
        with open(filepath, 'w', newline='') as f:
            if trades:
                writer = csv.DictWriter(f, fieldnames=trades[0].to_dict().keys())
                writer.writeheader()
                for trade in trades:
                    writer.writerow(trade.to_dict())
        
        logger.info(f"Exported {len(trades)} trades to {filepath}")
    
    async def export_performance_report(self, filepath: str, days: int = 30):
        """Export comprehensive performance report"""
        summary = await self.get_performance_summary(days)
        
        with open(filepath, 'w') as f:
            f.write("=" * 60 + "\n")
            f.write(f"PERFORMANCE REPORT - Last {days} Days\n")
            f.write("=" * 60 + "\n\n")
            
            f.write(f"Total Trades: {summary.get('total_trades', 0)}\n")
            f.write(f"Total P&L: ${summary.get('total_pnl', 0):.2f}\n")
            f.write(f"Win Rate: {summary.get('win_rate', 0):.1%}\n")
            f.write(f"Profit Factor: {summary.get('profit_factor', 0):.2f}\n")
            f.write(f"Average Edge: {summary.get('avg_edge', 0):.2%}\n\n")
            
            f.write("P&L by Ticker:\n")
            for ticker, pnl in summary.get('pnl_by_ticker', {}).items():
                f.write(f"  {ticker}: ${pnl:.2f}\n")
            
            f.write("\nP&L by Strategy:\n")
            for stype, pnl in summary.get('pnl_by_type', {}).items():
                f.write(f"  {stype}: ${pnl:.2f}\n")
        
        logger.info(f"Exported performance report to {filepath}")


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_db_instance: Optional[DatabaseManager] = None

async def get_database() -> DatabaseManager:
    """Get or create global database instance"""
    global _db_instance
    if _db_instance is None:
        _db_instance = DatabaseManager()
        await _db_instance.connect()
    return _db_instance


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

async def record_trade(signal: TradingSignal, order: OrderResponse):
    """Quick helper to record a trade"""
    db = await get_database()
    
    trade = TradeRecord(
        id=None,
        signal_id=signal.signal_id,
        order_id=order.order_id,
        ticker=signal.ticker,
        side=signal.side.value,
        signal_type=signal.signal_type.value,
        model_probability=float(signal.model_probability),
        market_probability=float(signal.market_probability),
        edge=float(signal.edge),
        entry_price=order.price or 0,
        exit_price=None,
        requested_quantity=order.requested_count,
        filled_quantity=order.filled_count,
        realized_pnl=None,
        fees=0,
        signal_time=signal.created_at,
        entry_time=order.created_at,
        exit_time=None,
        status="open" if order.status != OrderStatus.FILLED else "pending_settlement",
        metadata=signal.metadata
    )
    
    return await db.insert_trade(trade)


async def record_signal(signal: TradingSignal, was_traded: bool, rejection_reason: str = None):
    """Quick helper to record a signal"""
    db = await get_database()
    await db.insert_signal(signal, was_traded, rejection_reason)
