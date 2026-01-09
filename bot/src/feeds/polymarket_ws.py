"""
Polymarket WebSocket feed for orderbook data.
"""
import asyncio
import threading
from typing import Dict, Optional, Set
from datetime import datetime
import websockets
import json
from src.models import BookTop
from src.logging_setup import get_logger

logger = get_logger("polymarket_ws")


class PolymarketBookFeed:
    """
    WebSocket client for Polymarket orderbook data.
    Maintains top-of-book snapshots per token_id.
    """

    def __init__(self, ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"):
        self.ws_url = ws_url
        self._books: Dict[str, BookTop] = {}
        self._lock = threading.RLock()
        self._subscribed_tokens: Set[str] = set()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def subscribe(self, token_ids: list[str]) -> None:
        """Subscribe to orderbook updates for given token IDs."""
        with self._lock:
            self._subscribed_tokens.update(token_ids)
        logger.info(f"Subscribed to {len(token_ids)} tokens")

    def unsubscribe(self, token_ids: list[str]) -> None:
        """Unsubscribe from orderbook updates."""
        with self._lock:
            self._subscribed_tokens.difference_update(token_ids)
        logger.info(f"Unsubscribed from {len(token_ids)} tokens")

    def get_book(self, token_id: str) -> Optional[BookTop]:
        """Get thread-safe snapshot of top-of-book for a token."""
        with self._lock:
            book = self._books.get(token_id)
            if book:
                # Return a copy to prevent external modification
                return BookTop(
                    token_id=book.token_id,
                    bid_px=book.bid_px,
                    bid_sz=book.bid_sz,
                    ask_px=book.ask_px,
                    ask_sz=book.ask_sz,
                    ts=book.ts
                )
        return None

    def get_all_books(self) -> Dict[str, BookTop]:
        """Get thread-safe snapshot of all books."""
        with self._lock:
            return {
                token_id: BookTop(
                    token_id=book.token_id,
                    bid_px=book.bid_px,
                    bid_sz=book.bid_sz,
                    ask_px=book.ask_px,
                    ask_sz=book.ask_sz,
                    ts=book.ts
                )
                for token_id, book in self._books.items()
            }

    def start(self) -> None:
        """Start the WebSocket feed in a background thread."""
        if self._running:
            logger.warning("Feed already running")
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="polymarket-ws")
        self._thread.start()
        logger.info("Polymarket WebSocket feed started")

    def stop(self) -> None:
        """Stop the WebSocket feed."""
        self._running = False
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Polymarket WebSocket feed stopped")

    def _run_loop(self) -> None:
        """Run the asyncio event loop in this thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._connect_and_consume())
        except Exception as e:
            logger.error(f"WebSocket loop error: {e}", exc_info=True)
        finally:
            self._loop.close()

    async def _connect_and_consume(self) -> None:
        """Connect to WebSocket and consume messages."""
        retry_delay = 1
        max_retry_delay = 60

        while self._running:
            try:
                async with websockets.connect(self.ws_url) as ws:
                    logger.info("Connected to Polymarket WebSocket")
                    retry_delay = 1  # Reset retry delay on successful connection

                    # Send subscription messages for all tokens
                    with self._lock:
                        for token_id in self._subscribed_tokens:
                            await self._send_subscribe(ws, token_id)

                    # Consume messages
                    async for message in ws:
                        if not self._running:
                            break
                        await self._handle_message(message)

            except websockets.exceptions.WebSocketException as e:
                logger.error(f"WebSocket error: {e}")
            except Exception as e:
                logger.error(f"Unexpected error in WebSocket: {e}", exc_info=True)

            if self._running:
                logger.info(f"Reconnecting in {retry_delay}s...")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)

    async def _send_subscribe(self, ws, token_id: str) -> None:
        """Send subscription message for a token."""
        message = {
            "type": "subscribe",
            "channel": "book",
            "market": token_id
        }
        await ws.send(json.dumps(message))

    async def _handle_message(self, message: str) -> None:
        """Handle incoming WebSocket message."""
        try:
            data = json.loads(message)

            # Handle different message types
            msg_type = data.get("type")
            if msg_type == "book":
                await self._handle_book_update(data)
            elif msg_type == "subscribed":
                logger.debug(f"Subscribed to {data.get('market')}")
            elif msg_type == "error":
                logger.error(f"WebSocket error message: {data}")

        except json.JSONDecodeError:
            logger.warning(f"Failed to decode message: {message}")
        except Exception as e:
            logger.error(f"Error handling message: {e}", exc_info=True)

    async def _handle_book_update(self, data: dict) -> None:
        """Handle orderbook update message."""
        token_id = data.get("market")
        if not token_id:
            return

        timestamp = int(datetime.now().timestamp() * 1000)

        # Parse bids and asks
        bids = data.get("bids", [])
        asks = data.get("asks", [])

        bid_px = float(bids[0]["price"]) if bids else None
        bid_sz = float(bids[0]["size"]) if bids else None
        ask_px = float(asks[0]["price"]) if asks else None
        ask_sz = float(asks[0]["size"]) if asks else None

        book = BookTop(
            token_id=token_id,
            bid_px=bid_px,
            bid_sz=bid_sz,
            ask_px=ask_px,
            ask_sz=ask_sz,
            ts=timestamp
        )

        with self._lock:
            self._books[token_id] = book

        logger.debug(f"Book update for {token_id}: bid={bid_px}@{bid_sz}, ask={ask_px}@{ask_sz}")


class SimulatedBookFeed(PolymarketBookFeed):
    """
    Simulated orderbook feed for testing.
    Generates synthetic book data without connecting to real WebSocket.
    """

    def __init__(self):
        super().__init__()
        self._sim_prices: Dict[str, float] = {}

    def set_simulated_price(self, token_id: str, mid_price: float, spread: float = 0.02) -> None:
        """Set simulated mid price and spread for a token."""
        self._sim_prices[token_id] = mid_price

        timestamp = int(datetime.now().timestamp() * 1000)
        book = BookTop(
            token_id=token_id,
            bid_px=mid_price - spread / 2,
            bid_sz=100.0,
            ask_px=mid_price + spread / 2,
            ask_sz=100.0,
            ts=timestamp
        )

        with self._lock:
            self._books[token_id] = book

        logger.debug(f"Simulated book for {token_id}: {book.bid_px}@{book.bid_sz} / {book.ask_px}@{book.ask_sz}")

    def start(self) -> None:
        """Simulated feed doesn't need background thread."""
        self._running = True
        logger.info("Simulated Polymarket feed started (no WebSocket connection)")

    def stop(self) -> None:
        """Stop simulated feed."""
        self._running = False
        logger.info("Simulated Polymarket feed stopped")
