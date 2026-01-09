"""
Market maker strategy - provide liquidity around fair price with inventory skew.
"""
from typing import List, Dict
from src.models import Market, Position, Intent, Side, IntentMode
from src.strategy.fair_price import clamp_to_tick, calculate_inventory_skew
from src.logging_setup import get_logger

logger = get_logger("market_maker")


class MarketMakerStrategy:
    """
    Market making strategy.

    Maintains bid/ask quotes around fair price to capture spread and rebates.
    Adjusts quotes based on inventory to avoid getting stuck on one side.
    """

    def __init__(
        self,
        half_spread: float = 0.01,
        default_size: float = 10.0,
        quote_ttl_ms: int = 3000,
        inventory_skew_factor: float = 0.0001,
        max_inventory: float = 500.0
    ):
        """
        Initialize market maker strategy.

        Args:
            half_spread: Half spread around fair price (e.g., 0.01 = 1 cent)
            default_size: Default quote size
            quote_ttl_ms: Quote time-to-live in milliseconds
            inventory_skew_factor: Inventory skew sensitivity
            max_inventory: Maximum inventory for skew calculation
        """
        self.half_spread = half_spread
        self.default_size = default_size
        self.quote_ttl_ms = quote_ttl_ms
        self.inventory_skew_factor = inventory_skew_factor
        self.max_inventory = max_inventory
        logger.info(
            f"Initialized market maker strategy (half_spread={half_spread}, "
            f"quote_ttl_ms={quote_ttl_ms}, inventory_skew_factor={inventory_skew_factor})"
        )

    def generate_intents(
        self,
        market: Market,
        p_fair: float,
        positions: Dict[str, Position]
    ) -> List[Intent]:
        """
        Generate maker intents (bid and ask quotes).

        Args:
            market: Market definition
            p_fair: Fair YES probability
            positions: Current positions by token_id

        Returns:
            List of maker intents (typically 2: bid and ask)
        """
        intents = []

        # Get current position for YES token
        position = positions.get(market.yes_token_id, Position(
            token_id=market.yes_token_id,
            qty=0.0,
            avg_cost=0.0
        ))

        # Calculate inventory skew
        inventory_skew = calculate_inventory_skew(
            position_qty=position.qty,
            max_inventory=self.max_inventory,
            skew_factor=self.inventory_skew_factor
        )

        # Adjust center price with inventory skew
        p_center = p_fair + inventory_skew

        # Calculate bid and ask prices
        bid_price = p_center - self.half_spread
        ask_price = p_center + self.half_spread

        # Clamp to tick size and valid range
        bid_price = clamp_to_tick(bid_price, market.tick_size)
        ask_price = clamp_to_tick(ask_price, market.tick_size)

        logger.debug(
            f"Market maker for {market.slug}: p_fair={p_fair:.4f}, "
            f"inventory={position.qty:.1f}, skew={inventory_skew:.6f}, "
            f"p_center={p_center:.4f}, bid={bid_price:.4f}, ask={ask_price:.4f}"
        )

        # Create bid intent (buy YES)
        bid_intent = Intent(
            token_id=market.yes_token_id,
            side=Side.BUY,
            price=bid_price,
            size=self.default_size,
            mode=IntentMode.MAKER,
            ttl_ms=self.quote_ttl_ms,
            reason=f"mm_bid_pfair={p_fair:.4f}_skew={inventory_skew:.6f}"
        )
        intents.append(bid_intent)

        # Create ask intent (sell YES)
        ask_intent = Intent(
            token_id=market.yes_token_id,
            side=Side.SELL,
            price=ask_price,
            size=self.default_size,
            mode=IntentMode.MAKER,
            ttl_ms=self.quote_ttl_ms,
            reason=f"mm_ask_pfair={p_fair:.4f}_skew={inventory_skew:.6f}"
        )
        intents.append(ask_intent)

        logger.debug(
            f"Generated maker intents: BID {self.default_size} @ {bid_price:.4f}, "
            f"ASK {self.default_size} @ {ask_price:.4f}"
        )

        return intents
