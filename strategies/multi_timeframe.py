"""
Multi-Timeframe Crypto Analysis Strategy

Analyzes crypto markets across multiple timeframes (5min, 10min, 15min, hourly)
to identify consistent edge opportunities.

Key concepts:
- Timeframe confluence: signals are stronger when multiple timeframes agree
- Momentum alignment: trend direction across different horizons
- Volatility scaling: adjust edge thresholds based on timeframe
- Optimal entry timing: identify best timeframe for entry

Used for Kalshi crypto price markets that expire at different intervals.
"""

import asyncio
import logging
import math
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional, List, Dict, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum
from collections import deque

from config import config
from core.models import (
    NormalizedMarket, TradingSignal, Side, SignalType, Venue, CryptoPrice
)
from core.ml_volatility import (
    VolatilityForecaster, PriceObservation, VolatilityRegime,
    get_volatility_forecaster
)
from connectors.kalshi import KalshiClient
from connectors.coinbase import CoinbaseClient

logger = logging.getLogger(__name__)


class Timeframe(Enum):
    """Supported trading timeframes"""
    M5 = "5min"
    M10 = "10min"
    M15 = "15min"
    M30 = "30min"
    H1 = "1hour"
    H4 = "4hour"
    D1 = "daily"
    
    @property
    def minutes(self) -> int:
        """Get timeframe in minutes"""
        mapping = {
            "5min": 5,
            "10min": 10,
            "15min": 15,
            "30min": 30,
            "1hour": 60,
            "4hour": 240,
            "daily": 1440
        }
        return mapping[self.value]
    
    @property
    def edge_multiplier(self) -> float:
        """Edge threshold multiplier (shorter TF needs higher edge)"""
        # Shorter timeframes need more edge to overcome noise
        mapping = {
            "5min": 1.5,
            "10min": 1.3,
            "15min": 1.0,
            "30min": 0.9,
            "1hour": 0.8,
            "4hour": 0.7,
            "daily": 0.6
        }
        return mapping[self.value]


class TrendDirection(Enum):
    """Price trend direction"""
    STRONG_UP = "strong_up"
    UP = "up"
    NEUTRAL = "neutral"
    DOWN = "down"
    STRONG_DOWN = "strong_down"


@dataclass
class TimeframeAnalysis:
    """Analysis results for a single timeframe"""
    timeframe: Timeframe
    symbol: str
    
    # Price data
    current_price: float
    price_at_start: float
    price_change_pct: float
    
    # Volatility
    realized_vol: float
    vol_regime: VolatilityRegime
    
    # Trend
    trend: TrendDirection
    trend_strength: float  # 0-1
    
    # Momentum indicators
    momentum_score: float  # -1 to 1
    rsi: float            # 0-100
    
    # Market structure
    support_level: float
    resistance_level: float
    
    # Timing
    minutes_to_close: int
    optimal_entry: bool
    
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> Dict:
        return {
            "timeframe": self.timeframe.value,
            "symbol": self.symbol,
            "current_price": self.current_price,
            "price_change_pct": self.price_change_pct,
            "realized_vol": self.realized_vol,
            "vol_regime": self.vol_regime.value,
            "trend": self.trend.value,
            "trend_strength": self.trend_strength,
            "momentum_score": self.momentum_score,
            "rsi": self.rsi,
            "minutes_to_close": self.minutes_to_close,
            "optimal_entry": self.optimal_entry
        }


@dataclass
class MultiTimeframeSignal:
    """Signal with multi-timeframe confluence"""
    symbol: str
    side: Side
    
    # Core signal data
    primary_timeframe: Timeframe
    model_probability: Decimal
    market_probability: Decimal
    edge: Decimal
    confidence: Decimal
    
    # Confluence data
    agreeing_timeframes: List[Timeframe]
    disagreeing_timeframes: List[Timeframe]
    confluence_score: float  # 0-1, higher = more timeframes agree
    
    # Timeframe analyses
    analyses: Dict[Timeframe, TimeframeAnalysis]
    
    # Market info
    ticker: str
    threshold: Decimal
    expiry: datetime
    
    # Timing
    optimal_entry_window: bool
    time_pressure: str  # "low", "medium", "high"
    
    reason: str
    
    def to_trading_signal(self) -> TradingSignal:
        """Convert to standard TradingSignal"""
        import uuid
        
        return TradingSignal(
            signal_id=str(uuid.uuid4()),
            signal_type=SignalType.MODEL,
            ticker=self.ticker,
            venue=Venue.KALSHI,
            side=self.side,
            model_probability=self.model_probability,
            market_probability=self.market_probability,
            confidence=self.confidence,
            edge=self.edge,
            urgency="high" if self.time_pressure == "high" else "normal",
            reason=self.reason,
            metadata={
                "strategy": "multi_timeframe",
                "primary_tf": self.primary_timeframe.value,
                "confluence_score": self.confluence_score,
                "agreeing_tfs": [tf.value for tf in self.agreeing_timeframes],
                "analyses": {tf.value: a.to_dict() for tf, a in self.analyses.items()}
            }
        )


