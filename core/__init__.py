# Core package
# Note: Imports are done carefully to avoid circular dependencies
from core.models import *

# Lazy imports for components that depend on connectors
def get_universe_engine():
    from core.universe_engine import UniverseEngine
    return UniverseEngine

def get_probability_engine():
    from core.probability_engine import ProbabilityEngine
    return ProbabilityEngine

def get_risk_manager():
    from core.risk_manager import RiskManager
    return RiskManager

def get_ml_volatility():
    from core.ml_volatility import (
        VolatilityForecaster,
        VolatilityForecast,
        VolatilityRegime,
        PriceObservation,
        get_volatility_forecaster
    )
    return {
        'VolatilityForecaster': VolatilityForecaster,
        'VolatilityForecast': VolatilityForecast,
        'VolatilityRegime': VolatilityRegime,
        'PriceObservation': PriceObservation,
        'get_volatility_forecaster': get_volatility_forecaster
    }

# Re-export for backwards compatibility - only import when actually used
__all__ = [
    # From models
    'Venue', 'Side', 'OrderType', 'OrderStatus', 'MarketCategory', 'SignalType',
    'NormalizedMarket', 'Orderbook', 'OrderbookLevel', 'OrderRequest', 'OrderResponse',
    'Position', 'TradingSignal', 'ArbitrageSignal', 'EconomicDataPoint', 
    'WeatherForecast', 'NewsItem', 'CryptoPrice', 'AccountBalance', 'DailyPnL',
    # Lazy loaders
    'get_universe_engine', 'get_probability_engine', 'get_risk_manager', 'get_ml_volatility'
]
