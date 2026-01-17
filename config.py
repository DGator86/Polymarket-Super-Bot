"""
Configuration and thresholds for the Kalshi Prediction Bot.
All tunable parameters in one place.
"""

import os
from dataclasses import dataclass
from decimal import Decimal
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class KalshiConfig:
    """Kalshi API configuration"""
    api_key: str = os.getenv("KALSHI_API_KEY", "")
    private_key_path: str = os.getenv("KALSHI_PRIVATE_KEY_PATH", "./kalshi_private_key.pem")
    # Production API (migrated to elections.kalshi.com as of 2025)
    base_url: str = "https://api.elections.kalshi.com/trade-api/v2"
    ws_url: str = "wss://api.elections.kalshi.com/trade-api/ws/v2"
    # Demo environment for testing
    demo_base_url: str = "https://demo-api.kalshi.co/trade-api/v2"
    demo_ws_url: str = "wss://demo-api.kalshi.co/trade-api/ws/v2"
    use_demo: bool = os.getenv("KALSHI_USE_DEMO", "false").lower() == "true"
    token_refresh_buffer_seconds: int = 60  # Refresh token 1 min before expiry


@dataclass(frozen=True)
class DataSourceConfig:
    """External data source API keys"""
    fred_api_key: str = os.getenv("FRED_API_KEY", "")
    bls_api_key: str = os.getenv("BLS_API_KEY", "")
    newsapi_key: str = os.getenv("NEWSAPI_KEY", "")
    coinbase_api_key: str = os.getenv("COINBASE_API_KEY", "")
    coinbase_api_secret: str = os.getenv("COINBASE_API_SECRET", "")


@dataclass(frozen=True)
class UniverseEngineConfig:
    """Pre-filter thresholds for market selection"""
    min_liquidity_usd: Decimal = Decimal("5")  # Minimum $ at best quote
    max_spread_pct: Decimal = Decimal("0.20")   # 10% max bid-ask spread
    min_time_to_expiry_hours: int = 1           # Avoid near-settlement markets
    max_markets_to_analyze: int = 50            # Cap expensive computation
    

@dataclass(frozen=True)
class ProbabilityEngineConfig:
    """Model probability computation settings"""
    min_edge_pct: Decimal = Decimal("0.03")     # 5% minimum edge after fees
    confidence_threshold: Decimal = Decimal("0.70")  # 70% model confidence required
    kalshi_fee_pct: Decimal = Decimal("0.01")   # 1% fee assumption (varies)
    

@dataclass(frozen=True)
class RiskConfig:
    """Position sizing and risk limits"""
    kelly_fraction: Decimal = Decimal("0.25")   # 25% Kelly for conservatism
    max_position_pct: Decimal = Decimal("0.10") # 10% of account per market
    max_correlated_exposure_pct: Decimal = Decimal("0.25")  # 25% in correlated bets
    max_daily_loss_pct: Decimal = Decimal("0.05")  # 5% daily loss circuit breaker
    min_bet_size: int = 1                       # Minimum contracts per trade
    max_bet_size: int = 100                     # Maximum contracts per trade


@dataclass(frozen=True)
class ExecutionConfig:
    """Order execution settings"""
    use_limit_orders_only: bool = True          # Never use market orders
    order_timeout_seconds: int = 30             # Cancel unfilled orders after
    max_slippage_pct: Decimal = Decimal("0.02") # 2% max acceptable slippage
    retry_attempts: int = 3                     # Retries on transient failures
    retry_delay_seconds: float = 0.5            # Delay between retries


@dataclass(frozen=True)
class LatencyArbConfig:
    """Latency arbitrage strategy settings"""
    enabled: bool = True
    min_price_divergence_pct: Decimal = Decimal("0.02")  # 2% min divergence
    max_position_hold_seconds: int = 60         # Exit if not converging
    stale_quote_threshold_ms: int = 500         # Quote older than this = opportunity
    crypto_symbols: tuple = ("BTC-USD", "ETH-USD")


