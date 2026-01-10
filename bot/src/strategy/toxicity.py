"""
Toxicity detection module.
Detects adverse market conditions to gate aggressive trading.
"""
from typing import Dict, List
from src.models import BookTop, RefPrice
from src.logging_setup import get_logger

logger = get_logger("toxicity")

class ToxicityDetector:
    """
    Analyzes market data for signs of toxicity/adverse selection.
    
    Signals:
    1. Volatility Spikes (Ref prices moving fast)
    2. Book Thinning (Liquidity disappearing)
    3. One-sided Flow (Market moving fast against us)
    """
    
    def __init__(self, vol_threshold: float = 0.02, spread_threshold: float = 0.05):
        self.vol_threshold = vol_threshold
        self.spread_threshold = spread_threshold
        
    def is_toxic(self, book: BookTop, ref_price: RefPrice) -> bool:
        """
        Check if the current market state is 'toxic'.
        """
        reasons = []
        
        # 1. Spread Check
        # If spread is huge (>5c), market makers are scared. We should be too.
        if book.spread and book.spread > self.spread_threshold:
            reasons.append(f"wide_spread({book.spread:.3f})")
            
        # 2. Reference Volatility
        # If the underlying asset (BTC/ETH) is moving violenty, don't quote tight.
        # r_5s is 5-second return. |0.001| = 0.1% move in 5s is huge for crypto.
        if abs(ref_price.r_5s) > 0.001:
             reasons.append(f"high_vol_5s({ref_price.r_5s:.4f})")
             
        if reasons:
            logger.debug(f"Toxic regime detected for {book.token_id}: {', '.join(reasons)}")
            return True
            
        return False
