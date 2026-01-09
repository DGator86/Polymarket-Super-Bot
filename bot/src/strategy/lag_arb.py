"""
Lag arbitrage strategy - take aggressive orders when edge exceeds threshold.
"""
from typing import Optional, List
from src.models import Market, BookTop, Intent, Side, IntentMode
from src.logging_setup import get_logger

logger = get_logger("lag_arb")


class LagArbStrategy:
    """
    Lag arbitrage strategy.

    Takes aggressive orders (removes liquidity) when the fair price
    significantly differs from market price.
    """

    def __init__(
        self,
        edge_threshold: float = 0.03,
        max_slippage: float = 0.02,
        default_size: float = 10.0,
        taker_fee: float = 0.0  # Polymarket has 0% taker fees
    ):
        """
        Initialize lag arb strategy.

        Args:
            edge_threshold: Minimum edge to trigger taker order (e.g., 0.03 = 3 cents)
            max_slippage: Maximum allowed slippage (e.g., 0.02 = 2 cents)
            default_size: Default order size
            taker_fee: Taker fee rate (0.0 for Polymarket)
        """
        self.edge_threshold = edge_threshold
        self.max_slippage = max_slippage
        self.default_size = default_size
        self.taker_fee = taker_fee
        logger.info(
            f"Initialized lag arb strategy (edge_threshold={edge_threshold}, "
            f"max_slippage={max_slippage})"
        )

    def generate_intents(
        self,
        market: Market,
        book: BookTop,
        p_fair: float
    ) -> List[Intent]:
        """
        Generate taker intents if edge is sufficient.

        Args:
            market: Market definition
            book: Current orderbook top
            p_fair: Fair YES probability

        Returns:
            List of taker intents (0 or 1 element)
        """
        intents = []

        # Calculate market-implied probability from mid
        p_market = book.mid
        if p_market is None:
            logger.debug(f"No mid price for {market.slug}, skipping")
            return intents

        # Calculate edge
        edge = p_fair - p_market

        logger.debug(
            f"Lag arb check for {market.slug}: p_fair={p_fair:.4f}, "
            f"p_market={p_market:.4f}, edge={edge:.4f}"
        )

        # Check if edge exceeds threshold
        if abs(edge) < self.edge_threshold:
            return intents

        # Determine direction
        if edge > 0:
            # Fair price > market price → buy YES (or sell NO)
            # Buy YES at ask
            side = Side.BUY
            price = book.ask_px
            available_size = book.ask_sz
            token_id = market.yes_token_id
            reason = f"lag_arb_buy_yes_edge={edge:.4f}"

        else:
            # Fair price < market price → sell YES (or buy NO)
            # Sell YES at bid
            side = Side.SELL
            price = book.bid_px
            available_size = book.bid_sz
            token_id = market.yes_token_id
            reason = f"lag_arb_sell_yes_edge={edge:.4f}"

        # Validate price exists
        if price is None or available_size is None:
            logger.debug(f"No price available for {side} on {market.slug}")
            return intents

        # Check spread sanity
        spread = book.spread
        if spread is None or spread > self.max_slippage:
            logger.warning(
                f"Spread too wide for {market.slug}: {spread}, "
                f"max_slippage={self.max_slippage}"
            )
            return intents

        # Calculate after-fee edge
        fee_cost = self.taker_fee * price
        if side == Side.BUY:
            effective_price = price + fee_cost
            net_edge = p_fair - effective_price
        else:
            effective_price = price - fee_cost
            net_edge = effective_price - p_fair

        # Ensure positive after-fee edge
        if net_edge <= 0:
            logger.debug(
                f"After-fee edge not positive for {market.slug}: "
                f"net_edge={net_edge:.4f}"
            )
            return intents

        # Determine size (limited by available liquidity)
        size = min(self.default_size, available_size)
        size = max(size, market.min_size)

        # Create taker intent
        intent = Intent(
            token_id=token_id,
            side=side,
            price=price,
            size=size,
            mode=IntentMode.TAKER,
            ttl_us=1_000_000,  # Taker orders are short-lived (1 second in microseconds)
            reason=reason
        )

        intents.append(intent)
        logger.info(
            f"Generated taker intent: {side} {size} {token_id} @ {price:.4f} "
            f"(edge={edge:.4f}, net_edge={net_edge:.4f})"
        )

        return intents
