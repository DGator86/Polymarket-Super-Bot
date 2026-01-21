"""
Probability Engine

Computes model probabilities for markets using external data sources,
compares to market-implied probabilities, and identifies trading opportunities.

This is where the "alpha" lives - the edge comes from better probability
estimates than the market consensus.
"""

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional, Dict, Callable, Awaitable
from dataclasses import dataclass
from enum import Enum

from config import config
from core.models import (
    NormalizedMarket, MarketCategory, Side, SignalType,
    TradingSignal, EconomicDataPoint, WeatherForecast, CryptoPrice
)
from connectors.fred import FREDClient
from connectors.noaa import NOAAClient
from connectors.coinbase import CoinbaseClient

logger = logging.getLogger(__name__)


class ModelType(Enum):
    """Types of probability models"""
    ECONOMIC_THRESHOLD = "economic_threshold"  # CPI > X, Unemployment < Y
    WEATHER_THRESHOLD = "weather_threshold"    # Temperature > X
    CRYPTO_THRESHOLD = "crypto_threshold"      # BTC > $X
    BINARY_EVENT = "binary_event"              # Generic yes/no
    CUSTOM = "custom"


@dataclass
class ModelOutput:
    """Output from a probability model"""
    model_type: ModelType
    probability: Decimal          # 0-1, our estimated probability of YES
    confidence: Decimal           # 0-1, how confident we are in the estimate
    inputs_used: Dict[str, any]   # Data that went into the model
    reasoning: str                # Human-readable explanation


@dataclass
class Opportunity:
    """A trading opportunity identified by the engine"""
    market: NormalizedMarket
    model_output: ModelOutput
    side: Side                    # Which side to trade
    edge: Decimal                 # Our edge (model_prob - market_prob, adjusted)
    expected_value: Decimal       # Expected profit per dollar risked
    signal: TradingSignal         # Ready-to-trade signal