@dataclass(frozen=True)
class CrossPlatformArbConfig:
    """Cross-platform arbitrage settings"""
    enabled: bool = False  # Requires Polymarket access
    min_arb_profit_pct: Decimal = Decimal("0.01")  # 1% minimum after fees
    max_execution_lag_ms: int = 2000            # Both legs must fill within


@dataclass(frozen=True)
class LoggingConfig:
    """Logging and monitoring settings"""
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    log_file: str = "bot.log"
    log_trades: bool = True
    log_signals: bool = True
    metrics_interval_seconds: int = 60


@dataclass(frozen=True)
class AlertsConfig:
    """Telegram and Discord alert settings"""
    # Telegram (create bot via @BotFather)
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
    
    # Discord (create webhook in channel settings)
    discord_webhook_url: str = os.getenv("DISCORD_WEBHOOK_URL", "")
    
    # Alert preferences
    alert_on_signals: bool = True
    alert_on_trades: bool = True
    alert_on_fills: bool = True
    alert_on_errors: bool = True
    alert_on_circuit_breaker: bool = True
    send_daily_summary: bool = True
    daily_summary_hour: int = 17  # 5 PM UTC


@dataclass(frozen=True)
class DatabaseConfig:
    """Historical database settings"""
    path: str = os.getenv("DATABASE_PATH", "./data/trades.db")
    backup_enabled: bool = True
    backup_interval_hours: int = 24
    retention_days: int = 365  # Keep data for 1 year
    export_path: str = "./data/exports"


@dataclass(frozen=True)
class MLVolatilityConfig:
    """Machine learning volatility forecasting settings"""
    enabled: bool = True
    max_observations: int = 10080  # 7 days of minute data
    min_observations: int = 60     # Minimum for calculations
    
    # GARCH parameters
    garch_omega: float = 0.00001
    garch_alpha: float = 0.1       # Shock coefficient
    garch_beta: float = 0.85       # Persistence coefficient
    
    # Regime thresholds (annualized volatility)
    regime_low_threshold: float = 0.20
    regime_medium_threshold: float = 0.60
    regime_high_threshold: float = 1.00
    
    # Adaptive Kelly adjustments
    kelly_regime_low_mult: float = 1.2
    kelly_regime_medium_mult: float = 1.0
    kelly_regime_high_mult: float = 0.6
    kelly_regime_extreme_mult: float = 0.3


@dataclass(frozen=True)
class MultiTimeframeConfig:
    """Multi-timeframe analysis settings"""
    enabled: bool = True
    
    # Timeframes to analyze
    analyze_5min: bool = True
    analyze_15min: bool = True
    analyze_1hour: bool = True
    analyze_4hour: bool = True
    
    # Confluence requirements
    min_confluence_score: float = 0.5  # At least 50% of TFs must agree
    
    # Edge multipliers by timeframe (shorter TF needs more edge)
    edge_mult_5min: float = 1.5
    edge_mult_15min: float = 1.0
    edge_mult_1hour: float = 0.8
    edge_mult_4hour: float = 0.7
    
    # Scan interval
    scan_interval_seconds: int = 30


# Assembled configuration
@dataclass(frozen=True)
class BotConfig:
    kalshi: KalshiConfig = KalshiConfig()
    data_sources: DataSourceConfig = DataSourceConfig()
    universe: UniverseEngineConfig = UniverseEngineConfig()
    probability: ProbabilityEngineConfig = ProbabilityEngineConfig()
    risk: RiskConfig = RiskConfig()
    execution: ExecutionConfig = ExecutionConfig()
    latency_arb: LatencyArbConfig = LatencyArbConfig()
    cross_platform_arb: CrossPlatformArbConfig = CrossPlatformArbConfig()
    logging: LoggingConfig = LoggingConfig()
    alerts: AlertsConfig = AlertsConfig()
    database: DatabaseConfig = DatabaseConfig()
    ml_volatility: MLVolatilityConfig = MLVolatilityConfig()
    multi_timeframe: MultiTimeframeConfig = MultiTimeframeConfig()


# Global config instance
config = BotConfig()
