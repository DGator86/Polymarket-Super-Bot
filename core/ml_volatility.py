"""
Machine Learning Volatility Forecasting

Provides ML-based volatility predictions for crypto strategies:
- GARCH-like volatility modeling
- Feature engineering from price data
- Rolling volatility estimation with adaptive windows
- Regime detection (low/medium/high volatility states)

Used to improve probability calculations for crypto price threshold markets.
"""

import logging
import numpy as np
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional, List, Dict, Tuple, Deque
from dataclasses import dataclass, field
from collections import deque
from enum import Enum
import math

logger = logging.getLogger(__name__)


class VolatilityRegime(Enum):
    """Market volatility regime"""
    LOW = "low"           # <20% annualized
    MEDIUM = "medium"     # 20-60% annualized
    HIGH = "high"         # 60-100% annualized
    EXTREME = "extreme"   # >100% annualized


@dataclass
class PriceObservation:
    """Single price observation for volatility calculation"""
    timestamp: datetime
    price: float
    volume: float = 0.0
    
    @property
    def timestamp_ms(self) -> int:
        return int(self.timestamp.timestamp() * 1000)


@dataclass
class VolatilityForecast:
    """Volatility forecast output"""
    symbol: str
    timestamp: datetime
    
    # Volatility estimates (annualized)
    realized_vol_1h: float      # 1-hour realized volatility
    realized_vol_24h: float     # 24-hour realized volatility
    realized_vol_7d: float      # 7-day realized volatility
    
    # Forecasted volatility
    forecast_1h: float          # 1-hour forward forecast
    forecast_24h: float         # 24-hour forward forecast
    
    # Regime classification
    regime: VolatilityRegime
    regime_confidence: float    # 0-1
    
    # Additional metrics
    volatility_trend: str       # "increasing", "stable", "decreasing"
    vol_of_vol: float          # Volatility of volatility
    
    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "realized_vol_1h": self.realized_vol_1h,
            "realized_vol_24h": self.realized_vol_24h,
            "realized_vol_7d": self.realized_vol_7d,
            "forecast_1h": self.forecast_1h,
            "forecast_24h": self.forecast_24h,
            "regime": self.regime.value,
            "regime_confidence": self.regime_confidence,
            "volatility_trend": self.volatility_trend,
            "vol_of_vol": self.vol_of_vol
        }


@dataclass
class GARCHParams:
    """GARCH(1,1) model parameters"""
    omega: float = 0.00001   # Long-run variance constant
    alpha: float = 0.1       # Shock coefficient (recent returns)
    beta: float = 0.85       # Persistence coefficient
    
    @property
    def persistence(self) -> float:
        """Alpha + Beta - measures volatility clustering"""
        return self.alpha + self.beta
    
    @property
    def long_run_variance(self) -> float:
        """Unconditional variance"""
        if self.persistence >= 1:
            return self.omega / 0.01  # Cap if near-integrated
        return self.omega / (1 - self.persistence)


