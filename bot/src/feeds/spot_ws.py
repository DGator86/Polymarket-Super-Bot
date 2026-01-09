"""
Spot price WebSocket feed for reference prices.
"""
import asyncio
import threading
from typing import Dict, Optional
from datetime import datetime
from collections import deque
import math
from src.models import RefPrice
from src.logging_setup import get_logger

logger = get_logger("spot_ws")


class SpotPriceFeed:
    """
    WebSocket client for spot price data.
    Tracks spot prices, returns, and short-term volatility.

    This is a base class / interface. For production, implement
    a concrete subclass that connects to your data provider
    (e.g., Binance, Coinbase, etc.)
    """

    def __init__(self):
        self._prices: Dict[str, RefPrice] = {}
        self._lock = threading.RLock()
        self._price_history: Dict[str, deque] = {}  # symbol -> deque of (ts, price)
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def get_price(self, symbol: str) -> Optional[RefPrice]:
        """Get thread-safe snapshot of reference price for a symbol."""
        with self._lock:
            price = self._prices.get(symbol)
            if price:
                return RefPrice(
                    symbol=price.symbol,
                    spot_mid=price.spot_mid,
                    r_1s=price.r_1s,
                    r_5s=price.r_5s,
                    vol_30s=price.vol_30s,
                    ts=price.ts
                )
        return None

    def get_all_prices(self) -> Dict[str, RefPrice]:
        """Get thread-safe snapshot of all reference prices."""
        with self._lock:
            return {
                symbol: RefPrice(
                    symbol=price.symbol,
                    spot_mid=price.spot_mid,
                    r_1s=price.r_1s,
                    r_5s=price.r_5s,
                    vol_30s=price.vol_30s,
                    ts=price.ts
                )
                for symbol, price in self._prices.items()
            }

    def start(self) -> None:
        """Start the feed."""
        raise NotImplementedError("Subclass must implement start()")

    def stop(self) -> None:
        """Stop the feed."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Spot price feed stopped")

    def _update_price(self, symbol: str, mid_price: float, timestamp_ms: int) -> None:
        """
        Update price and calculate returns and volatility.
        Thread-safe internal method.
        """
        with self._lock:
            # Initialize history if needed
            if symbol not in self._price_history:
                self._price_history[symbol] = deque(maxlen=60)  # Keep 60 seconds of data

            history = self._price_history[symbol]
            history.append((timestamp_ms, mid_price))

            # Calculate returns
            r_1s = self._calculate_return(history, timestamp_ms, 1000)
            r_5s = self._calculate_return(history, timestamp_ms, 5000)

            # Calculate 30-second volatility (annualized)
            vol_30s = self._calculate_volatility(history, timestamp_ms, 30000)

            # Update reference price
            self._prices[symbol] = RefPrice(
                symbol=symbol,
                spot_mid=mid_price,
                r_1s=r_1s,
                r_5s=r_5s,
                vol_30s=vol_30s,
                ts=timestamp_ms
            )

    def _calculate_return(self, history: deque, current_ts: int, lookback_ms: int) -> float:
        """Calculate return over lookback period."""
        if len(history) < 2:
            return 0.0

        current_price = history[-1][1]
        target_ts = current_ts - lookback_ms

        # Find closest historical price
        for ts, price in reversed(history):
            if ts <= target_ts:
                return (current_price - price) / price if price > 0 else 0.0

        # Not enough history
        return 0.0

    def _calculate_volatility(self, history: deque, current_ts: int, window_ms: int) -> float:
        """Calculate annualized volatility over window."""
        if len(history) < 2:
            return 0.0

        target_ts = current_ts - window_ms
        returns = []

        # Collect returns in window
        prev_price = None
        for ts, price in history:
            if ts >= target_ts:
                if prev_price is not None:
                    ret = (price - prev_price) / prev_price if prev_price > 0 else 0.0
                    returns.append(ret)
                prev_price = price

        if len(returns) < 2:
            return 0.0

        # Calculate standard deviation of returns
        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        std_dev = math.sqrt(variance)

        # Annualize (assuming 1-second sampling)
        # Annual factor = sqrt(seconds_per_year) = sqrt(365.25 * 24 * 3600)
        annual_factor = math.sqrt(365.25 * 24 * 3600)
        annualized_vol = std_dev * annual_factor

        return annualized_vol


class SimulatedSpotFeed(SpotPriceFeed):
    """
    Simulated spot price feed for testing.
    Allows manual price updates without real WebSocket.
    """

    def __init__(self):
        super().__init__()
        logger.info("Initialized simulated spot feed")

    def set_price(self, symbol: str, mid_price: float) -> None:
        """Manually set spot price for a symbol."""
        timestamp_ms = int(datetime.now().timestamp() * 1000)
        self._update_price(symbol, mid_price, timestamp_ms)
        logger.debug(f"Simulated price for {symbol}: {mid_price}")

    def start(self) -> None:
        """Simulated feed doesn't need background thread."""
        self._running = True
        logger.info("Simulated spot feed started (no WebSocket connection)")

    def stop(self) -> None:
        """Stop simulated feed."""
        self._running = False
        logger.info("Simulated spot feed stopped")


