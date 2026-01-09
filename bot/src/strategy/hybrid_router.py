"""
Hybrid strategy router - combines lag arb (A) and market making (B).
"""
from typing import List, Dict, Optional
from src.models import Market, BookTop, RefPrice, Position, Intent, IntentMode
from src.strategy.fair_price import FairPriceCalculator
from src.strategy.lag_arb import LagArbStrategy
from src.strategy.market_maker import MarketMakerStrategy
from src.logging_setup import get_logger

logger = get_logger("hybrid_router")


class HybridRouter:
    """
    Hybrid strategy router.

    Combines:
    - A) Lag arbitrage: take when edge is large
    - B) Market making: provide liquidity otherwise

    Priority:
    1. If strong taker edge exists, emit taker intent only
    2. Otherwise, emit maker intents (bid/ask quotes)

    Ensures no contradictory intents for same token.
    """

    def __init__(
        self,
        fair_price_calc: FairPriceCalculator,
        lag_arb: LagArbStrategy,
        market_maker: MarketMakerStrategy
    ):
        """
        Initialize hybrid router.

        Args:
            fair_price_calc: Fair price calculator
            lag_arb: Lag arbitrage strategy
            market_maker: Market maker strategy
        """
        self.fair_price_calc = fair_price_calc
        self.lag_arb = lag_arb
        self.market_maker = market_maker
        logger.info("Initialized hybrid router")

    def generate_intents(
        self,
        market: Market,
        book: BookTop,
        ref_price: RefPrice,
        positions: Dict[str, Position],
        current_ts: int
    ) -> List[Intent]:
        """
        Generate trading intents for a market.

        Args:
            market: Market definition
            book: Current orderbook
            ref_price: Reference spot price
            positions: Current positions
            current_ts: Current timestamp in seconds

        Returns:
            List of intents (either 1 taker or 2 makers)
        """
        intents = []

        # Check staleness
        if book.is_stale:
            logger.warning(f"Book is stale for {market.slug}, skipping")
            return intents

        if ref_price.is_stale:
            logger.warning(f"Reference price is stale for {ref_price.symbol}, skipping")
            return intents

        # Calculate fair probability
        p_fair = self.fair_price_calc.calculate_fair_prob(market, ref_price, current_ts)
        if p_fair is None:
            logger.warning(f"Could not calculate fair price for {market.slug}")
            return intents

        # Step 1: Check for lag arb opportunity (A)
        taker_intents = self.lag_arb.generate_intents(market, book, p_fair)

        if taker_intents:
            # Strong edge exists, use taker only
            logger.info(
                f"Taker edge detected for {market.slug}, emitting {len(taker_intents)} taker intents"
            )
            return taker_intents

        # Step 2: Generate maker quotes (B)
        maker_intents = self.market_maker.generate_intents(market, p_fair, positions)

        logger.debug(
            f"No taker edge for {market.slug}, emitting {len(maker_intents)} maker intents"
        )

        return maker_intents

    def generate_all_intents(
        self,
        markets: Dict[str, Market],
        books: Dict[str, BookTop],
        ref_prices: Dict[str, RefPrice],
        positions: Dict[str, Position],
        current_ts: int,
        symbol_mapping: Optional[Dict[str, str]] = None
    ) -> List[Intent]:
        """
        Generate intents for all markets.

        Args:
            markets: All active markets
            books: Orderbooks by token_id
            ref_prices: Reference prices by symbol
            positions: Current positions by token_id
            current_ts: Current timestamp in seconds
            symbol_mapping: Optional mapping from market slug to ref price symbol

        Returns:
            List of all intents across all markets
        """
        all_intents = []

        for slug, market in markets.items():
            # Get book for YES token
            book = books.get(market.yes_token_id)
            if not book:
                logger.debug(f"No book data for {slug}, skipping")
                continue

            # Determine reference symbol
            if symbol_mapping and slug in symbol_mapping:
                symbol = symbol_mapping[slug]
            else:
                # Default: extract from slug (e.g., "btc-above-100k" -> "BTCUSDT")
                symbol = self._extract_symbol_from_slug(slug)

            ref_price = ref_prices.get(symbol)
            if not ref_price:
                logger.debug(f"No reference price for {symbol}, skipping {slug}")
                continue

            # Generate intents for this market
            market_intents = self.generate_intents(
                market=market,
                book=book,
                ref_price=ref_price,
                positions=positions,
                current_ts=current_ts
            )

            all_intents.extend(market_intents)

        logger.info(f"Generated {len(all_intents)} total intents across {len(markets)} markets")
        return all_intents

    def _extract_symbol_from_slug(self, slug: str) -> str:
        """
        Extract reference symbol from market slug.

        Examples:
        - "btc-above-100k-by-march-2026" -> "BTCUSDT"
        - "eth-above-5k-by-march-2026" -> "ETHUSDT"

        Args:
            slug: Market slug

        Returns:
            Symbol for reference price lookup
        """
        slug_lower = slug.lower()

        # Simple pattern matching
        if "btc" in slug_lower:
            return "BTCUSDT"
        elif "eth" in slug_lower:
            return "ETHUSDT"
        elif "sol" in slug_lower:
            return "SOLUSDT"
        else:
            # Default fallback
            logger.warning(f"Could not extract symbol from slug: {slug}")
            return "UNKNOWN"
