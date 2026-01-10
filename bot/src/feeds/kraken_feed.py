"""
Kraken WebSocket feed for spot prices (US-friendly alternative to Binance).
"""
import asyncio
import threading
from typing import Optional
from datetime import datetime
from src.feeds.spot_ws import SpotPriceFeed
from src.logging_setup import get_logger

logger = get_logger("kraken_ws")


class KrakenSpotFeed(SpotPriceFeed):
    """
    Kraken WebSocket feed for spot prices.
    US-friendly alternative to Binance.
    """

    # Map common symbols to Kraken pairs
    SYMBOL_MAP = {
        "BTCUSDT": "XBT/USDT",
        "ETHUSDT": "ETH/USDT",
        "SOLUSDT": "SOL/USDT",
        "MATICUSDT": "MATIC/USDT",
        "ADAUSDT": "ADA/USDT",
        "DOGEUSDT": "DOGE/USDT",
        "DOTUSDT": "DOT/USDT",
        "AVAXUSDT": "AVAX/USDT",
        "LINKUSDT": "LINK/USDT",
        "UNIUSDT": "UNI/USDT",
    }

    def __init__(self, symbols: list[str]):
        super().__init__()
        self.symbols = symbols
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def start(self) -> None:
        """Start the Kraken WebSocket feed."""
        if self._running:
            logger.warning("Feed already running")
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="kraken-ws")
        self._thread.start()
        logger.info("Kraken WebSocket feed started")

    def _run_loop(self) -> None:
        """Run the asyncio event loop."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._connect_and_consume())
        except Exception as e:
            logger.error(f"WebSocket loop error: {e}", exc_info=True)
        finally:
            self._loop.close()

    async def _connect_and_consume(self) -> None:
        """Connect to Kraken WebSocket and consume messages."""
        import websockets
        import json

        ws_url = "wss://ws.kraken.com/"

        retry_delay = 1
        max_retry_delay = 60

        while self._running:
            try:
                async with websockets.connect(ws_url) as ws:
                    logger.info("Connected to Kraken WebSocket")
                    retry_delay = 1

                    # Subscribe to ticker for all symbols
                    pairs = []
                    for symbol in self.symbols:
                        kraken_pair = self.SYMBOL_MAP.get(symbol)
                        if kraken_pair:
                            pairs.append(kraken_pair)

                    if pairs:
                        subscribe_msg = {
                            "event": "subscribe",
                            "pair": pairs,
                            "subscription": {"name": "ticker"}
                        }
                        await ws.send(json.dumps(subscribe_msg))
                        logger.info(f"Subscribed to {len(pairs)} Kraken pairs")

                    async for message in ws:
                        if not self._running:
                            break

                        data = json.loads(message)

                        # Skip non-ticker messages
                        if not isinstance(data, list) or len(data) < 4:
                            continue

                        # Kraken ticker format: [channelID, data, channelName, pair]
                        if data[2] == "ticker":
                            pair = data[3]
                            ticker_data = data[1]

                            # Get last price (index 'c' = [price, lot_volume])
                            if 'c' in ticker_data:
                                price = float(ticker_data['c'][0])

                                # Convert back to standard symbol format
                                standard_symbol = None
                                for std_sym, kraken_pair in self.SYMBOL_MAP.items():
                                    if kraken_pair == pair:
                                        standard_symbol = std_sym
                                        break

                                if standard_symbol:
                                    ts_ms = int(datetime.now().timestamp() * 1000)
                                    self._update_price(standard_symbol, price, ts_ms)

            except Exception as e:
                logger.error(f"Kraken WebSocket error: {e}")

            if self._running:
                logger.info(f"Reconnecting in {retry_delay}s...")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)
