"""
Configuration loader and validator.
"""
from dataclasses import dataclass
from typing import Optional
import os
from dotenv import load_dotenv


@dataclass
class StrategyConfig:
    """Strategy parameters."""
    maker_half_spread: float
    taker_edge_threshold: float
    quote_refresh_ttl_ms: int
    inventory_skew_factor: float
    sigma_floor: float
    use_normal_cdf: bool


@dataclass
class RiskConfig:
    """Risk limits."""
    max_notional_per_market: float
    max_inventory_per_token: float
    max_open_orders_total: int
    max_orders_per_min: int
    max_daily_loss: float
    max_taker_slippage: float
    feed_stale_ms: int


@dataclass
class ExecutionConfig:
    """Execution parameters."""
    dry_run: bool
    private_key: str
    api_key: Optional[str]
    api_secret: Optional[str]
    api_passphrase: Optional[str]
    chain_id: int
    clob_url: str


@dataclass
class Config:
    """Master configuration."""
    strategy: StrategyConfig
    risk: RiskConfig
    execution: ExecutionConfig
    log_level: str
    log_file: Optional[str]
    db_path: str
    market_registry_path: str
    loop_interval_ms: int
    kill_switch: bool


def load_config() -> Config:
    """
    Load and validate configuration from environment variables.

    Raises:
        ValueError: If required configuration is missing or invalid
    """
    load_dotenv()

    def get_env(key: str, required: bool = True, default: Optional[str] = None) -> Optional[str]:
        value = os.getenv(key, default)
        if required and value is None:
            raise ValueError(f"Missing required environment variable: {key}")
        return value

    def get_float(key: str, required: bool = True, default: Optional[float] = None) -> float:
        value = get_env(key, required, str(default) if default is not None else None)
        if value is None:
            return default
        try:
            return float(value)
        except ValueError:
            raise ValueError(f"Invalid float value for {key}: {value}")

    def get_int(key: str, required: bool = True, default: Optional[int] = None) -> int:
        value = get_env(key, required, str(default) if default is not None else None)
        if value is None:
            return default
        try:
            return int(value)
        except ValueError:
            raise ValueError(f"Invalid int value for {key}: {value}")

    def get_bool(key: str, default: bool = False) -> bool:
        value = get_env(key, False, str(int(default)))
        return value.lower() in ('1', 'true', 'yes', 'on')

    # Strategy config
    strategy = StrategyConfig(
        maker_half_spread=get_float("MAKER_HALF_SPREAD", default=0.01),
        taker_edge_threshold=get_float("TAKER_EDGE_THRESHOLD", default=0.03),
        quote_refresh_ttl_ms=get_int("QUOTE_REFRESH_TTL_MS", default=3000),
        inventory_skew_factor=get_float("INVENTORY_SKEW_FACTOR", default=0.0001),
        sigma_floor=get_float("SIGMA_FLOOR", default=0.001),
        use_normal_cdf=get_bool("USE_NORMAL_CDF", default=True)
    )

    # Risk config
    risk = RiskConfig(
        max_notional_per_market=get_float("MAX_NOTIONAL_PER_MARKET", default=100.0),
        max_inventory_per_token=get_float("MAX_INVENTORY_PER_TOKEN", default=500.0),
        max_open_orders_total=get_int("MAX_OPEN_ORDERS_TOTAL", default=10),
        max_orders_per_min=get_int("MAX_ORDERS_PER_MIN", default=30),
        max_daily_loss=get_float("MAX_DAILY_LOSS", default=50.0),
        max_taker_slippage=get_float("MAX_TAKER_SLIPPAGE", default=0.02),
        feed_stale_ms=get_int("FEED_STALE_MS", default=2000)
    )

    # Execution config
    dry_run = get_bool("DRY_RUN", default=True)
    execution = ExecutionConfig(
        dry_run=dry_run,
        private_key=get_env("PRIVATE_KEY", required=not dry_run, default=""),
        api_key=get_env("API_KEY", required=False),
        api_secret=get_env("API_SECRET", required=False),
        api_passphrase=get_env("API_PASSPHRASE", required=False),
        chain_id=get_int("CHAIN_ID", default=137),
        clob_url=get_env("CLOB_URL", default="https://clob.polymarket.com")
    )

    # General config
    kill_switch = get_bool("KILL_SWITCH", default=False)

    return Config(
        strategy=strategy,
        risk=risk,
        execution=execution,
        log_level=get_env("LOG_LEVEL", default="INFO"),
        log_file=get_env("LOG_FILE", required=False),
        db_path=get_env("DB_PATH", default="bot_state.db"),
        market_registry_path=get_env("MARKET_REGISTRY_PATH", default="markets.json"),
        loop_interval_ms=get_int("LOOP_INTERVAL_MS", default=500),
        kill_switch=kill_switch
    )
