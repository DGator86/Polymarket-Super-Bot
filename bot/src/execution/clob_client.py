"""
Polymarket CLOB client wrapper.
"""
from typing import Optional, Dict
from src.models import Intent, Side
from src.execution.rate_limiter import RateLimiter
from src.logging_setup import get_logger

logger = get_logger("clob_client")


class CLOBClient:
    """
    Wrapper around Polymarket py-clob-client.

    Handles:
    - Order placement
    - Order cancellation
    - Order status queries
    - Dry-run mode
    """

    def __init__(
        self,
        private_key: str,
        chain_id: int = 137,
        clob_url: str = "https://clob.polymarket.com",
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        api_passphrase: Optional[str] = None,
        dry_run: bool = True
    ):
        """
        Initialize CLOB client.

        Args:
            private_key: Private key for signing
            chain_id: Chain ID (137 = Polygon mainnet)
            clob_url: CLOB API URL
            api_key: API key for authenticated endpoints
            api_secret: API secret
            api_passphrase: API passphrase
            dry_run: If True, log orders instead of placing them
        """
        self.dry_run = dry_run
        self.chain_id = chain_id
        self.clob_url = clob_url
        self._client = None
        self._rate_limiter = RateLimiter(max_requests=30, window_seconds=60)

        if not dry_run:
            try:
                from py_clob_client.client import ClobClient
                from py_clob_client.clob_types import OrderArgs, OrderType

                # Initialize client with private key
                self._client = ClobClient(
                    host=clob_url,
                    key=private_key,
                    chain_id=chain_id
                )

                # Set API credentials if provided
                if api_key and api_secret and api_passphrase:
                    self._client.set_api_creds(
                        api_key=api_key,
                        api_secret=api_secret,
                        api_passphrase=api_passphrase
                    )
                    logger.info("CLOB client initialized with API credentials")
                else:
                    logger.info("CLOB client initialized without API credentials")

            except ImportError:
                logger.error("py-clob-client not installed. Install with: pip install py-clob-client")
                raise
            except Exception as e:
                logger.error(f"Failed to initialize CLOB client: {e}", exc_info=True)
                raise
        else:
            logger.info("CLOB client initialized in DRY-RUN mode")

    def place_order(
        self,
        intent: Intent,
        post_only: bool = False
    ) -> Optional[str]:
        """
        Place an order.

        Args:
            intent: Trading intent
            post_only: If True, order will only be placed as maker

        Returns:
            Order ID if successful, None otherwise
        """
        # Rate limit check
        if not self._rate_limiter.acquire(blocking=False):
            logger.warning("Rate limit exceeded, cannot place order")
            return None

        if self.dry_run:
            order_id = f"DRY_{intent.token_id}_{int(intent.created_ts)}"
            logger.info(
                f"[DRY-RUN] Place order: {intent.side} {intent.size} {intent.token_id} "
                f"@ {intent.price:.4f} (mode={intent.mode}, post_only={post_only}) -> {order_id}"
            )
            return order_id

        try:
            from py_clob_client.clob_types import OrderArgs, OrderType

            # Determine order type
            if intent.mode.value == "MAKER" or post_only:
                order_type = OrderType.GTD  # Good-til-date (maker)
            else:
                order_type = OrderType.FOK  # Fill-or-kill (taker)

            # Build order args
            order_args = OrderArgs(
                token_id=intent.token_id,
                price=intent.price,
                size=intent.size,
                side=intent.side.value,
                order_type=order_type,
                expiration=intent.created_ts_ms + intent.ttl_ms  # Expiration timestamp
            )

            # Place order
            response = self._client.create_order(order_args)
            order_id = response.get("orderID")

            logger.info(
                f"Placed order: {intent.side} {intent.size} {intent.token_id} "
                f"@ {intent.price:.4f} -> {order_id}"
            )

            return order_id

        except Exception as e:
            logger.error(f"Failed to place order: {e}", exc_info=True)
            return None

    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an order.

        Args:
            order_id: Order ID to cancel

        Returns:
            True if successful
        """
        # Rate limit check
        if not self._rate_limiter.acquire(blocking=False):
            logger.warning("Rate limit exceeded, cannot cancel order")
            return False

        if self.dry_run:
            logger.info(f"[DRY-RUN] Cancel order: {order_id}")
            return True

        try:
            self._client.cancel_order(order_id)
            logger.info(f"Cancelled order: {order_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}", exc_info=True)
            return False

    def cancel_all_orders(self, token_id: Optional[str] = None) -> int:
        """
        Cancel all orders, optionally filtered by token.

        Args:
            token_id: If provided, only cancel orders for this token

        Returns:
            Number of orders cancelled
        """
        if self.dry_run:
            logger.info(f"[DRY-RUN] Cancel all orders (token_id={token_id})")
            return 0

        try:
            if token_id:
                response = self._client.cancel_orders(token_id=token_id)
            else:
                response = self._client.cancel_all()

            count = len(response.get("cancelled", []))
            logger.info(f"Cancelled {count} orders (token_id={token_id})")
            return count

        except Exception as e:
            logger.error(f"Failed to cancel all orders: {e}", exc_info=True)
            return 0

    def get_order_status(self, order_id: str) -> Optional[Dict]:
        """
        Get order status.

        Args:
            order_id: Order ID

        Returns:
            Order status dict or None
        """
        if self.dry_run:
            logger.debug(f"[DRY-RUN] Get order status: {order_id}")
            return None

        try:
            response = self._client.get_order(order_id)
            return response

        except Exception as e:
            logger.error(f"Failed to get order status for {order_id}: {e}", exc_info=True)
            return None

    def get_open_orders(self, token_id: Optional[str] = None) -> list:
        """
        Get open orders.

        Args:
            token_id: If provided, filter by token

        Returns:
            List of open orders
        """
        if self.dry_run:
            logger.debug(f"[DRY-RUN] Get open orders (token_id={token_id})")
            return []

        try:
            response = self._client.get_orders(token_id=token_id)
            return response.get("orders", [])

        except Exception as e:
            logger.error(f"Failed to get open orders: {e}", exc_info=True)
            return []
