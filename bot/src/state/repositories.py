"""
Data repositories for CRUD operations.
"""
from typing import List, Optional, Dict
from datetime import datetime
from src.models import OpenOrder, Fill, Position, Intent, Side
from src.state.db import Database
from src.logging_setup import get_logger

logger = get_logger("repositories")


class OrderRepository:
    """Repository for order data."""

    def __init__(self, db: Database):
        self.db = db

    def save_order(self, order: OpenOrder, reason: str = "") -> None:
        """Save an order."""
        now_ms = int(datetime.now().timestamp() * 1000)
        self.db.execute(
            """
            INSERT OR REPLACE INTO orders
            (order_id, token_id, side, price, size, filled_size, status, reason, created_ts, updated_ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order.order_id,
                order.token_id,
                order.side.value,
                order.price,
                order.size,
                order.filled_size,
                "OPEN",
                reason,
                order.ts,
                now_ms
            )
        )
        self.db.commit()

    def update_order_status(self, order_id: str, status: str, filled_size: float = 0.0) -> None:
        """Update order status."""
        now_ms = int(datetime.now().timestamp() * 1000)
        self.db.execute(
            "UPDATE orders SET status = ?, filled_size = ?, updated_ts = ? WHERE order_id = ?",
            (status, filled_size, now_ms, order_id)
        )
        self.db.commit()

    def get_open_orders(self, token_id: Optional[str] = None) -> List[OpenOrder]:
        """Get open orders."""
        if token_id:
            cursor = self.db.execute(
                "SELECT * FROM orders WHERE status = 'OPEN' AND token_id = ?",
                (token_id,)
            )
        else:
            cursor = self.db.execute("SELECT * FROM orders WHERE status = 'OPEN'")

        orders = []
        for row in cursor.fetchall():
            order = OpenOrder(
                order_id=row["order_id"],
                token_id=row["token_id"],
                side=Side(row["side"]),
                price=row["price"],
                size=row["size"],
                filled_size=row["filled_size"],
                ts=row["created_ts"]
            )
            orders.append(order)

        return orders

    def get_order(self, order_id: str) -> Optional[OpenOrder]:
        """Get order by ID."""
        cursor = self.db.execute(
            "SELECT * FROM orders WHERE order_id = ?",
            (order_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None

        return OpenOrder(
            order_id=row["order_id"],
            token_id=row["token_id"],
            side=Side(row["side"]),
            price=row["price"],
            size=row["size"],
            filled_size=row["filled_size"],
            ts=row["created_ts"]
        )


class FillRepository:
    """Repository for fill data."""

    def __init__(self, db: Database):
        self.db = db

    def save_fill(self, fill: Fill) -> None:
        """Save a fill."""
        self.db.execute(
            """
            INSERT INTO fills
            (fill_id, order_id, token_id, side, price, size, fee, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fill.fill_id,
                fill.order_id,
                fill.token_id,
                fill.side.value,
                fill.price,
                fill.size,
                fill.fee,
                fill.ts
            )
        )
        self.db.commit()

    def get_fills(
        self,
        token_id: Optional[str] = None,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None
    ) -> List[Fill]:
        """Get fills with optional filters."""
        query = "SELECT * FROM fills WHERE 1=1"
        params = []

        if token_id:
            query += " AND token_id = ?"
            params.append(token_id)

        if start_ts:
            query += " AND ts >= ?"
            params.append(start_ts)

        if end_ts:
            query += " AND ts <= ?"
            params.append(end_ts)

        query += " ORDER BY ts DESC"

        cursor = self.db.execute(query, tuple(params))

        fills = []
        for row in cursor.fetchall():
            fill = Fill(
                fill_id=row["fill_id"],
                order_id=row["order_id"],
                token_id=row["token_id"],
                side=Side(row["side"]),
                price=row["price"],
                size=row["size"],
                fee=row["fee"],
                ts=row["ts"]
            )
            fills.append(fill)

        return fills


class PositionRepository:
    """Repository for position data."""

    def __init__(self, db: Database):
        self.db = db

    def save_position(self, position: Position) -> None:
        """Save a position."""
        now_ms = int(datetime.now().timestamp() * 1000)
        self.db.execute(
            """
            INSERT OR REPLACE INTO positions
            (token_id, qty, avg_cost, realized_pnl, updated_ts)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                position.token_id,
                position.qty,
                position.avg_cost,
                position.realized_pnl,
                now_ms
            )
        )
        self.db.commit()

    def get_position(self, token_id: str) -> Optional[Position]:
        """Get position for a token."""
        cursor = self.db.execute(
            "SELECT * FROM positions WHERE token_id = ?",
            (token_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None

        return Position(
            token_id=row["token_id"],
            qty=row["qty"],
            avg_cost=row["avg_cost"],
            realized_pnl=row["realized_pnl"]
        )

    def get_all_positions(self) -> Dict[str, Position]:
        """Get all positions."""
        cursor = self.db.execute("SELECT * FROM positions WHERE qty != 0")

        positions = {}
        for row in cursor.fetchall():
            position = Position(
                token_id=row["token_id"],
                qty=row["qty"],
                avg_cost=row["avg_cost"],
                realized_pnl=row["realized_pnl"]
            )
            positions[position.token_id] = position

        return positions


class DecisionRepository:
    """Repository for decision/intent logs."""

    def __init__(self, db: Database):
        self.db = db

    def log_decision(
        self,
        intent: Intent,
        accepted: bool,
        rejection_reason: Optional[str] = None
    ) -> None:
        """Log a trading decision."""
        now_ms = int(datetime.now().timestamp() * 1000)
        self.db.execute(
            """
            INSERT INTO decisions
            (token_id, side, price, size, mode, reason, accepted, rejection_reason, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                intent.token_id,
                intent.side.value,
                intent.price,
                intent.size,
                intent.mode.value,
                intent.reason,
                1 if accepted else 0,
                rejection_reason,
                now_ms
            )
        )
        self.db.commit()
