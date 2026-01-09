"""
Fair probability calculation for binary outcome markets.
"""
import math
from typing import Optional
from src.models import Market, RefPrice
from src.logging_setup import get_logger

logger = get_logger("fair_price")


def normal_cdf(x: float) -> float:
    """
    Approximation of the cumulative distribution function of the standard normal distribution.
    Uses the error function approximation.

    Args:
        x: Input value (z-score)

    Returns:
        Probability P(Z <= x) where Z ~ N(0,1)
    """
    # Using the error function approximation
    # CDF(x) = 0.5 * (1 + erf(x / sqrt(2)))
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def logistic_prob(distance: float, scale: float) -> float:
    """
    Logistic function for probability calculation.

    Args:
        distance: Distance from strike (spot - strike)
        scale: Scaling factor (incorporates volatility and time)

    Returns:
        Probability between 0 and 1
    """
    if scale <= 0:
        return 0.5

    # Clamp to prevent overflow
    x = distance / scale
    x = max(min(x, 100), -100)

    return 1.0 / (1.0 + math.exp(-x))


class FairPriceCalculator:
    """
    Calculate fair YES probability for binary outcome markets.

    For markets like "BTC above X at time T", uses spot price,
    strike, time to expiry, and volatility to compute probability.
    """

    def __init__(self, sigma_floor: float = 0.001, use_normal_cdf: bool = True):
        """
        Initialize fair price calculator.

        Args:
            sigma_floor: Minimum volatility to prevent division by zero
            use_normal_cdf: If True, use normal CDF; else use logistic function
        """
        self.sigma_floor = sigma_floor
        self.use_normal_cdf = use_normal_cdf
        logger.info(f"Initialized fair price calculator (use_normal_cdf={use_normal_cdf}, sigma_floor={sigma_floor})")

    def calculate_fair_prob(
        self,
        market: Market,
        ref_price: RefPrice,
        current_ts: int
    ) -> Optional[float]:
        """
        Calculate fair YES probability for a market.

        Args:
            market: Market definition
            ref_price: Current reference spot price
            current_ts: Current timestamp in seconds

        Returns:
            Fair probability [0, 1] or None if calculation not possible
        """
        # Check if market has required fields
        if market.strike is None:
            logger.warning(f"Market {market.slug} has no strike price")
            return None

        # Calculate distance from strike
        distance = ref_price.spot_mid - market.strike

        # Calculate time to expiry in seconds
        tau = max(market.expiry_ts - current_ts, 1)

        # Use volatility with floor
        sigma = max(ref_price.vol_30s, self.sigma_floor)

        if self.use_normal_cdf:
            # Normal CDF approach
            # z = distance / (sigma * sqrt(tau))
            # p_fair = Φ(z)
            vol_scaled = sigma * math.sqrt(tau)
            if vol_scaled == 0:
                vol_scaled = self.sigma_floor

            z_score = distance / vol_scaled
            p_fair = normal_cdf(z_score)

        else:
            # Logistic approach
            # p_fair = 1 / (1 + exp(-distance / scale))
            # where scale = k0 + k1 * sigma * sqrt(tau)
            k0 = 1000.0  # Base scale factor
            k1 = 100.0   # Volatility multiplier

            scale = k0 + k1 * sigma * math.sqrt(tau)
            p_fair = logistic_prob(distance, scale)

        # Clamp to [0.01, 0.99] to avoid extreme values
        p_fair = max(min(p_fair, 0.99), 0.01)

        logger.debug(
            f"Fair price for {market.slug}: spot={ref_price.spot_mid:.2f}, "
            f"strike={market.strike:.2f}, tau={tau}s, sigma={sigma:.4f}, "
            f"p_fair={p_fair:.4f}"
        )

        return p_fair

    def calculate_edge(
        self,
        p_fair: float,
        p_market: float
    ) -> float:
        """
        Calculate edge (mispricing).

        Args:
            p_fair: Fair probability
            p_market: Market-implied probability

        Returns:
            Edge = p_fair - p_market (positive means underpriced YES)
        """
        return p_fair - p_market


def clamp_to_tick(price: float, tick_size: float = 0.01) -> float:
    """
    Round price to nearest tick.

    Args:
        price: Raw price
        tick_size: Tick size (e.g., 0.01 for $0.01)

    Returns:
        Price rounded to nearest tick
    """
    if tick_size <= 0:
        return price

    ticks = round(price / tick_size)
    clamped = ticks * tick_size

    # Ensure within [0.01, 0.99]
    clamped = max(min(clamped, 0.99), 0.01)

    return round(clamped, 4)  # Round to avoid floating point errors


def calculate_inventory_skew(
    position_qty: float,
    max_inventory: float,
    skew_factor: float = 0.0001
) -> float:
    """
    Calculate inventory skew adjustment to fair price.

    If long YES, shift center price down (more aggressive ask, less aggressive bid).
    If short YES, shift center price up.

    Args:
        position_qty: Current position (positive = long YES, negative = short)
        max_inventory: Maximum allowed inventory
        skew_factor: Skew sensitivity (cents per unit of inventory)

    Returns:
        Price adjustment (negative if long, positive if short)
    """
    if max_inventory <= 0:
        return 0.0

    # Normalize position to [-1, 1] range
    normalized_position = position_qty / max_inventory

    # Skew is opposite to position direction
    # If long (+), we want to shift down (-) to encourage selling
    # If short (-), we want to shift up (+) to encourage buying
    skew = -normalized_position * skew_factor

    # Clamp skew to reasonable range
    skew = max(min(skew, 0.1), -0.1)

    return skew
