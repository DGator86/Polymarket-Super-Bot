"""
Rate limiter for API calls with microsecond precision.
"""
import threading
import time
from collections import deque
from typing import Optional
from src.logging_setup import get_logger
from src.utils.timing import now_us

logger = get_logger("rate_limiter")


class RateLimiter:
    """
    Token bucket rate limiter with microsecond precision.

    Enforces maximum requests per time window.
    Thread-safe.
    """

    def __init__(self, max_requests: int, window_seconds: float = 60.0):
        """
        Initialize rate limiter.

        Args:
            max_requests: Maximum requests allowed in window
            window_seconds: Time window in seconds
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.window_us = int(window_seconds * 1_000_000)  # Convert to microseconds
        self._timestamps: deque = deque()  # Store microsecond timestamps
        self._lock = threading.RLock()
        logger.info(f"Rate limiter initialized: {max_requests} requests per {window_seconds}s ({self.window_us}µs)")

    def acquire(self, blocking: bool = True, timeout: Optional[float] = None) -> bool:
        """
        Acquire permission to make a request.

        Args:
            blocking: If True, wait until permission granted
            timeout: Maximum time to wait in seconds (None = infinite)

        Returns:
            True if permission granted, False if denied (non-blocking only)
        """
        start_time_us = now_us()
        timeout_us = int(timeout * 1_000_000) if timeout is not None else None

        while True:
            with self._lock:
                now = now_us()
                cutoff = now - self.window_us

                # Remove old timestamps (outside window)
                while self._timestamps and self._timestamps[0] < cutoff:
                    self._timestamps.popleft()

                # Check if we can proceed
                if len(self._timestamps) < self.max_requests:
                    self._timestamps.append(now)
                    return True

            # If non-blocking, return immediately
            if not blocking:
                return False

            # If timeout exceeded, return False
            if timeout_us is not None and (now_us() - start_time_us) >= timeout_us:
                logger.warning("Rate limiter timeout exceeded")
                return False

            # Wait a bit before retrying (10ms)
            time.sleep(0.01)

    def get_available_requests(self) -> int:
        """Get number of available requests in current window."""
        with self._lock:
            now = now_us()
            cutoff = now - self.window_us

            # Remove old timestamps (outside window)
            while self._timestamps and self._timestamps[0] < cutoff:
                self._timestamps.popleft()

            return self.max_requests - len(self._timestamps)

    def reset(self) -> None:
        """Reset the rate limiter."""
        with self._lock:
            self._timestamps.clear()
        logger.info("Rate limiter reset")