class CSVReplayFeed(SpotPriceFeed):
    """
    Replay spot prices from CSV file for backtesting.

    CSV format: timestamp_ms, symbol, price
    """

    def __init__(self, csv_path: str, replay_speed: float = 1.0):
        super().__init__()
        self.csv_path = csv_path
        self.replay_speed = replay_speed
        self._data: list = []

    def load_csv(self) -> None:
        """Load CSV data."""
        import csv
        with open(self.csv_path, 'r') as f:
            reader = csv.DictReader(f)
            self._data = list(reader)
        logger.info(f"Loaded {len(self._data)} price records from {self.csv_path}")

    def start(self) -> None:
        """Start replaying CSV data."""
        if not self._data:
            self.load_csv()

        self._running = True
        self._thread = threading.Thread(target=self._replay, daemon=True, name="csv-replay")
        self._thread.start()
        logger.info("CSV replay feed started")

    def _replay(self) -> None:
        """Replay CSV data in background thread."""
        start_time = datetime.now().timestamp()
        first_ts = None

        for row in self._data:
            if not self._running:
                break

            ts_ms = int(row['timestamp_ms'])
            symbol = row['symbol']
            price = float(row['price'])

            if first_ts is None:
                first_ts = ts_ms

            # Calculate delay to maintain replay speed
            elapsed_real = datetime.now().timestamp() - start_time
            elapsed_sim = (ts_ms - first_ts) / 1000.0
            delay = (elapsed_sim / self.replay_speed) - elapsed_real

            if delay > 0:
                import time
                time.sleep(delay)

            self._update_price(symbol, price, ts_ms)

        logger.info("CSV replay completed")


class BinanceSpotFeed(SpotPriceFeed):
    """
    Real Binance WebSocket feed for spot prices.
    Connects to Binance's public WebSocket API.
    """

    def __init__(self, symbols: list[str]):
        super().__init__()
        self.symbols = symbols
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def start(self) -> None:
        """Start the Binance WebSocket feed."""
        if self._running:
            logger.warning("Feed already running")
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="binance-ws")
        self._thread.start()
        logger.info("Binance WebSocket feed started")

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
        """Connect to Binance WebSocket and consume messages."""
        import websockets
        import json

        # Build stream names (e.g., btcusdt@ticker)
        streams = [f"{s.lower()}@ticker" for s in self.symbols]
        ws_url = f"wss://stream.binance.com:9443/ws/{'/'.join(streams)}"

        retry_delay = 1
        max_retry_delay = 60

        while self._running:
            try:
                async with websockets.connect(ws_url) as ws:
                    logger.info("Connected to Binance WebSocket")
                    retry_delay = 1

                    async for message in ws:
                        if not self._running:
                            break

                        data = json.loads(message)
                        symbol = data.get('s')  # e.g., "BTCUSDT"
                        if symbol and 'c' in data:
                            price = float(data['c'])  # Last price
                            ts_ms = int(datetime.now().timestamp() * 1000)
                            self._update_price(symbol, price, ts_ms)

            except Exception as e:
                logger.error(f"Binance WebSocket error: {e}")

            if self._running:
                logger.info(f"Reconnecting in {retry_delay}s...")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)
