"""
PnL tracking and position management.
"""
from typing import Dict, Optional
from src.models import Fill, Position, Side
from src.state.repositories import PositionRepository, FillRepository
from src.logging_setup import get_logger

logger = get_logger("pnl")


class PnLTracker:
    """
    Track PnL and update positions based on fills.

    Uses average cost basis method for position tracking.
    """

    def __init__(
        self,
        position_repo: PositionRepository,
        fill_repo: FillRepository
    ):
        self.position_repo = position_repo
        self.fill_repo = fill_repo
        self._positions_cache: Dict[str, Position] = {}
        self._load_positions()

    def _load_positions(self) -> None:
        """Load positions from repository into cache."""
        self._positions_cache = self.position_repo.get_all_positions()
        logger.info(f"Loaded {len(self._positions_cache)} positions from database")

    def get_position(self, token_id: str) -> Position:
        """
        Get current position for a token.

        Args:
            token_id: Token ID

        Returns:
            Position (creates empty position if none exists)
        """
        if token_id not in self._positions_cache:
            self._positions_cache[token_id] = Position(
                token_id=token_id,
                qty=0.0,
                avg_cost=0.0,
                realized_pnl=0.0
            )
        return self._positions_cache[token_id]

    def get_all_positions(self) -> Dict[str, Position]:
        """Get all positions."""
        return self._positions_cache.copy()

    def process_fill(self, fill: Fill) -> float:
        """
        Process a fill and update position.

        Args:
            fill: Fill to process

        Returns:
            Realized PnL from this fill
        """
        position = self.get_position(fill.token_id)

        # Calculate realized PnL
        realized_pnl = 0.0

        if fill.side == Side.BUY:
            # Buying
            if position.qty < 0:
                # Closing short position (or part of it)
                close_qty = min(-position.qty, fill.size)
                realized_pnl = close_qty * (position.avg_cost - fill.price)
                logger.info(
                    f"Closing {close_qty} short @ {fill.price:.4f} "
                    f"(avg_cost={position.avg_cost:.4f}) -> PnL={realized_pnl:.2f}"
                )

            # Update position
            new_qty = position.qty + fill.size
            if new_qty > 0:
                # Long or increasing long
                if position.qty <= 0:
                    # Opening new long or flipping from short
                    position.avg_cost = fill.price
                else:
                    # Increasing existing long - update average cost
                    total_cost = (position.qty * position.avg_cost) + (fill.size * fill.price)
                    position.avg_cost = total_cost / new_qty

            position.qty = new_qty

        else:
            # Selling
            if position.qty > 0:
                # Closing long position (or part of it)
                close_qty = min(position.qty, fill.size)
                realized_pnl = close_qty * (fill.price - position.avg_cost)
                logger.info(
                    f"Closing {close_qty} long @ {fill.price:.4f} "
                    f"(avg_cost={position.avg_cost:.4f}) -> PnL={realized_pnl:.2f}"
                )

            # Update position
            new_qty = position.qty - fill.size
            if new_qty < 0:
                # Short or increasing short
                if position.qty >= 0:
                    # Opening new short or flipping from long
                    position.avg_cost = fill.price
                else:
                    # Increasing existing short - update average cost
                    total_cost = (-position.qty * position.avg_cost) + (fill.size * fill.price)
                    position.avg_cost = total_cost / (-new_qty)

            position.qty = new_qty

        # Subtract fees from realized PnL
        realized_pnl -= fill.fee

        # Update realized PnL
        position.realized_pnl += realized_pnl

        # Save position
        self.position_repo.save_position(position)

        logger.info(
            f"Processed fill: {fill.side} {fill.size} {fill.token_id} @ {fill.price:.4f}, "
            f"new_qty={position.qty:.1f}, avg_cost={position.avg_cost:.4f}, "
            f"realized_pnl={realized_pnl:.2f}"
        )

        return realized_pnl

    def calculate_unrealized_pnl(self, current_mids: Dict[str, float]) -> float:
        """
        Calculate total unrealized PnL across all positions.

        Args:
            current_mids: Current mid prices by token_id

        Returns:
            Total unrealized PnL
        """
        total_unrealized = 0.0

        for token_id, position in self._positions_cache.items():
            if position.qty == 0:
                continue

            mid = current_mids.get(token_id, position.avg_cost)
            unrealized = position.unrealized_pnl(mid)
            total_unrealized += unrealized

        return total_unrealized

    def calculate_total_pnl(self, current_mids: Dict[str, float]) -> Dict[str, float]:
        """
        Calculate total PnL (realized + unrealized).

        Args:
            current_mids: Current mid prices by token_id

        Returns:
            Dict with 'realized', 'unrealized', and 'total' PnL
        """
        total_realized = sum(p.realized_pnl for p in self._positions_cache.values())
        total_unrealized = self.calculate_unrealized_pnl(current_mids)

        return {
            "realized": total_realized,
            "unrealized": total_unrealized,
            "total": total_realized + total_unrealized
        }