class ProbabilityEngine:
    """
    Computes model probabilities and identifies trading opportunities.
    
    For each market that passes Universe Engine filters:
    1. Determine what type of market it is (economic, weather, crypto, etc.)
    2. Fetch relevant external data
    3. Run appropriate probability model
    4. Compare to market-implied probability
    5. Generate trading signal if edge exceeds threshold
    
    Usage:
        engine = ProbabilityEngine(fred, noaa, coinbase)
        opportunities = await engine.analyze(markets)
    """
    
    def __init__(
        self,
        fred_client: FREDClient = None,
        noaa_client: NOAAClient = None,
        coinbase_client: CoinbaseClient = None,
        min_edge: Decimal = None,
        min_confidence: Decimal = None
    ):
        self.fred = fred_client
        self.noaa = noaa_client
        self.coinbase = coinbase_client
        
        self.min_edge = min_edge or config.probability.min_edge_pct
        self.min_confidence = min_confidence or config.probability.confidence_threshold
        self.fee_pct = config.probability.kalshi_fee_pct
        
        # Model registry: category -> model function
        self._models: Dict[MarketCategory, Callable] = {
            MarketCategory.ECONOMICS: self._model_economic,
            MarketCategory.WEATHER: self._model_weather,
            MarketCategory.CRYPTO: self._model_crypto,
        }
    
    async def analyze(self, markets: List[NormalizedMarket]) -> List[Opportunity]:
        """
        Analyze markets and return trading opportunities.
        
        Args:
            markets: Pre-filtered markets from Universe Engine
        
        Returns:
            List of Opportunity objects, sorted by expected value
        """
        opportunities = []
        
        for market in markets:
            try:
                opp = await self._analyze_single(market)
                if opp:
                    opportunities.append(opp)
            except Exception as e:
                logger.warning(f"Error analyzing {market.ticker}: {e}")
        
        # Sort by expected value (best opportunities first)
        opportunities.sort(key=lambda o: o.expected_value, reverse=True)
        
        logger.info(f"Found {len(opportunities)} opportunities from {len(markets)} markets")
        
        return opportunities
    
    async def _analyze_single(self, market: NormalizedMarket) -> Optional[Opportunity]:
        """Analyze a single market for trading opportunity"""
        
        # Get appropriate model for this market category
        model_func = self._models.get(market.category, self._model_generic)
        
        # Run model to get probability estimate
        model_output = await model_func(market)
        
        if not model_output:
            return None
        
        if model_output.confidence < self.min_confidence:
            logger.debug(f"{market.ticker}: Low confidence ({model_output.confidence})")
            return None
        
        # Determine which side has edge
        market_prob = market.implied_prob_mid
        model_prob = model_output.probability
        
        # Calculate edge for YES side
        yes_edge = model_prob - market_prob
        
        # Calculate edge for NO side
        no_edge = (Decimal("1") - model_prob) - (Decimal("1") - market_prob)
        # Simplifies to: market_prob - model_prob (opposite of yes_edge)
        
        # Pick the side with positive edge
        if yes_edge > no_edge and yes_edge > self.min_edge:
            side = Side.YES
            edge = yes_edge
            entry_price = market.best_ask  # Cost to buy YES
        elif no_edge > yes_edge and no_edge > self.min_edge:
            side = Side.NO
            edge = no_edge
            entry_price = Decimal("1") - market.best_bid  # Cost to buy NO
        else:
            logger.debug(f"{market.ticker}: Insufficient edge (YES: {yes_edge}, NO: {no_edge})")
            return None
        
        # Adjust edge for fees
        adjusted_edge = edge - self.fee_pct
        if adjusted_edge <= 0:
            logger.debug(f"{market.ticker}: Edge eaten by fees")
            return None
        
        # Calculate expected value
        if side == Side.YES:
            win_prob = model_prob
            win_amount = Decimal("1") - entry_price
            lose_amount = entry_price
        else:
            win_prob = Decimal("1") - model_prob
            win_amount = Decimal("1") - entry_price
            lose_amount = entry_price
        
        ev = (win_prob * win_amount) - ((Decimal("1") - win_prob) * lose_amount)
        
        # Build trading signal
        import uuid
        signal = TradingSignal(
            signal_id=str(uuid.uuid4()),
            signal_type=SignalType.MODEL,
            ticker=market.ticker,
            venue=market.venue,
            side=side,
            model_probability=model_prob,
            market_probability=market_prob,
            confidence=model_output.confidence,
            edge=adjusted_edge,
            reason=model_output.reasoning,
            metadata={"model_type": model_output.model_type.value}
        )
        
        return Opportunity(
            market=market,
            model_output=model_output,
            side=side,
            edge=adjusted_edge,
            expected_value=ev,
            signal=signal
        )
    
    # =========================================================================
    # CATEGORY-SPECIFIC MODELS
    # =========================================================================
    
    async def _model_economic(self, market: NormalizedMarket) -> Optional[ModelOutput]:
        """
        Model for economic markets (CPI, unemployment, fed funds, etc.)
        
        Parses the market question to identify the metric and threshold,
        then uses FRED data to estimate probability.
        """
        if not self.fred:
            return None
        
        question = market.question.lower()
        
        # Try to identify the economic indicator
        if "cpi" in question or "inflation" in question:
            return await self._model_cpi(market)
        elif "unemployment" in question or "jobless" in question:
            return await self._model_unemployment(market)
        elif "fed" in question and ("rate" in question or "funds" in question):
            return await self._model_fed_funds(market)
        elif "gdp" in question:
            return await self._model_gdp(market)
        
        return None
    
    async def _model_cpi(self, market: NormalizedMarket) -> Optional[ModelOutput]:
        """Model for CPI/inflation markets"""
        
        # Get recent CPI data
        cpi_data = await self.fred.get_cpi_history(months=24)
        if len(cpi_data) < 13:
            return None
        
        # Calculate YoY inflation
        current_cpi = cpi_data[-1].value
        year_ago_cpi = cpi_data[-13].value if len(cpi_data) >= 13 else cpi_data[0].value
        yoy_inflation = ((current_cpi - year_ago_cpi) / year_ago_cpi) * 100
        
        # Parse threshold from question (e.g., "CPI > 3%")
        import re
        threshold_match = re.search(r'(\d+\.?\d*)\s*%', market.question)
        if not threshold_match:
            return None
        
        threshold = Decimal(threshold_match.group(1))
        
        # Simple model: based on current level and recent trend
        recent_trend = cpi_data[-1].value - cpi_data[-3].value  # 3-month change
        
        # Estimate probability based on distance from threshold
        distance = yoy_inflation - float(threshold)
        
        if distance > 0.5:
            prob = Decimal("0.85")  # Well above threshold
        elif distance > 0:
            prob = Decimal("0.65")  # Just above
        elif distance > -0.5:
            prob = Decimal("0.35")  # Just below
        else:
            prob = Decimal("0.15")  # Well below
        
        # Adjust for trend
        if recent_trend > 0:
            prob = min(prob + Decimal("0.1"), Decimal("0.95"))
        elif recent_trend < 0:
            prob = max(prob - Decimal("0.1"), Decimal("0.05"))
        
        return ModelOutput(
            model_type=ModelType.ECONOMIC_THRESHOLD,
            probability=prob,
            confidence=Decimal("0.7"),
            inputs_used={
                "current_yoy_inflation": float(yoy_inflation),
                "threshold": float(threshold),
                "recent_trend": float(recent_trend)
            },
            reasoning=f"YoY CPI at {yoy_inflation:.2f}% vs threshold {threshold}%"
        )
    
    async def _model_unemployment(self, market: NormalizedMarket) -> Optional[ModelOutput]:
        """Model for unemployment rate markets"""
        
        unemployment = await self.fred.get_unemployment_rate()
        if not unemployment:
            return None
        
        current_rate = unemployment.value
        
        # Parse threshold
        import re
        threshold_match = re.search(r'(\d+\.?\d*)\s*%', market.question)
        if not threshold_match:
            return None
        
        threshold = Decimal(threshold_match.group(1))
        
        # Check direction (above or below)
        is_above_market = "above" in market.question.lower() or ">" in market.question
        
        distance = current_rate - threshold
        
        # Unemployment is sticky - use tighter bands
        if is_above_market:
            if distance > Decimal("0.3"):
                prob = Decimal("0.90")
            elif distance > 0:
                prob = Decimal("0.70")
            elif distance > Decimal("-0.3"):
                prob = Decimal("0.40")
            else:
                prob = Decimal("0.15")
        else:  # Below threshold
            prob = Decimal("1") - prob  # Invert
        
        return ModelOutput(
            model_type=ModelType.ECONOMIC_THRESHOLD,
            probability=prob,
            confidence=Decimal("0.75"),
            inputs_used={"current_rate": float(current_rate), "threshold": float(threshold)},
            reasoning=f"Unemployment at {current_rate}% vs threshold {threshold}%"
        )
    
    async def _model_fed_funds(self, market: NormalizedMarket) -> Optional[ModelOutput]:
        """Model for Fed Funds rate decision markets"""
        
        lower, upper = await self.fred.get_fed_funds_target()
        if not lower or not upper:
            return None
        
        current_mid = (lower + upper) / 2
        
        # These markets are usually about rate changes
        # For simplicity, assume rates stay same (high probability of no change)
        
        return ModelOutput(
            model_type=ModelType.ECONOMIC_THRESHOLD,
            probability=Decimal("0.50"),  # Neutral - need more sophisticated model
            confidence=Decimal("0.5"),     # Low confidence without FOMC analysis
            inputs_used={"current_range": f"{lower}-{upper}"},
            reasoning=f"Fed funds currently at {lower}-{upper}%"
        )
    
    async def _model_gdp(self, market: NormalizedMarket) -> Optional[ModelOutput]:
        """Model for GDP growth markets"""
        
        gdp_growth = await self.fred.get_gdp_growth()
        if not gdp_growth:
            return None
        
        return ModelOutput(
            model_type=ModelType.ECONOMIC_THRESHOLD,
            probability=Decimal("0.50"),
            confidence=Decimal("0.5"),
            inputs_used={"last_gdp_growth": float(gdp_growth.value)},
            reasoning=f"Last GDP growth: {gdp_growth.value}%"
        )
    
    async def _model_weather(self, market: NormalizedMarket) -> Optional[ModelOutput]:
        """Model for weather markets (temperature, precipitation, etc.)"""
        
        if not self.noaa:
            return None
        
        # Parse location from question
        from connectors.noaa import LOCATIONS
        
        question_upper = market.question.upper()
        location = None
        lat, lon = None, None
        
        for city, coords in LOCATIONS.items():
            if city.replace("_", " ") in question_upper:
                location = city
                lat, lon = coords
                break
        
        if not lat or not lon:
            return None
        
        try:
            forecast = await self.noaa.get_forecast(lat, lon)
        except Exception as e:
            logger.warning(f"Weather forecast failed: {e}")
            return None
        
        if not forecast:
            return None
        
        # Parse temperature threshold
        import re
        temp_match = re.search(r'(\d+)\s*°?\s*[fF]', market.question)
        
        if temp_match:
            threshold = int(temp_match.group(1))
            
            # Get forecasted high
            daytime = [f for f in forecast if f.is_daytime]
            if not daytime:
                return None
            
            forecasted_high = daytime[0].temperature
            
            # Simple probability based on forecast vs threshold
            diff = forecasted_high - threshold
            
            if diff > 5:
                prob = Decimal("0.90")
            elif diff > 0:
                prob = Decimal("0.70")
            elif diff > -5:
                prob = Decimal("0.30")
            else:
                prob = Decimal("0.10")
            
            return ModelOutput(
                model_type=ModelType.WEATHER_THRESHOLD,
                probability=prob,
                confidence=Decimal("0.8"),
                inputs_used={
                    "location": location,
                    "forecasted_high": forecasted_high,
                    "threshold": threshold
                },
                reasoning=f"Forecast: {forecasted_high}°F vs threshold {threshold}°F"
            )
        
        return None
    
    async def _model_crypto(self, market: NormalizedMarket) -> Optional[ModelOutput]:
        """Model for crypto price threshold markets"""
        
        if not self.coinbase:
            return None
        
        question = market.question.lower()
        
        # Determine which crypto
        if "btc" in question or "bitcoin" in question:
            symbol = "BTC-USD"
        elif "eth" in question or "ethereum" in question:
            symbol = "ETH-USD"
        else:
            return None
        
        try:
            price = await self.coinbase.get_price(symbol)
        except Exception as e:
            logger.warning(f"Failed to get {symbol} price: {e}")
            return None
        
        # Parse threshold (e.g., "$100,000" or "100000")
        import re
        price_match = re.search(r'\$?([\d,]+)', market.question)
        if not price_match:
            return None
        
        threshold = Decimal(price_match.group(1).replace(",", ""))
        
        # Calculate probability using simple model
        hours_to_expiry = (market.expiry - datetime.now(timezone.utc)).total_seconds() / 3600
        
        prob = self.coinbase.calculate_price_threshold_prob(
            current_price=price.price,
            threshold=threshold,
            volatility_pct=Decimal("0.03"),  # ~3% daily vol assumption
            time_to_expiry_hours=hours_to_expiry
        )
        
        return ModelOutput(
            model_type=ModelType.CRYPTO_THRESHOLD,
            probability=prob,
            confidence=Decimal("0.65"),
            inputs_used={
                "symbol": symbol,
                "current_price": float(price.price),
                "threshold": float(threshold),
                "hours_to_expiry": hours_to_expiry
            },
            reasoning=f"{symbol} at ${price.price:,.0f} vs ${threshold:,.0f} threshold"
        )
    
    async def _model_generic(self, market: NormalizedMarket) -> Optional[ModelOutput]:
        """Fallback model for markets without specific models"""
        
        # For unknown market types, return None (don't trade what we can't model)
        return None