@dataclass
class CryptoMarketInfo:
    """Parsed Kalshi crypto market info"""
    ticker: str
    symbol: str          # BTC-USD, ETH-USD
    threshold: Decimal
    is_above: bool       # True = "price > threshold"
    expiry: datetime
    timeframe: Timeframe
    market: NormalizedMarket


class MultiTimeframeStrategy:
    """
    Multi-timeframe analysis strategy for crypto markets.
    
    Analyzes price action across 5min, 10min, 15min, and hourly timeframes
    to find high-confluence trading opportunities.
    
    Key features:
    - Timeframe confluence scoring
    - Adaptive volatility thresholds
    - Momentum alignment detection
    - Optimal entry window identification
    
    Usage:
        strategy = MultiTimeframeStrategy(kalshi, coinbase)
        await strategy.initialize()
        signals = await strategy.analyze()
    """
    
    # Supported timeframes for analysis
    ANALYSIS_TIMEFRAMES = [
        Timeframe.M5,
        Timeframe.M15,
        Timeframe.H1,
        Timeframe.H4
    ]
    
    # Minimum confluence for signal
    MIN_CONFLUENCE = 0.5  # At least half of timeframes should agree
    
    def __init__(
        self,
        kalshi_client: KalshiClient,
        coinbase_client: CoinbaseClient,
        min_edge: Decimal = None,
        symbols: List[str] = None
    ):
        self.kalshi = kalshi_client
        self.coinbase = coinbase_client
        
        self.min_edge = min_edge or Decimal("0.03")  # 3% base edge
        self.symbols = symbols or ["BTC-USD", "ETH-USD"]
        
        # Volatility forecaster
        self.vol_forecaster = get_volatility_forecaster()
        
        # Price history
        self._price_history: Dict[str, deque] = {}
        for symbol in self.symbols:
            self._price_history[symbol] = deque(maxlen=10080)  # 7 days of minute data
        
        # Discovered markets
        self._markets: Dict[str, CryptoMarketInfo] = {}
        
        # Running state
        self._running = False
        self._last_prices: Dict[str, CryptoPrice] = {}
    
    async def initialize(self):
        """Discover crypto markets and initialize price feeds"""
        logger.info("Initializing multi-timeframe strategy...")
        
        # Discover Kalshi crypto markets
        await self._discover_markets()
        
        # Fetch initial price history
        await self._load_price_history()
        
        logger.info(f"Found {len(self._markets)} crypto markets across timeframes")
    
    async def _discover_markets(self):
        """Find all crypto price markets on Kalshi"""
        import re
        
        markets = await self.kalshi.get_markets(status="open", limit=1000)
        
        for raw in markets:
            question = (raw.get("title", "") + " " + raw.get("subtitle", "")).lower()
            
            # Check if crypto market
            symbol = None
            if "btc" in question or "bitcoin" in question:
                symbol = "BTC-USD"
            elif "eth" in question or "ethereum" in question:
                symbol = "ETH-USD"
            else:
                continue
            
            # Parse threshold
            price_match = re.search(r'\$?([\d,]+(?:\.\d+)?)', raw.get("title", ""))
            if not price_match:
                continue
            
            try:
                threshold = Decimal(price_match.group(1).replace(",", ""))
            except:
                continue
            
            # Parse expiry and determine timeframe
            expiry_str = raw.get("expiration_time", "")
            try:
                expiry = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
            except:
                continue
            
            minutes_to_expiry = (expiry - datetime.now(timezone.utc)).total_seconds() / 60
            
            # Classify timeframe
            if minutes_to_expiry <= 7:
                timeframe = Timeframe.M5
            elif minutes_to_expiry <= 12:
                timeframe = Timeframe.M10
            elif minutes_to_expiry <= 20:
                timeframe = Timeframe.M15
            elif minutes_to_expiry <= 35:
                timeframe = Timeframe.M30
            elif minutes_to_expiry <= 90:
                timeframe = Timeframe.H1
            elif minutes_to_expiry <= 300:
                timeframe = Timeframe.H4
            else:
                timeframe = Timeframe.D1
            
            # Get orderbook
            try:
                orderbook = await self.kalshi.get_orderbook(raw.get("ticker", ""))
                market = KalshiClient.normalize_market(raw, orderbook)
            except:
                continue
            
            is_above = "above" in question or ">" in question or "over" in question
            
            self._markets[raw.get("ticker", "")] = CryptoMarketInfo(
                ticker=raw.get("ticker", ""),
                symbol=symbol,
                threshold=threshold,
                is_above=is_above,
                expiry=expiry,
                timeframe=timeframe,
                market=market
            )
    
    async def _load_price_history(self):
        """Load recent price history for volatility calculations"""
        for symbol in self.symbols:
            try:
                # Get current price to seed history
                price = await self.coinbase.get_price(symbol)
                self._last_prices[symbol] = price
                
                obs = PriceObservation(
                    timestamp=price.timestamp,
                    price=float(price.price),
                    volume=float(price.volume_24h) if price.volume_24h else 0
                )
                self._price_history[symbol].append(obs)
                self.vol_forecaster.add_price(symbol, obs)
                
            except Exception as e:
                logger.warning(f"Failed to load price for {symbol}: {e}")
    
    async def analyze(self) -> List[MultiTimeframeSignal]:
        """
        Run multi-timeframe analysis on all markets.
        
        Returns:
            List of MultiTimeframeSignal objects with confluence data
        """
        signals = []
        
        # Update prices
        for symbol in self.symbols:
            try:
                price = await self.coinbase.get_price(symbol)
                self._last_prices[symbol] = price
                
                obs = PriceObservation(
                    timestamp=price.timestamp,
                    price=float(price.price)
                )
                self._price_history[symbol].append(obs)
                self.vol_forecaster.add_price(symbol, obs)
            except:
                pass
        
        # Group markets by symbol
        markets_by_symbol: Dict[str, List[CryptoMarketInfo]] = {}
        for ticker, info in self._markets.items():
            if info.symbol not in markets_by_symbol:
                markets_by_symbol[info.symbol] = []
            markets_by_symbol[info.symbol].append(info)
        
        # Analyze each symbol
        for symbol, market_list in markets_by_symbol.items():
            if symbol not in self._last_prices:
                continue
            
            current_price = self._last_prices[symbol]
            
            # Run timeframe analyses
            analyses = await self._analyze_timeframes(symbol, current_price)
            
            # Find signals for each market
            for market_info in market_list:
                signal = await self._evaluate_market(
                    market_info,
                    current_price,
                    analyses
                )
                if signal:
                    signals.append(signal)
        
        # Sort by confluence score
        signals.sort(key=lambda s: s.confluence_score, reverse=True)
        
        return signals
    
    async def _analyze_timeframes(
        self,
        symbol: str,
        current_price: CryptoPrice
    ) -> Dict[Timeframe, TimeframeAnalysis]:
        """Analyze all timeframes for a symbol"""
        analyses = {}
        
        price_history = list(self._price_history.get(symbol, []))
        if len(price_history) < 60:
            return analyses
        
        current = float(current_price.price)
        
        for tf in self.ANALYSIS_TIMEFRAMES:
            lookback = min(tf.minutes, len(price_history))
            if lookback < 5:
                continue
            
            window_prices = [p.price for p in price_history[-lookback:]]
            
            if not window_prices:
                continue
            
            # Calculate metrics
            start_price = window_prices[0]
            price_change = (current - start_price) / start_price if start_price > 0 else 0
            
            # Trend detection
            trend, trend_strength = self._detect_trend(window_prices)
            
            # Momentum
            momentum = self._calculate_momentum(window_prices)
            rsi = self._calculate_rsi(window_prices)
            
            # Support/Resistance
            support = min(window_prices)
            resistance = max(window_prices)
            
            # Volatility from forecaster
            vol_forecast = self.vol_forecaster.get_forecast(symbol)
            realized_vol = vol_forecast.realized_vol_1h if vol_forecast else 0.5
            vol_regime = vol_forecast.regime if vol_forecast else VolatilityRegime.MEDIUM
            
            # Entry timing (best in middle third of timeframe)
            now = datetime.now(timezone.utc)
            tf_start = now - timedelta(minutes=tf.minutes)
            elapsed_pct = (now - tf_start).total_seconds() / (tf.minutes * 60)
            optimal_entry = 0.3 < elapsed_pct < 0.7
            
            analyses[tf] = TimeframeAnalysis(
                timeframe=tf,
                symbol=symbol,
                current_price=current,
                price_at_start=start_price,
                price_change_pct=price_change,
                realized_vol=realized_vol,
                vol_regime=vol_regime,
                trend=trend,
                trend_strength=trend_strength,
                momentum_score=momentum,
                rsi=rsi,
                support_level=support,
                resistance_level=resistance,
                minutes_to_close=int((1 - elapsed_pct) * tf.minutes),
                optimal_entry=optimal_entry
            )
        
        return analyses
    
    def _detect_trend(self, prices: List[float]) -> Tuple[TrendDirection, float]:
        """Detect trend direction and strength"""
        if len(prices) < 5:
            return TrendDirection.NEUTRAL, 0.0
        
        # Linear regression slope
        n = len(prices)
        x_mean = (n - 1) / 2
        y_mean = sum(prices) / n
        
        numerator = sum((i - x_mean) * (prices[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        
        if denominator == 0:
            return TrendDirection.NEUTRAL, 0.0
        
        slope = numerator / denominator
        
        # Normalize slope by average price
        norm_slope = slope / y_mean if y_mean > 0 else 0
        
        # Classify
        if norm_slope > 0.002:
            return TrendDirection.STRONG_UP, min(1.0, norm_slope / 0.005)
        elif norm_slope > 0.0005:
            return TrendDirection.UP, min(1.0, norm_slope / 0.002)
        elif norm_slope < -0.002:
            return TrendDirection.STRONG_DOWN, min(1.0, abs(norm_slope) / 0.005)
        elif norm_slope < -0.0005:
            return TrendDirection.DOWN, min(1.0, abs(norm_slope) / 0.002)
        else:
            return TrendDirection.NEUTRAL, abs(norm_slope) / 0.0005
    
    def _calculate_momentum(self, prices: List[float]) -> float:
        """Calculate momentum score (-1 to 1)"""
        if len(prices) < 10:
            return 0.0
        
        # Rate of change over different periods
        roc_short = (prices[-1] - prices[-5]) / prices[-5] if prices[-5] > 0 else 0
        roc_long = (prices[-1] - prices[0]) / prices[0] if prices[0] > 0 else 0
        
        # Weighted average
        momentum = 0.6 * roc_short + 0.4 * roc_long
        
        # Normalize to -1 to 1
        return max(-1.0, min(1.0, momentum * 20))
    
    def _calculate_rsi(self, prices: List[float], period: int = 14) -> float:
        """Calculate RSI indicator"""
        if len(prices) < period + 1:
            return 50.0
        
        changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        
        gains = [c if c > 0 else 0 for c in changes[-period:]]
        losses = [abs(c) if c < 0 else 0 for c in changes[-period:]]
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    async def _evaluate_market(
        self,
        market_info: CryptoMarketInfo,
        current_price: CryptoPrice,
        analyses: Dict[Timeframe, TimeframeAnalysis]
    ) -> Optional[MultiTimeframeSignal]:
        """Evaluate a specific market for trading opportunity"""
        
        if not analyses:
            return None
        
        # Calculate fair probability using ML volatility
        fair_prob = self.vol_forecaster.calculate_price_threshold_prob(
            symbol=market_info.symbol,
            current_price=float(current_price.price),
            threshold=float(market_info.threshold),
            time_to_expiry_hours=(market_info.expiry - datetime.now(timezone.utc)).total_seconds() / 3600
        )
        
        if fair_prob is None:
            return None
        
        # Adjust for direction
        if not market_info.is_above:
            fair_prob = Decimal("1") - fair_prob
        
        market_prob = market_info.market.implied_prob_mid
        
        # Calculate base edge
        if fair_prob > market_prob:
            side = Side.YES
            edge = fair_prob - market_prob
        else:
            side = Side.NO
            edge = market_prob - fair_prob
        
        # Apply timeframe multiplier
        adjusted_min_edge = self.min_edge * Decimal(str(market_info.timeframe.edge_multiplier))
        
        if edge < adjusted_min_edge:
            return None
        
        # Check timeframe confluence
        agreeing = []
        disagreeing = []
        
        for tf, analysis in analyses.items():
            tf_agrees = self._timeframe_agrees(analysis, side, market_info)
            if tf_agrees:
                agreeing.append(tf)
            else:
                disagreeing.append(tf)
        
        # Calculate confluence score
        total_tfs = len(analyses)
        confluence = len(agreeing) / total_tfs if total_tfs > 0 else 0
        
        if confluence < self.MIN_CONFLUENCE:
            return None
        
        # Calculate confidence based on confluence and volatility
        primary_analysis = analyses.get(market_info.timeframe)
        vol_confidence = 0.8 if primary_analysis and primary_analysis.vol_regime in [VolatilityRegime.LOW, VolatilityRegime.MEDIUM] else 0.6
        
        confidence = Decimal(str(confluence * 0.6 + vol_confidence * 0.4))
        
        # Determine time pressure
        minutes_to_expiry = (market_info.expiry - datetime.now(timezone.utc)).total_seconds() / 60
        if minutes_to_expiry < 5:
            time_pressure = "high"
        elif minutes_to_expiry < 15:
            time_pressure = "medium"
        else:
            time_pressure = "low"
        
        # Build reason
        reasons = [
            f"{market_info.symbol} @ ${current_price.price:,.0f}",
            f"vs ${market_info.threshold:,.0f} threshold",
            f"Edge: {float(edge)*100:.1f}%",
            f"Confluence: {len(agreeing)}/{total_tfs} TFs agree"
        ]
        
        return MultiTimeframeSignal(
            symbol=market_info.symbol,
            side=side,
            primary_timeframe=market_info.timeframe,
            model_probability=fair_prob,
            market_probability=market_prob,
            edge=edge,
            confidence=confidence,
            agreeing_timeframes=agreeing,
            disagreeing_timeframes=disagreeing,
            confluence_score=confluence,
            analyses=analyses,
            ticker=market_info.ticker,
            threshold=market_info.threshold,
            expiry=market_info.expiry,
            optimal_entry_window=any(a.optimal_entry for a in analyses.values()),
            time_pressure=time_pressure,
            reason=" | ".join(reasons)
        )
    
    def _timeframe_agrees(
        self,
        analysis: TimeframeAnalysis,
        side: Side,
        market_info: CryptoMarketInfo
    ) -> bool:
        """Check if timeframe analysis agrees with proposed side"""
        
        # For YES (price will be above threshold)
        if side == Side.YES:
            # Bullish signals support YES
            if analysis.trend in [TrendDirection.STRONG_UP, TrendDirection.UP]:
                return True
            if analysis.momentum_score > 0.2:
                return True
            if analysis.rsi > 50 and analysis.trend != TrendDirection.STRONG_DOWN:
                return True
            # Current price above threshold is supportive
            if analysis.current_price > float(market_info.threshold):
                return True
        
        # For NO (price will be below threshold)
        else:
            # Bearish signals support NO
            if analysis.trend in [TrendDirection.STRONG_DOWN, TrendDirection.DOWN]:
                return True
            if analysis.momentum_score < -0.2:
                return True
            if analysis.rsi < 50 and analysis.trend != TrendDirection.STRONG_UP:
                return True
            # Current price below threshold is supportive
            if analysis.current_price < float(market_info.threshold):
                return True
        
        return False
    
    async def run_continuous(
        self,
        callback,
        scan_interval: int = 30
    ):
        """
        Run continuous multi-timeframe analysis.
        
        Args:
            callback: Async function called with each signal
            scan_interval: Seconds between scans
        """
        self._running = True
        
        while self._running:
            try:
                # Refresh market data
                await self._discover_markets()
                
                # Analyze
                signals = await self.analyze()
                
                for signal in signals:
                    await callback(signal)
                
                await asyncio.sleep(scan_interval)
                
            except Exception as e:
                logger.error(f"Error in multi-timeframe analysis: {e}")
                await asyncio.sleep(10)
    
    def stop(self):
        """Stop continuous analysis"""
        self._running = False
