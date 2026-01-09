"""
Kill switch mechanism for emergency shutdown.
"""
import threading
from typing import Optional, Callable
from src.logging_setup import get_logger

logger = get_logger("kill_switch")


class KillSwitch:
    """
    Emergency kill switch.

    When activated:
    1. Prevents all new trading
    2. Triggers emergency shutdown callbacks
    3. Thread-safe activation
    """

    def __init__(self):
        self._active = False
        self._lock = threading.RLock()
        self._callbacks: list[Callable] = []
        logger.info("Kill switch initialized (inactive)")

    def activate(self, reason: str = "Manual activation") -> None:
        """
        Activate the kill switch.

        Args:
            reason: Reason for activation
        """
        with self._lock:
            if self._active:
                logger.warning("Kill switch already active")
                return

            self._active = True
            logger.critical(f"KILL SWITCH ACTIVATED: {reason}")

            # Execute all callbacks
            for callback in self._callbacks:
                try:
                    callback()
                except Exception as e:
                    logger.error(f"Error in kill switch callback: {e}", exc_info=True)

    def is_active(self) -> bool:
        """Check if kill switch is active."""
        with self._lock:
            return self._active

    def register_callback(self, callback: Callable) -> None:
        """
        Register callback to execute on kill switch activation.

        Args:
            callback: Function to call when kill switch activates
        """
        with self._lock:
            self._callbacks.append(callback)
        logger.info(f"Registered kill switch callback: {callback.__name__}")

    def reset(self) -> None:
        """
        Reset the kill switch (use with caution).

        This should only be used after manually verifying
        the issue has been resolved.
        """
        with self._lock:
            if not self._active:
                logger.warning("Kill switch already inactive")
                return

            self._active = False
            logger.warning("KILL SWITCH RESET - trading may resume")
