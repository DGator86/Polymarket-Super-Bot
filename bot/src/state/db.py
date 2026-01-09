"""
Database initialization and schema.
"""
import sqlite3
from pathlib import Path
from src.logging_setup import get_logger

logger = get_logger("db")


class Database:
    """SQLite database manager."""

    def __init__(self, db_path: str):
        """
        Initialize database.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.connection: sqlite3.Connection = None
        logger.info(f"Database initialized at {db_path}")

    def connect(self) -> None:
        """Connect to database and run migrations."""
        self.connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        logger.info("Database connected")
        self._run_migrations()

    def close(self) -> None:
        """Close database connection."""
        if self.connection:
            self.connection.close()
            logger.info("Database closed")

    def _run_migrations(self) -> None:
        """Run database migrations to create tables."""
        cursor = self.connection.cursor()

        # Orders table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                token_id TEXT NOT NULL,
                side TEXT NOT NULL,
                price REAL NOT NULL,
                size REAL NOT NULL,
                filled_size REAL DEFAULT 0.0,
                status TEXT NOT NULL,
                reason TEXT,
                created_ts INTEGER NOT NULL,
                updated_ts INTEGER NOT NULL
            )
        """)

        # Fills table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fills (
                fill_id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                token_id TEXT NOT NULL,
                side TEXT NOT NULL,
                price REAL NOT NULL,
                size REAL NOT NULL,
                fee REAL NOT NULL,
                ts INTEGER NOT NULL,
                FOREIGN KEY (order_id) REFERENCES orders (order_id)
            )
        """)

        # Positions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                token_id TEXT PRIMARY KEY,
                qty REAL NOT NULL,
                avg_cost REAL NOT NULL,
                realized_pnl REAL DEFAULT 0.0,
                updated_ts INTEGER NOT NULL
            )
        """)

        # Decisions table (intent logs)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_id TEXT NOT NULL,
                side TEXT NOT NULL,
                price REAL NOT NULL,
                size REAL NOT NULL,
                mode TEXT NOT NULL,
                reason TEXT,
                accepted INTEGER NOT NULL,
                rejection_reason TEXT,
                ts INTEGER NOT NULL
            )
        """)

        # Snapshots table (optional, for analytics)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                total_notional REAL,
                num_positions INTEGER,
                num_open_orders INTEGER,
                daily_pnl REAL,
                ts INTEGER NOT NULL
            )
        """)

        # Create indices
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_token ON orders(token_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_fills_order ON fills(order_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_fills_ts ON fills(ts)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_decisions_ts ON decisions(ts)")

        self.connection.commit()
        logger.info("Database migrations completed")

    def execute(self, query: str, params: tuple = ()) -> sqlite3.Cursor:
        """
        Execute a query.

        Args:
            query: SQL query
            params: Query parameters

        Returns:
            Cursor
        """
        cursor = self.connection.cursor()
        cursor.execute(query, params)
        return cursor

    def commit(self) -> None:
        """Commit transaction."""
        self.connection.commit()

    def rollback(self) -> None:
        """Rollback transaction."""
        self.connection.rollback()