class VolatilityForecaster:
    """
    ML-based volatility forecasting engine.
    
    Combines:
    - Rolling realized volatility
    - GARCH-style conditional variance
    - Regime detection via volatility clustering
    - Adaptive window sizing based on market conditions
    
    Usage:
        forecaster = VolatilityForecaster()
        forecaster.add_price(PriceObservation(...))
        forecast = forecaster.get_forecast("BTC-USD")
    """
    
    # Annualization factor (assuming continuous 24/7 trading)
    MINUTES_PER_YEAR = 525600  # 365.25 * 24 * 60
    HOURS_PER_YEAR = 8766      # 365.25 * 24
    
    # Regime thresholds (annualized volatility)
    REGIME_THRESHOLDS = {
        VolatilityRegime.LOW: 0.20,
        VolatilityRegime.MEDIUM: 0.60,
        VolatilityRegime.HIGH: 1.00,
        VolatilityRegime.EXTREME: float('inf')
    }
    
    def __init__(
        self,
        max_observations: int = 10080,  # 7 days of minute data
        min_observations: int = 60,      # Minimum for any calculation
        garch_params: GARCHParams = None
    ):
        self.max_observations = max_observations
        self.min_observations = min_observations
        self.garch = garch_params or GARCHParams()
        
        # Price history by symbol
        self._prices: Dict[str, Deque[PriceObservation]] = {}
        
        # Return history by symbol
        self._returns: Dict[str, Deque[float]] = {}
        
        # GARCH conditional variance state
        self._garch_variance: Dict[str, float] = {}
        
        # Volatility history for regime detection
        self._vol_history: Dict[str, Deque[float]] = {}
    
    def add_price(self, symbol: str, observation: PriceObservation):
        """
        Add a new price observation.
        Updates returns and GARCH state.
        """
        if symbol not in self._prices:
            self._prices[symbol] = deque(maxlen=self.max_observations)
            self._returns[symbol] = deque(maxlen=self.max_observations)
            self._vol_history[symbol] = deque(maxlen=168)  # 1 week of hourly
            self._garch_variance[symbol] = self.garch.long_run_variance
        
        prices = self._prices[symbol]
        returns = self._returns[symbol]
        
        # Calculate return if we have previous price
        if prices:
            prev_price = prices[-1].price
            if prev_price > 0:
                log_return = math.log(observation.price / prev_price)
                returns.append(log_return)
                
                # Update GARCH variance
                self._update_garch(symbol, log_return)
        
        prices.append(observation)
    
    def add_prices_batch(self, symbol: str, observations: List[PriceObservation]):
        """Add multiple price observations efficiently"""
        for obs in sorted(observations, key=lambda x: x.timestamp):
            self.add_price(symbol, obs)
    
    def _update_garch(self, symbol: str, return_val: float):
        """
        Update GARCH(1,1) conditional variance.
        
        σ²_t = ω + α * r²_{t-1} + β * σ²_{t-1}
        """
        prev_var = self._garch_variance.get(symbol, self.garch.long_run_variance)
        
        new_var = (
            self.garch.omega +
            self.garch.alpha * (return_val ** 2) +
            self.garch.beta * prev_var
        )
        
        # Bound variance to prevent explosion
        new_var = max(1e-10, min(new_var, 1.0))
        
        self._garch_variance[symbol] = new_var
    
    def _calculate_realized_vol(
        self,
        symbol: str,
        window_minutes: int
    ) -> Optional[float]:
        """
        Calculate realized volatility over a time window.
        Uses log returns and annualizes.
        """
        returns = self._returns.get(symbol)
        if not returns or len(returns) < self.min_observations:
            return None
        
        # Get returns within window
        window_returns = list(returns)[-window_minutes:]
        
        if len(window_returns) < 2:
            return None
        
        # Calculate variance of returns
        mean_return = sum(window_returns) / len(window_returns)
        variance = sum((r - mean_return) ** 2 for r in window_returns) / (len(window_returns) - 1)
        
        # Annualize (scale by sqrt of periods per year)
        periods_per_year = self.MINUTES_PER_YEAR / 1  # Assuming 1-minute returns
        annualized_vol = math.sqrt(variance * periods_per_year)
        
        return annualized_vol
    
    def _calculate_ewma_vol(
        self,
        symbol: str,
        span: int = 60,
        min_periods: int = 20
    ) -> Optional[float]:
        """
        Calculate exponentially weighted moving average volatility.
        More responsive to recent changes than simple realized vol.
        """
        returns = self._returns.get(symbol)
        if not returns or len(returns) < min_periods:
            return None
        
        returns_list = list(returns)
        
        # EWMA decay factor
        alpha = 2 / (span + 1)
        
        # Initialize with simple variance
        ewma_var = sum(r ** 2 for r in returns_list[:min_periods]) / min_periods
        
        # Update with EWMA
        for ret in returns_list[min_periods:]:
            ewma_var = alpha * (ret ** 2) + (1 - alpha) * ewma_var
        
        # Annualize
        annualized_vol = math.sqrt(ewma_var * self.MINUTES_PER_YEAR)
        
        return annualized_vol
    
    def _classify_regime(
        self,
        volatility: float
    ) -> Tuple[VolatilityRegime, float]:
        """
        Classify current volatility regime.
        Returns regime and confidence level.
        """
        for regime, threshold in self.REGIME_THRESHOLDS.items():
            if volatility < threshold:
                # Calculate confidence based on distance to boundaries
                if regime == VolatilityRegime.LOW:
                    confidence = min(1.0, (threshold - volatility) / threshold)
                elif regime == VolatilityRegime.EXTREME:
                    confidence = min(1.0, (volatility - 1.0) / 1.0)
                else:
                    # Distance from midpoint of regime
                    prev_threshold = list(self.REGIME_THRESHOLDS.values())[
                        list(self.REGIME_THRESHOLDS.keys()).index(regime) - 1
                    ]
                    midpoint = (prev_threshold + threshold) / 2
                    distance = abs(volatility - midpoint)
                    max_distance = (threshold - prev_threshold) / 2
                    confidence = max(0.5, 1 - distance / max_distance)
                
                return regime, confidence
        
        return VolatilityRegime.EXTREME, 0.9
    
    def _detect_trend(self, symbol: str, window: int = 24) -> str:
        """
        Detect volatility trend over recent window.
        """
        vol_history = self._vol_history.get(symbol)
        if not vol_history or len(vol_history) < window:
            return "stable"
        
        recent = list(vol_history)[-window:]
        
        # Compare first half to second half
        first_half = sum(recent[:window//2]) / (window // 2)
        second_half = sum(recent[window//2:]) / (window - window // 2)
        
        change_pct = (second_half - first_half) / first_half if first_half > 0 else 0
        
        if change_pct > 0.15:
            return "increasing"
        elif change_pct < -0.15:
            return "decreasing"
        else:
            return "stable"
    
    def _calculate_vol_of_vol(self, symbol: str) -> float:
        """
        Calculate volatility of volatility.
        High VoV suggests unstable regime, requires more conservative sizing.
        """
        vol_history = self._vol_history.get(symbol)
        if not vol_history or len(vol_history) < 10:
            return 0.3  # Default moderate VoV
        
        vol_list = list(vol_history)
        
        if len(vol_list) < 2:
            return 0.3
        
        mean_vol = sum(vol_list) / len(vol_list)
        if mean_vol == 0:
            return 0.3
        
        variance = sum((v - mean_vol) ** 2 for v in vol_list) / (len(vol_list) - 1)
        std_vol = math.sqrt(variance)
        
        # Return coefficient of variation
        return std_vol / mean_vol
    
    def get_forecast(self, symbol: str) -> Optional[VolatilityForecast]:
        """
        Generate comprehensive volatility forecast.
        
        Returns:
            VolatilityForecast with multiple timeframes and regime info
        """
        if symbol not in self._prices or len(self._prices[symbol]) < self.min_observations:
            logger.debug(f"Insufficient data for {symbol} volatility forecast")
            return None
        
        # Calculate realized volatilities
        vol_1h = self._calculate_realized_vol(symbol, 60)
        vol_24h = self._calculate_realized_vol(symbol, 1440)
        vol_7d = self._calculate_realized_vol(symbol, 10080)
        
        if vol_1h is None:
            return None
        
        # EWMA volatility for responsiveness
        ewma_vol = self._calculate_ewma_vol(symbol)
        
        # GARCH forecast
        garch_var = self._garch_variance.get(symbol, self.garch.long_run_variance)
        garch_vol = math.sqrt(garch_var * self.MINUTES_PER_YEAR)
        
        # Blend forecasts (EWMA for short-term, GARCH for longer)
        if ewma_vol:
            forecast_1h = 0.6 * ewma_vol + 0.4 * garch_vol
            forecast_24h = 0.4 * ewma_vol + 0.6 * garch_vol
        else:
            forecast_1h = garch_vol
            forecast_24h = garch_vol
        
        # Update volatility history for regime tracking
        if symbol not in self._vol_history:
            self._vol_history[symbol] = deque(maxlen=168)
        self._vol_history[symbol].append(vol_1h)
        
        # Classify regime
        regime, regime_confidence = self._classify_regime(vol_24h or vol_1h)
        
        # Detect trend
        trend = self._detect_trend(symbol)
        
        # Vol of vol
        vov = self._calculate_vol_of_vol(symbol)
        
        return VolatilityForecast(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            realized_vol_1h=vol_1h,
            realized_vol_24h=vol_24h or vol_1h,
            realized_vol_7d=vol_7d or vol_24h or vol_1h,
            forecast_1h=forecast_1h,
            forecast_24h=forecast_24h,
            regime=regime,
            regime_confidence=regime_confidence,
            volatility_trend=trend,
            vol_of_vol=vov
        )
    
    def get_adjusted_kelly(
        self,
        symbol: str,
        base_kelly: float,
        edge: float
    ) -> float:
        """
        Adjust Kelly fraction based on volatility regime.
        
        In high volatility, reduce position sizes.
        In low volatility, can be more aggressive.
        """
        forecast = self.get_forecast(symbol)
        if not forecast:
            return base_kelly * 0.5  # Conservative default
        
        # Regime adjustments
        regime_multipliers = {
            VolatilityRegime.LOW: 1.2,
            VolatilityRegime.MEDIUM: 1.0,
            VolatilityRegime.HIGH: 0.6,
            VolatilityRegime.EXTREME: 0.3
        }
        
        regime_mult = regime_multipliers.get(forecast.regime, 1.0)
        
        # Trend adjustment
        trend_mult = 1.0
        if forecast.volatility_trend == "increasing":
            trend_mult = 0.8  # Reduce as vol increasing
        elif forecast.volatility_trend == "decreasing":
            trend_mult = 1.1  # Slightly increase as vol decreasing
        
        # Vol of vol adjustment (high uncertainty = more conservative)
        vov_mult = 1.0 - min(0.3, forecast.vol_of_vol * 0.5)
        
        adjusted = base_kelly * regime_mult * trend_mult * vov_mult
        
        # Ensure reasonable bounds
        return max(0.05, min(adjusted, base_kelly * 1.5))
    
    def calculate_price_threshold_prob(
        self,
        symbol: str,
        current_price: float,
        threshold: float,
        time_to_expiry_hours: float
    ) -> Optional[Decimal]:
        """
        Calculate probability of price exceeding threshold using ML volatility.
        
        Uses Black-Scholes N(d2) with forecasted volatility.
        """
        forecast = self.get_forecast(symbol)
        if not forecast:
            return None
        
        # Select appropriate volatility based on time horizon
        if time_to_expiry_hours <= 1:
            vol = forecast.forecast_1h
        else:
            vol = forecast.forecast_24h
        
        # Convert to appropriate time scale
        time_years = time_to_expiry_hours / self.HOURS_PER_YEAR
        vol_scaled = vol * math.sqrt(time_years)
        
        if vol_scaled <= 0 or current_price <= 0:
            return None
        
        # Black-Scholes d2
        log_moneyness = math.log(current_price / threshold)
        d2 = (log_moneyness - 0.5 * vol_scaled ** 2) / vol_scaled
        
        # N(d2) - probability of finishing above threshold
        from scipy.stats import norm
        prob_above = norm.cdf(d2)
        
        # Adjust for regime uncertainty
        # In extreme regimes, move probability toward 0.5
        uncertainty_adj = 1.0 - (1.0 - forecast.regime_confidence) * 0.2
        prob_adjusted = 0.5 + (prob_above - 0.5) * uncertainty_adj
        
        return Decimal(str(round(max(0.01, min(0.99, prob_adjusted)), 4)))
    
    def get_optimal_entry_window(
        self,
        symbol: str,
        target_expiry: datetime
    ) -> Dict[str, any]:
        """
        Suggest optimal entry timing based on volatility patterns.
        
        Returns:
            Dict with entry window recommendations
        """
        forecast = self.get_forecast(symbol)
        if not forecast:
            return {"recommendation": "insufficient_data"}
        
        hours_to_expiry = (target_expiry - datetime.now(timezone.utc)).total_seconds() / 3600
        
        recommendations = {
            "symbol": symbol,
            "regime": forecast.regime.value,
            "trend": forecast.volatility_trend,
            "hours_to_expiry": hours_to_expiry
        }
        
        # Entry timing based on regime and trend
        if forecast.regime == VolatilityRegime.EXTREME:
            recommendations["action"] = "wait"
            recommendations["reason"] = "Extreme volatility - wait for stabilization"
        elif forecast.volatility_trend == "increasing" and hours_to_expiry > 2:
            recommendations["action"] = "wait"
            recommendations["reason"] = "Volatility increasing - wait for peak"
        elif forecast.volatility_trend == "decreasing":
            recommendations["action"] = "enter_now"
            recommendations["reason"] = "Volatility decreasing - favorable entry"
        elif hours_to_expiry < 1:
            recommendations["action"] = "enter_now"
            recommendations["reason"] = "Near expiry - limited time"
        else:
            recommendations["action"] = "monitor"
            recommendations["reason"] = "Stable conditions - monitor for opportunity"
        
        recommendations["forecast"] = forecast.to_dict()
        
        return recommendations


# =============================================================================
# FEATURE ENGINEERING FOR ADVANCED ML
# =============================================================================

class VolatilityFeatureExtractor:
    """
    Extract features for more advanced ML models.
    Can be used with sklearn, XGBoost, or neural networks.
    """
    
    @staticmethod
    def extract_features(
        prices: List[PriceObservation],
        window_sizes: List[int] = [5, 15, 60, 240, 1440]
    ) -> Dict[str, float]:
        """
        Extract volatility features from price history.
        
        Features include:
        - Realized volatility at multiple windows
        - Return distribution moments
        - Price momentum
        - Volume-volatility correlation
        """
        if len(prices) < max(window_sizes):
            return {}
        
        # Calculate returns
        returns = []
        for i in range(1, len(prices)):
            if prices[i-1].price > 0:
                returns.append(math.log(prices[i].price / prices[i-1].price))
        
        if not returns:
            return {}
        
        features = {}
        
        # Volatility at different windows
        for window in window_sizes:
            if len(returns) >= window:
                window_returns = returns[-window:]
                variance = sum(r ** 2 for r in window_returns) / window
                features[f"vol_{window}m"] = math.sqrt(variance * 525600)  # Annualized
        
        # Return distribution moments
        if len(returns) >= 60:
            recent = returns[-60:]
            mean_ret = sum(recent) / len(recent)
            variance = sum((r - mean_ret) ** 2 for r in recent) / len(recent)
            std_ret = math.sqrt(variance)
            
            features["return_mean_1h"] = mean_ret
            features["return_std_1h"] = std_ret
            
            # Skewness
            if std_ret > 0:
                skew = sum((r - mean_ret) ** 3 for r in recent) / (len(recent) * std_ret ** 3)
                features["return_skew_1h"] = skew
                
                # Kurtosis
                kurt = sum((r - mean_ret) ** 4 for r in recent) / (len(recent) * std_ret ** 4) - 3
                features["return_kurt_1h"] = kurt
        
        # Price momentum
        if len(prices) >= 60:
            price_1h_ago = prices[-60].price
            current_price = prices[-1].price
            features["momentum_1h"] = (current_price - price_1h_ago) / price_1h_ago if price_1h_ago > 0 else 0
        
        if len(prices) >= 1440:
            price_24h_ago = prices[-1440].price
            current_price = prices[-1].price
            features["momentum_24h"] = (current_price - price_24h_ago) / price_24h_ago if price_24h_ago > 0 else 0
        
        # Volatility ratios (short-term vs long-term)
        if "vol_60m" in features and "vol_1440m" in features and features["vol_1440m"] > 0:
            features["vol_ratio_1h_24h"] = features["vol_60m"] / features["vol_1440m"]
        
        if "vol_5m" in features and "vol_60m" in features and features["vol_60m"] > 0:
            features["vol_ratio_5m_1h"] = features["vol_5m"] / features["vol_60m"]
        
        # High-low range
        if len(prices) >= 60:
            recent_prices = [p.price for p in prices[-60:]]
            high = max(recent_prices)
            low = min(recent_prices)
            if low > 0:
                features["range_1h"] = (high - low) / low
        
        return features


# =============================================================================
# SINGLETON INSTANCE FOR GLOBAL USE
# =============================================================================

_forecaster_instance: Optional[VolatilityForecaster] = None

def get_volatility_forecaster() -> VolatilityForecaster:
    """Get or create global volatility forecaster instance"""
    global _forecaster_instance
    if _forecaster_instance is None:
        _forecaster_instance = VolatilityForecaster()
    return _forecaster_instance
