"""
Order manager - reconciles intents with open orders.
"""
from typing import List, Dict, Optional
from datetime import datetime
from src.models import Intent, OpenOrder, Side, IntentMode
from src.execution.clob_client import CLOBClient
from src.logging_setup import get_logger

logger = get_logger("order_manager")


class OrderManager:
    """
    Order manager.

    Responsibilities:
    - Reconcile desired intents with open orders
    - Place new orders when needed
    - Cancel orders that don't match current intents
    - Replace orders that have drifted from desired price
    - Enforce TTL on maker orders
    - Dedupe to avoid duplicate orders
    """

    def __init__(
        self,
        clob_client: CLOBClient,
        tick_size: float = 0.01,
        min_price_diff_for_replace: float = 0.01
    ):
        """
        Initialize order manager.

        Args:
            clob_client: CLOB client for order operations
            tick_size: Minimum price increment
            min_price_diff_for_replace: Min price diff to trigger replace
        """
        self.clob_client = clob_client
        self.tick_size = tick_size
        self.min_price_diff_for_replace = min_price_diff_for_replace
        logger.info("Order manager initialized")

    def reconcile(
        self,
        intents: List[Intent],
        open_orders: List[OpenOrder]
    ) -> Dict[str, str]:
        """
        Reconcile intents with open orders.

        Args:
            intents: Desired trading intents
            open_orders: Current open orders

        Returns:
            Dict mapping intent to order_id for newly placed orders
        """
        placed_orders = {}

        # Build lookup of open orders by (token_id, side)
        open_by_token_side = {}
        for order in open_orders:
            key = (order.token_id, order.side)
            if key not in open_by_token_side:
                open_by_token_side[key] = []
            open_by_token_side[key].append(order)

        # Process each intent
        for intent in intents:
            key = (intent.token_id, intent.side)
            matching_orders = open_by_token_side.get(key, [])

            # Handle taker intents (always place immediately)
            if intent.mode == IntentMode.TAKER:
                order_id = self._place_taker_order(intent)
                if order_id:
                    placed_orders[f"{intent.token_id}_{intent.side.value}"] = order_id
                continue

            # Handle maker intents
            # Check if we have a matching maker order
            matched = False
            for order in matching_orders:
                if self._is_order_matching(order, intent):
                    matched = True
                    logger.debug(
                        f"Order {order.order_id} matches intent for {intent.token_id} "
                        f"{intent.side}, keeping it"
                    )
                    # Remove from list so it's not cancelled
                    matching_orders.remove(order)
                    break

            # If no matching order, check if we should place a new one
            if not matched:
                # Cancel any non-matching orders first
                for order in matching_orders:
                    self._cancel_order(order)
                    matching_orders.remove(order)

                # Place new order
                order_id = self._place_maker_order(intent)
                if order_id:
                    placed_orders[f"{intent.token_id}_{intent.side.value}"] = order_id

        # Cancel any remaining open orders that don't match intents
        intent_keys = set((i.token_id, i.side) for i in intents)
        for (token_id, side), orders in open_by_token_side.items():
            if (token_id, side) not in intent_keys:
                for order in orders:
                    self._cancel_order(order)

        return placed_orders

    def _is_order_matching(self, order: OpenOrder, intent: Intent) -> bool:
        """
        Check if an order matches an intent.

        Args:
            order: Existing open order
            intent: Desired intent

        Returns:
            True if order matches intent closely enough
        """
        # Check price proximity
        price_diff = abs(order.price - intent.price)
        if price_diff > self.min_price_diff_for_replace:
            logger.debug(
                f"Order price {order.price:.4f} differs from intent {intent.price:.4f} "
                f"by {price_diff:.4f} (threshold={self.min_price_diff_for_replace})"
            )
            return False

        # Check size proximity (within 10%)
        size_diff_pct = abs(order.remaining_size - intent.size) / intent.size
        if size_diff_pct > 0.1:
            logger.debug(
                f"Order size {order.remaining_size:.1f} differs from intent {intent.size:.1f} "
                f"by {size_diff_pct:.1%}"
            )
            return False

        # Check TTL (for maker orders)
        if intent.mode == IntentMode.MAKER:
            if order.age_ms > intent.ttl_ms:
                logger.debug(
                    f"Order age {order.age_ms}ms exceeds TTL {intent.ttl_ms}ms"
                )
                return False

        return True

    def _place_maker_order(self, intent: Intent) -> Optional[str]:
        """
        Place a maker order.

        Args:
            intent: Maker intent

        Returns:
            Order ID if successful
        """
        logger.info(
            f"Placing maker order: {intent.side} {intent.size} {intent.token_id} "
            f"@ {intent.price:.4f} (reason={intent.reason})"
        )

        order_id = self.clob_client.place_order(intent, post_only=True)
        return order_id

    def _place_taker_order(self, intent: Intent) -> Optional[str]:
        """
        Place a taker order.

        Args:
            intent: Taker intent

        Returns:
            Order ID if successful
        """
        logger.info(
            f"Placing taker order: {intent.side} {intent.size} {intent.token_id} "
            f"@ {intent.price:.4f} (reason={intent.reason})"
        )

        order_id = self.clob_client.place_order(intent, post_only=False)
        return order_id

    def _cancel_order(self, order: OpenOrder) -> bool:
        """
        Cancel an order.

        Args:
            order: Order to cancel

        Returns:
            True if successful
        """
        logger.info(
            f"Cancelling order: {order.order_id} ({order.side} {order.remaining_size} "
            f"{order.token_id} @ {order.price:.4f})"
        )

        return self.clob_client.cancel_order(order.order_id)

    def cancel_all_orders(self) -> int:
        """
        Cancel all open orders (emergency function).

        Returns:
            Number of orders cancelled
        """
        logger.warning("Cancelling ALL open orders")
        return self.clob_client.cancel_all_orders()
