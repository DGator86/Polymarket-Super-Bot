"""
Market registry - loads and manages market definitions.
"""
import json
from typing import Dict, Optional
from pathlib import Path
from src.models import Market
from src.logging_setup import get_logger

logger = get_logger("market_registry")


class MarketRegistry:
    """
    Manages market definitions loaded from JSON.

    JSON schema:
    {
      "markets": [
        {
          "slug": "btc-above-100k-by-feb-2026",
          "strike": 100000,
          "expiry_ts": 1738368000,
          "yes_token_id": "0x123...",
          "no_token_id": "0x456...",
          "tick_size": 0.01,
          "min_size": 1.0,
          "condition_id": "0xabc..."
        }
      ]
    }
    """

    def __init__(self, registry_path: str):
        self.registry_path = Path(registry_path)
        self._markets: Dict[str, Market] = {}
        self._token_to_market: Dict[str, str] = {}  # token_id -> slug
        self._load_markets()

    def _load_markets(self) -> None:
        """Load markets from JSON file."""
        if not self.registry_path.exists():
            logger.warning(f"Market registry not found at {self.registry_path}, using empty registry")
            return

        try:
            with open(self.registry_path, 'r') as f:
                data = json.load(f)

            for market_data in data.get("markets", []):
                market = Market(
                    slug=market_data["slug"],
                    strike=market_data.get("strike"),
                    expiry_ts=market_data["expiry_ts"],
                    yes_token_id=market_data["yes_token_id"],
                    no_token_id=market_data["no_token_id"],
                    tick_size=market_data.get("tick_size", 0.01),
                    min_size=market_data.get("min_size", 1.0),
                    condition_id=market_data.get("condition_id")
                )
                self._markets[market.slug] = market
                self._token_to_market[market.yes_token_id] = market.slug
                self._token_to_market[market.no_token_id] = market.slug

            logger.info(f"Loaded {len(self._markets)} markets from {self.registry_path}")

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse market registry JSON: {e}")
            raise
        except KeyError as e:
            logger.error(f"Missing required field in market registry: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to load market registry: {e}")
            raise

    def get_market(self, slug: str) -> Optional[Market]:
        """Get market by slug."""
        return self._markets.get(slug)

    def get_market_by_token(self, token_id: str) -> Optional[Market]:
        """Get market by token ID."""
        slug = self._token_to_market.get(token_id)
        if slug:
            return self._markets.get(slug)
        return None

    def get_all_markets(self) -> Dict[str, Market]:
        """Get all markets."""
        return self._markets.copy()

    def get_active_markets(self, current_ts: int) -> Dict[str, Market]:
        """Get markets that haven't expired yet."""
        return {
            slug: market
            for slug, market in self._markets.items()
            if market.expiry_ts > current_ts
        }

    def reload(self) -> None:
        """Reload markets from file."""
        self._markets.clear()
        self._token_to_market.clear()
        self._load_markets()
        logger.info("Market registry reloaded")
