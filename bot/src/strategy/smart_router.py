"""
Smart strategy router - implements the '3 Modes' logic and toxicity gating.
Replaces the basic HybridRouter for the 'Smart Survival' strategy.
"""
from typing import List, Dict, Optional, Tuple
from src.models import Market, BookTop, RefPrice, Position, Intent, IntentMode, Side
from src.strategy.fair_price import FairPriceCalculator
from src.strategy.lag_arb import LagArbStrategy
from src.strategy.market_maker import MarketMakerStrategy
from src.strategy.toxicity import ToxicityDetector
from src.strategy.fee_model import FeeModel
from src.logging_setup import get_logger

logger = get_logger("smart_router")

class SmartRouter:
    """
    Smart router with 3 modes and toxicity gating.
    
    Modes:
    1. Maker Mode (Default): Provide liquidity if regime is safe.
    2. Parity Mode: Check if YES + NO < 1.0 (Arbitrage).
    3. Taker Mode: Only if edge > fee_buffer + slippage.
    
    Gates:
    - Toxicity: If market is toxic (wide spread, high vol), go FLAT or WIDEN quotes.
    - Fees: If edge doesn't cover fees, don't trade.
    """

    def __init__(
        self,
        fair_price_calc: FairPriceCalculator,
        lag_arb: LagArbStrategy,
        market_maker: MarketMakerStrategy,
        toxicity_detector: ToxicityDetector,
        fee_model: FeeModel
    ):
        self.fair_price_calc = fair_price_calc
        self.lag_arb = lag_arb
        self.market_maker = market_maker
        self.toxicity = toxicity_detector
        self.fee_model = fee_model
        
        logger.info("Initialized SmartRouter with 3-mode logic")

    def generate_all_intents(
        self,
        markets: Dict[str, Market],
        books: Dict[str, BookTop],
        ref_prices: Dict[str, RefPrice],
        positions: Dict[str, Position],
        current_ts: int,
        symbol_mapping: Optional[Dict[str, str]] = None
    ) -> List[Intent]:
        """Generate intents for all markets."""
        all_intents = []

        for slug, market in markets.items():
            # Get books for both sides (needed for parity check)
            book_yes = books.get(market.yes_token_id)
            book_no = books.get(market.no_token_id)
            
            if not book_yes or not book_no:
                continue

            # Determine reference symbol (logic borrowed from HybridRouter)
            symbol = "UNKNOWN"
            if symbol_mapping and slug in symbol_mapping:
                symbol = symbol_mapping[slug]
            elif "btc" in slug.lower(): symbol = "BTCUSDT"
            elif "eth" in slug.lower(): symbol = "ETHUSDT"
            
            ref_price = ref_prices.get(symbol)
            
            # Generate intents for this market
            market_intents = self._process_single_market(
                market, book_yes, book_no, ref_price, positions, current_ts
            )
            all_intents.extend(market_intents)

        return all_intents

    def _get_market_type(self, slug: str) -> str:
        """Determine market type from slug."""
        slug_lower = slug.lower()
        if "15-min" in slug_lower or "rolling" in slug_lower:
            return "rolling15"
        return "default"

    def _process_single_market(
        self,
        market: Market,
        book_yes: BookTop,
        book_no: BookTop,
        ref_price: Optional[RefPrice],
        positions: Dict[str, Position],
        current_ts: int
    ) -> List[Intent]:
        """Process a single market through the decision tree."""
        intents = []
        market_type = self._get_market_type(market.slug)
        
        # 1. Toxicity Check
        # If ref_price is available, use it for vol check. If not, rely on book.
        is_toxic = False
        if ref_price:
            is_toxic = self.toxicity.is_toxic(book_yes, ref_price)
        elif book_yes.spread and book_yes.spread > 0.05:
            is_toxic = True
            logger.debug(f"Toxic spread detected: {book_yes.spread}")

        if is_toxic:
            # In toxic regime, we DO NOT quote tight.
            # We might cancel existing orders (empty list returns does this in reconciliation)
            # Or quote very wide (passive).
            # For "Smart Survival", we just step aside.
            logger.debug(f"Skipping {market.slug} due to toxicity")
            return []

        # 2. Parity Arb Check (Risk-free*)
        # Check if Best Ask YES + Best Ask NO < 1.0 (minus fees)
        # *Not truly risk free due to execution risk, but close
        if book_yes.ask_px and book_no.ask_px:
            cost_basis = book_yes.ask_px + book_no.ask_px
            # Calculate dynamic fee for both legs
            fee_yes = self.fee_model.get_taker_fee_rate(book_yes.ask_px, market_type)
            fee_no = self.fee_model.get_taker_fee_rate(book_no.ask_px, market_type)
            total_fee_rate = fee_yes + fee_no
            
            # Parity Threshold: 1.0 - Fees - Buffer
            # Buffer: 0.5% for slippage/execution risk
            max_cost = 1.0 - total_fee_rate - 0.005
            
            if cost_basis < max_cost:
                profit_pct = (1.0 - cost_basis - total_fee_rate) * 100
                logger.info(f"Parity Arb found on {market.slug}: Cost {cost_basis:.4f} vs Max {max_cost:.4f} (Profit: {profit_pct:.2f}%)")
                
                # Generate Immediate Taker Intents for both legs
                # Size limited by min liquidity of both sides
                safe_size = min(book_yes.ask_sz or 0, book_no.ask_sz or 0, 10.0) # Cap at 10 shares for safety
                if safe_size >= market.min_size:
                    intent_yes = Intent(
                        token_id=market.yes_token_id,
                        side=Side.BUY,
                        price=book_yes.ask_px,
                        size=safe_size,
                        mode=IntentMode.TAKER,
                        ttl_us=500_000, # Fast expire
                        reason=f"parity_arb_yes_cost={cost_basis:.4f}"
                    )
                    intent_no = Intent(
                        token_id=market.no_token_id,
                        side=Side.BUY,
                        price=book_no.ask_px,
                        size=safe_size,
                        mode=IntentMode.TAKER,
                        ttl_us=500_000,
                        reason=f"parity_arb_no_cost={cost_basis:.4f}"
                    )
                    # Return immediately to execute arb
                    return [intent_yes, intent_no]

        # 3. Fair Price Calculation
        p_fair = None
        if ref_price:
            p_fair = self.fair_price_calc.calculate_fair_prob(market, ref_price, current_ts)
        
        # If we can't calculate fair price (e.g. sports without live feed), 
        # we can still market make based on mid-price, but with caution.
        if p_fair is None:
            # Fallback to mid-price for market making, but don't snipe
            if book_yes.mid:
                p_fair = book_yes.mid
            else:
                return []

        # 4. Taker Mode (Snipe)
        # Only if we have a high confidence fair price (from ref_price)
        if ref_price:
            taker_intents = self.lag_arb.generate_intents(market, book_yes, p_fair)
            if taker_intents:
                # Fee Gate
                intent = taker_intents[0]
                trade_val = intent.price * intent.size
                
                # Use dynamic fee calculation
                required_edge = self.fee_model.get_min_edge(trade_val, intent.price, is_taker=True, market_type=market_type)
                
                # Check if edge exceeds required edge
                current_edge = abs(p_fair - intent.price)
                if current_edge > required_edge:
                    logger.info(f"Snipe triggered: Edge {current_edge:.4f} > Required {required_edge:.4f}")
                    return taker_intents
                else:
                    logger.debug(f"Snipe ignored: Edge {current_edge:.4f} < Required {required_edge:.4f}")

        # 5. Maker Mode (Default)
        # Check if we should be a maker (safe regime)
        # For Rolling 15s (Crypto), we prioritize this engine
        maker_intents = self.market_maker.generate_intents(market, p_fair, positions)
        return maker_intents
