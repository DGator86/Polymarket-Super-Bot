#!/usr/bin/env python3
"""
Kalshi Arbitrage Bot

Identifies and executes arbitrage opportunities across prediction markets.

ARBITRAGE TYPES:
1. Internal Kalshi Arbitrage:
   - Probability arbitrage: YES + NO prices < $1.00 (guaranteed profit)
   - Spread trading: Bid > Ask in orderbook (instant profit)

2. Cross-Platform Arbitrage (Kalshi vs Polymarket):
   - Same event, different strike prices = overlapping coverage
   - Buy opposing positions for guaranteed $1.00 minimum payout
   - If cost < $1.00, profit is locked in

Author: Built for FINAL_GNOSIS Trading System
"""

import os
import sys
import json
import time
import asyncio
import logging
import base64
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple, Any
from enum import Enum
from decimal import Decimal, ROUND_DOWN

# Load environment variables
def load_dotenv():
    env_paths = [
        Path(__file__).parent / '.env',
        Path.cwd() / '.env',
        Path('/opt/kalshi-arbitrage-bot/.env'),
        Path('/opt/kalshi-latency-bot/.env'),
    ]
    for env_path in env_paths:
        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        os.environ.setdefault(key.strip(), value.strip())
            break

load_dotenv()

# Third-party imports
try:
    import aiohttp
    import requests
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import padding
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Install with: pip install aiohttp requests cryptography")
    sys.exit(1)

# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class Config:
    """Arbitrage bot configuration"""
    
    # Kalshi credentials
    KALSHI_API_KEY: str = field(default_factory=lambda: os.getenv("KALSHI_API_KEY", ""))
    KALSHI_PRIVATE_KEY_PATH: str = field(default_factory=lambda: os.getenv("KALSHI_PRIVATE_KEY_PATH", ""))
    KALSHI_API_BASE: str = field(default_factory=lambda: os.getenv("KALSHI_API_BASE", "https://api.elections.kalshi.com/trade-api/v2"))
    
    # Polymarket (no auth needed for reading)
    POLYMARKET_API_BASE: str = "https://clob.polymarket.com"
    POLYMARKET_GAMMA_API: str = "https://gamma-api.polymarket.com"
    
    # Arbitrage thresholds
    MIN_PROFIT_CENTS: int = 2  # Minimum profit per contract in cents
    MIN_PROFIT_PERCENT: float = 0.01  # 1% minimum profit margin
    MAX_POSITION_SIZE: int = 100  # Max contracts per arbitrage
    MIN_LIQUIDITY: int = 100  # Minimum volume/liquidity
    
    # Scanning
    SCAN_INTERVAL_SECONDS: int = 30
    MAX_MARKETS_PER_SCAN: int = 1000
    
    # Risk
    MAX_TOTAL_EXPOSURE: float = 500.0  # Max $ at risk
    
    # Logging
    LOG_LEVEL: str = "INFO"

# =============================================================================
# DATA MODELS
# =============================================================================

class ArbitrageType(Enum):
    PROBABILITY = "probability"  # YES + NO < $1
    SPREAD = "spread"  # Bid > Ask
    CROSS_PLATFORM = "cross_platform"  # Kalshi vs Polymarket

@dataclass
class ArbitrageOpportunity:
    """Represents an arbitrage opportunity"""
    arb_type: ArbitrageType
    platform: str
    ticker: str
    title: str
    
    # Prices
    leg1_side: str  # 'yes' or 'no' or 'up' or 'down'
    leg1_price: float
    leg1_platform: str
    
    leg2_side: str
    leg2_price: float
    leg2_platform: str
    
    # Profit calculation
    total_cost: float
    guaranteed_payout: float
    gross_profit: float
    net_profit: float  # After fees
    profit_percent: float
    
    # Metadata
    expiration: Optional[datetime] = None
    volume: int = 0
    liquidity: int = 0
    
    def __str__(self):
        return (
            f"{self.arb_type.value.upper()} | {self.ticker}\n"
            f"  {self.leg1_platform}: {self.leg1_side.upper()} @ ${self.leg1_price:.2f}\n"
            f"  {self.leg2_platform}: {self.leg2_side.upper()} @ ${self.leg2_price:.2f}\n"
            f"  Cost: ${self.total_cost:.2f} → Payout: ${self.guaranteed_payout:.2f}\n"
            f"  Profit: ${self.net_profit:.2f} ({self.profit_percent:.1%})"
        )

@dataclass
class KalshiMarket:
    """Kalshi market data"""
    ticker: str
    event_ticker: str
    title: str
    subtitle: str
    yes_bid: float
    yes_ask: float
    no_bid: float
    no_ask: float
    volume: int
    open_interest: int
    strike_price: Optional[float]
    expiration_time: datetime
    
    @property
    def total_ask(self) -> float:
        """Total cost to buy both YES and NO at ask prices"""
        return (self.yes_ask or 0) + (self.no_ask or 0)
    
    @property
    def total_bid(self) -> float:
        """Total value if selling both YES and NO at bid prices"""
        return (self.yes_bid or 0) + (self.no_bid or 0)
    
    @property
    def probability_arb_profit(self) -> float:
        """Profit if YES_ask + NO_ask < 1.00"""
        if self.yes_ask and self.no_ask:
            return 1.0 - self.total_ask
        return 0

@dataclass 
class PolymarketMarket:
    """Polymarket market data"""
    condition_id: str
    question_id: str
    title: str
    outcomes: List[Dict]
    tokens: List[Dict]
    expiration: Optional[datetime]
    volume: float
    liquidity: float
    
    @property
    def up_price(self) -> Optional[float]:
        """Price for UP/YES outcome"""
        for outcome in self.outcomes:
            if outcome.get('label', '').lower() in ['yes', 'up', 'higher']:
                return outcome.get('price')
        return None
    
    @property
    def down_price(self) -> Optional[float]:
        """Price for DOWN/NO outcome"""
        for outcome in self.outcomes:
            if outcome.get('label', '').lower() in ['no', 'down', 'lower']:
                return outcome.get('price')
        return None

# =============================================================================
# LOGGING
# =============================================================================

def setup_logging(config: Config) -> logging.Logger:
    logger = logging.getLogger("KalshiArbitrageBot")
    logger.setLevel(getattr(logging, config.LOG_LEVEL))
    
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S"
    ))
    logger.addHandler(console)
    
    return logger

# =============================================================================
# KALSHI CLIENT
# =============================================================================

class KalshiClient:
    """Kalshi API client with RSA-PSS authentication"""
    
    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self._session: Optional[aiohttp.ClientSession] = None
        self._private_key = None
        self._authenticated = False
    
    def _load_private_key(self):
        """Load RSA private key for signing"""
        key_path = self.config.KALSHI_PRIVATE_KEY_PATH
        if not key_path:
            return None
        
        try:
            if os.path.isfile(key_path):
                with open(key_path, 'rb') as f:
                    key_content = f.read()
            else:
                key_content = key_path.encode() if key_path.startswith('-----BEGIN') else None
                if not key_content:
                    return None
            
            return serialization.load_pem_private_key(key_content, password=None)
        except Exception as e:
            self.logger.error(f"Failed to load private key: {e}")
            return None
    
    def _sign_pss(self, message: str) -> str:
        """Sign message with RSA-PSS"""
        if not self._private_key:
            return ""
        
        signature = self._private_key.sign(
            message.encode(),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode()
    
    def _get_auth_headers(self, method: str, path: str) -> Dict[str, str]:
        """Generate authentication headers"""
        timestamp = str(int(time.time() * 1000))
        
        # Path must include /trade-api/v2 prefix for signing
        if not path.startswith('/trade-api/v2'):
            sign_path = '/trade-api/v2' + path
        else:
            sign_path = path
        
        message = timestamp + method + sign_path
        signature = self._sign_pss(message)
        
        return {
            "KALSHI-ACCESS-KEY": self.config.KALSHI_API_KEY,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json"
        }
    
    async def initialize(self):
        """Initialize client and authenticate"""
        self._session = aiohttp.ClientSession()
        self._private_key = self._load_private_key()
        
        if self._private_key and self.config.KALSHI_API_KEY:
            # Test authentication
            balance = await self.get_balance()
            if balance is not None:
                self._authenticated = True
                self.logger.info(f"Authenticated with Kalshi (balance: ${balance:.2f})")
            else:
                self.logger.warning("Authentication failed - running in read-only mode")
        else:
            self.logger.warning("No credentials - running in read-only mode")
    
    async def close(self):
        if self._session:
            await self._session.close()
    
    async def get_balance(self) -> Optional[float]:
        """Get account balance"""
        path = "/portfolio/balance"
        headers = self._get_auth_headers("GET", path)
        
        try:
            async with self._session.get(
                f"{self.config.KALSHI_API_BASE}{path}",
                headers=headers
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("balance", 0) / 100
        except Exception as e:
            self.logger.error(f"Failed to get balance: {e}")
        return None
    
    async def get_all_markets(self, limit: int = 200, series_filter: str = None) -> List[KalshiMarket]:
        """Fetch all open markets, optionally filtered by series"""
        all_markets = []
        cursor = None
        
        while len(all_markets) < limit:
            path = f"/markets?status=open&limit=200"
            if series_filter:
                path += f"&series_ticker={series_filter}"
            if cursor:
                path += f"&cursor={cursor}"
            
            headers = self._get_auth_headers("GET", path)
            
            try:
                async with self._session.get(
                    f"{self.config.KALSHI_API_BASE}{path}",
                    headers=headers
                ) as resp:
                    if resp.status != 200:
                        break
                    
                    data = await resp.json()
                    markets = data.get("markets", [])
                    
                    for m in markets:
                        try:
                            market = self._parse_market(m)
                            if market:
                                all_markets.append(market)
                        except Exception as e:
                            continue
                    
                    cursor = data.get("cursor")
                    if not cursor or not markets:
                        break
                        
            except Exception as e:
                self.logger.error(f"Error fetching markets: {e}")
                break
        
        return all_markets[:limit]
    
    async def get_crypto_markets(self) -> List[KalshiMarket]:
        """Fetch crypto-specific markets (BTC, ETH, SOL, XRP)"""
        crypto_series = ["KXBTCD", "KXETHD", "KXSOLD", "KXXRPD", "KXBTC", "KXETH", "KXSOLE", "KXXRP"]
        all_crypto = []
        
        for series in crypto_series:
            markets = await self.get_all_markets(limit=100, series_filter=series)
            all_crypto.extend(markets)
            await asyncio.sleep(0.1)  # Rate limit
        
        return all_crypto
    
    def _parse_market(self, m: dict) -> Optional[KalshiMarket]:
        """Parse market data from API response"""
        # Parse strike price
        strike = None
        subtitle = m.get("subtitle", "")
        ticker = m.get("ticker", "")
        
        if "$" in subtitle:
            try:
                price_str = subtitle.split("$")[1].replace(",", "").split()[0]
                price_str = ''.join(c for c in price_str if c.isdigit() or c == '.')
                if price_str:
                    strike = float(price_str)
            except:
                pass
        
        # Extract from ticker if needed
        if strike is None and ("-T" in ticker or "-B" in ticker):
            try:
                for part in ticker.split("-"):
                    if part.startswith("T") or part.startswith("B"):
                        strike = float(part[1:])
                        break
            except:
                pass
        
        # Expiration
        close_time = m.get("close_time") or m.get("expiration_time")
        if close_time:
            expiration = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
        else:
            expiration = datetime.now(timezone.utc) + timedelta(hours=1)
        
        return KalshiMarket(
            ticker=m["ticker"],
            event_ticker=m.get("event_ticker", ""),
            title=m.get("title", ""),
            subtitle=subtitle,
            yes_bid=(m.get("yes_bid") or 0) / 100,
            yes_ask=(m.get("yes_ask") or 0) / 100,
            no_bid=(m.get("no_bid") or 0) / 100,
            no_ask=(m.get("no_ask") or 0) / 100,
            volume=m.get("volume", 0),
            open_interest=m.get("open_interest", 0),
            strike_price=strike,
            expiration_time=expiration,
        )
    
    async def place_order(self, ticker: str, side: str, quantity: int, price: float) -> Dict:
        """Place a limit order"""
        if not self._authenticated:
            return {"success": False, "error": "Not authenticated"}
        
        path = "/portfolio/orders"
        headers = self._get_auth_headers("POST", path)
        
        order_data = {
            "ticker": ticker,
            "type": "limit",
            "action": "buy",
            "side": side.lower(),
            "count": quantity,
        }
        
        price_cents = int(price * 100)
        if side.lower() == "yes":
            order_data["yes_price"] = price_cents
        else:
            order_data["no_price"] = price_cents
        
        try:
            async with self._session.post(
                f"{self.config.KALSHI_API_BASE}{path}",
                headers=headers,
                json=order_data
            ) as resp:
                data = await resp.json()
                if resp.status in [200, 201]:
                    return {"success": True, "order": data.get("order", {})}
                else:
                    return {"success": False, "error": data}
        except Exception as e:
            return {"success": False, "error": str(e)}

# =============================================================================
# POLYMARKET CLIENT
# =============================================================================

class PolymarketClient:
    """Polymarket API client (read-only, no auth needed)"""
    
    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def initialize(self):
        self._session = aiohttp.ClientSession()
        self.logger.info("Polymarket client initialized (read-only)")
    
    async def close(self):
        if self._session:
            await self._session.close()
    
    async def search_markets(self, query: str = "bitcoin") -> List[Dict]:
        """Search for markets by query"""
        try:
            url = f"{self.config.POLYMARKET_GAMMA_API}/markets"
            params = {"closed": "false", "limit": 100}
            
            async with self._session.get(url, params=params) as resp:
                if resp.status == 200:
                    markets = await resp.json()
                    # Filter by query
                    query_lower = query.lower()
                    return [m for m in markets if query_lower in m.get("question", "").lower()]
        except Exception as e:
            self.logger.error(f"Polymarket search error: {e}")
        return []
    
    async def get_btc_hourly_markets(self) -> List[Dict]:
        """Get Bitcoin hourly price markets"""
        try:
            # Search for BTC hourly markets
            url = f"{self.config.POLYMARKET_GAMMA_API}/markets"
            params = {"closed": "false", "limit": 200}
            
            async with self._session.get(url, params=params) as resp:
                if resp.status == 200:
                    markets = await resp.json()
                    # Filter for BTC hourly
                    btc_markets = []
                    for m in markets:
                        question = m.get("question", "").lower()
                        if "bitcoin" in question and ("hour" in question or "1h" in question):
                            btc_markets.append(m)
                    return btc_markets
        except Exception as e:
            self.logger.error(f"Polymarket BTC fetch error: {e}")
        return []
    
    async def get_market_prices(self, token_id: str) -> Optional[Dict]:
        """Get current prices for a market token"""
        try:
            url = f"{self.config.POLYMARKET_API_BASE}/price"
            params = {"token_id": token_id}
            
            async with self._session.get(url, params=params) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception as e:
            self.logger.debug(f"Price fetch error: {e}")
        return None

# =============================================================================
# ARBITRAGE DETECTOR
# =============================================================================

class ArbitrageDetector:
    """Detects arbitrage opportunities across markets"""
    
    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        
        # Kalshi fee structure (approximate)
        self.fee_rate = 0.035  # ~3.5% for mid-priced contracts
    
    def calculate_fees(self, price: float, quantity: int = 1) -> float:
        """Calculate trading fees"""
        # Tiered fee based on price distance from 50%
        distance_from_mid = abs(price - 0.50)
        
        if distance_from_mid < 0.10:  # 40-60%
            rate = 0.035
        elif distance_from_mid < 0.20:  # 30-40, 60-70%
            rate = 0.030
        elif distance_from_mid < 0.30:  # 20-30, 70-80%
            rate = 0.025
        elif distance_from_mid < 0.40:  # 10-20, 80-90%
            rate = 0.020
        else:  # 0-10, 90-100%
            rate = 0.010
        
        return price * rate * quantity
    
    def find_probability_arbitrage(self, markets: List[KalshiMarket]) -> List[ArbitrageOpportunity]:
        """
        Find probability arbitrage: YES_ask + NO_ask < $1.00
        
        If both YES and NO can be bought for less than $1.00 combined,
        guaranteed profit since one MUST pay out $1.00.
        """
        opportunities = []
        
        for market in markets:
            # Skip if missing prices
            if not market.yes_ask or not market.no_ask:
                continue
            
            # Skip illiquid markets
            if market.volume < self.config.MIN_LIQUIDITY:
                continue
            
            total_cost = market.yes_ask + market.no_ask
            
            # Check for arbitrage
            if total_cost < 1.0:
                gross_profit = 1.0 - total_cost
                
                # Calculate fees for both legs
                fees = self.calculate_fees(market.yes_ask) + self.calculate_fees(market.no_ask)
                net_profit = gross_profit - fees
                
                # Check minimum profit threshold
                if net_profit >= self.config.MIN_PROFIT_CENTS / 100:
                    profit_percent = net_profit / total_cost
                    
                    if profit_percent >= self.config.MIN_PROFIT_PERCENT:
                        opp = ArbitrageOpportunity(
                            arb_type=ArbitrageType.PROBABILITY,
                            platform="kalshi",
                            ticker=market.ticker,
                            title=market.title,
                            leg1_side="yes",
                            leg1_price=market.yes_ask,
                            leg1_platform="kalshi",
                            leg2_side="no",
                            leg2_price=market.no_ask,
                            leg2_platform="kalshi",
                            total_cost=total_cost,
                            guaranteed_payout=1.0,
                            gross_profit=gross_profit,
                            net_profit=net_profit,
                            profit_percent=profit_percent,
                            expiration=market.expiration_time,
                            volume=market.volume,
                        )
                        opportunities.append(opp)
        
        return sorted(opportunities, key=lambda x: x.net_profit, reverse=True)
    
    def find_spread_arbitrage(self, markets: List[KalshiMarket]) -> List[ArbitrageOpportunity]:
        """
        Find spread arbitrage: Bid > Ask (instant profit)
        
        If someone is bidding MORE than the ask price, you can
        buy at ask and immediately sell at bid for profit.
        """
        opportunities = []
        
        for market in markets:
            # Check YES side: can buy at yes_ask, sell at yes_bid
            if market.yes_ask and market.yes_bid and market.yes_bid > market.yes_ask:
                gross_profit = market.yes_bid - market.yes_ask
                fees = self.calculate_fees(market.yes_ask) + self.calculate_fees(market.yes_bid)
                net_profit = gross_profit - fees
                
                if net_profit >= self.config.MIN_PROFIT_CENTS / 100:
                    opp = ArbitrageOpportunity(
                        arb_type=ArbitrageType.SPREAD,
                        platform="kalshi",
                        ticker=market.ticker,
                        title=f"{market.title} (YES spread)",
                        leg1_side="buy_yes",
                        leg1_price=market.yes_ask,
                        leg1_platform="kalshi",
                        leg2_side="sell_yes",
                        leg2_price=market.yes_bid,
                        leg2_platform="kalshi",
                        total_cost=market.yes_ask,
                        guaranteed_payout=market.yes_bid,
                        gross_profit=gross_profit,
                        net_profit=net_profit,
                        profit_percent=net_profit / market.yes_ask if market.yes_ask > 0 else 0,
                        volume=market.volume,
                    )
                    opportunities.append(opp)
            
            # Check NO side
            if market.no_ask and market.no_bid and market.no_bid > market.no_ask:
                gross_profit = market.no_bid - market.no_ask
                fees = self.calculate_fees(market.no_ask) + self.calculate_fees(market.no_bid)
                net_profit = gross_profit - fees
                
                if net_profit >= self.config.MIN_PROFIT_CENTS / 100:
                    opp = ArbitrageOpportunity(
                        arb_type=ArbitrageType.SPREAD,
                        platform="kalshi",
                        ticker=market.ticker,
                        title=f"{market.title} (NO spread)",
                        leg1_side="buy_no",
                        leg1_price=market.no_ask,
                        leg1_platform="kalshi",
                        leg2_side="sell_no",
                        leg2_price=market.no_bid,
                        leg2_platform="kalshi",
                        total_cost=market.no_ask,
                        guaranteed_payout=market.no_bid,
                        gross_profit=gross_profit,
                        net_profit=net_profit,
                        profit_percent=net_profit / market.no_ask if market.no_ask > 0 else 0,
                        volume=market.volume,
                    )
                    opportunities.append(opp)
        
        return sorted(opportunities, key=lambda x: x.net_profit, reverse=True)
    
    def find_cross_platform_arbitrage(
        self, 
        kalshi_markets: List[KalshiMarket],
        poly_markets: List[Dict]
    ) -> List[ArbitrageOpportunity]:
        """
        Find cross-platform arbitrage between Kalshi and Polymarket.
        
        Strategy: If both platforms have markets on the same event but
        different strike prices, we can create overlapping coverage:
        
        Scenario A (Poly Strike > Kalshi Strike):
          Buy Poly DOWN + Kalshi YES
          - Minimum payout: $1.00 (one always wins)
          - Middle zone: Both win = $2.00
          
        Scenario B (Poly Strike < Kalshi Strike):
          Buy Poly UP + Kalshi NO
          - Same logic
        """
        opportunities = []
        
        # Match markets by event type (BTC hourly, etc.)
        for poly in poly_markets:
            poly_question = poly.get("question", "").lower()
            
            # Extract Polymarket strike price
            poly_strike = self._extract_strike(poly_question)
            if not poly_strike:
                continue
            
            # Get Polymarket prices
            poly_outcomes = poly.get("outcomes", [])
            poly_up_price = None
            poly_down_price = None
            
            for outcome in poly_outcomes:
                label = outcome.get("label", "").lower()
                price = outcome.get("price")
                if label in ["up", "yes", "higher"] and price:
                    poly_up_price = float(price)
                elif label in ["down", "no", "lower"] and price:
                    poly_down_price = float(price)
            
            if not poly_up_price or not poly_down_price:
                continue
            
            # Find matching Kalshi markets
            for kalshi in kalshi_markets:
                if not kalshi.strike_price:
                    continue
                
                # Check if same asset type (BTC)
                if "btc" not in kalshi.ticker.lower() and "bitcoin" not in kalshi.title.lower():
                    continue
                
                kalshi_strike = kalshi.strike_price
                
                # Scenario A: Poly Strike > Kalshi Strike
                if poly_strike > kalshi_strike:
                    # Buy Poly DOWN + Kalshi YES
                    if poly_down_price and kalshi.yes_ask:
                        total_cost = poly_down_price + kalshi.yes_ask
                        if total_cost < 1.0:
                            gross_profit = 1.0 - total_cost
                            fees = self.calculate_fees(kalshi.yes_ask)  # Polymarket has different fees
                            net_profit = gross_profit - fees
                            
                            if net_profit >= self.config.MIN_PROFIT_CENTS / 100:
                                opp = ArbitrageOpportunity(
                                    arb_type=ArbitrageType.CROSS_PLATFORM,
                                    platform="kalshi+polymarket",
                                    ticker=kalshi.ticker,
                                    title=f"BTC Cross-Arb: Poly ${poly_strike:,.0f} vs Kalshi ${kalshi_strike:,.0f}",
                                    leg1_side="down",
                                    leg1_price=poly_down_price,
                                    leg1_platform="polymarket",
                                    leg2_side="yes",
                                    leg2_price=kalshi.yes_ask,
                                    leg2_platform="kalshi",
                                    total_cost=total_cost,
                                    guaranteed_payout=1.0,
                                    gross_profit=gross_profit,
                                    net_profit=net_profit,
                                    profit_percent=net_profit / total_cost,
                                    expiration=kalshi.expiration_time,
                                )
                                opportunities.append(opp)
                
                # Scenario B: Poly Strike < Kalshi Strike
                elif poly_strike < kalshi_strike:
                    # Buy Poly UP + Kalshi NO
                    if poly_up_price and kalshi.no_ask:
                        total_cost = poly_up_price + kalshi.no_ask
                        if total_cost < 1.0:
                            gross_profit = 1.0 - total_cost
                            fees = self.calculate_fees(kalshi.no_ask)
                            net_profit = gross_profit - fees
                            
                            if net_profit >= self.config.MIN_PROFIT_CENTS / 100:
                                opp = ArbitrageOpportunity(
                                    arb_type=ArbitrageType.CROSS_PLATFORM,
                                    platform="kalshi+polymarket",
                                    ticker=kalshi.ticker,
                                    title=f"BTC Cross-Arb: Poly ${poly_strike:,.0f} vs Kalshi ${kalshi_strike:,.0f}",
                                    leg1_side="up",
                                    leg1_price=poly_up_price,
                                    leg1_platform="polymarket",
                                    leg2_side="no",
                                    leg2_price=kalshi.no_ask,
                                    leg2_platform="kalshi",
                                    total_cost=total_cost,
                                    guaranteed_payout=1.0,
                                    gross_profit=gross_profit,
                                    net_profit=net_profit,
                                    profit_percent=net_profit / total_cost,
                                    expiration=kalshi.expiration_time,
                                )
                                opportunities.append(opp)
        
        return sorted(opportunities, key=lambda x: x.net_profit, reverse=True)
    
    def _extract_strike(self, text: str) -> Optional[float]:
        """Extract strike price from text"""
        import re
        
        # Look for dollar amounts
        patterns = [
            r'\$([0-9,]+(?:\.[0-9]+)?)',  # $95,000 or $95000.00
            r'([0-9,]+(?:\.[0-9]+)?)\s*(?:dollars|usd)',  # 95000 dollars
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1).replace(",", ""))
                except:
                    pass
        return None

# =============================================================================
# MAIN BOT
# =============================================================================

class KalshiArbitrageBot:
    """Main arbitrage bot orchestrator"""
    
    def __init__(self, config: Config = None):
        self.config = config or Config()
        self.logger = setup_logging(self.config)
        
        self.kalshi = KalshiClient(self.config, self.logger)
        self.polymarket = PolymarketClient(self.config, self.logger)
        self.detector = ArbitrageDetector(self.config, self.logger)
        
        self._running = False
    
    async def initialize(self):
        """Initialize all clients"""
        self.logger.info("=" * 60)
        self.logger.info("KALSHI ARBITRAGE BOT")
        self.logger.info("=" * 60)
        
        await self.kalshi.initialize()
        await self.polymarket.initialize()
    
    async def close(self):
        """Cleanup"""
        await self.kalshi.close()
        await self.polymarket.close()
    
    async def scan_once(self) -> Dict[str, List[ArbitrageOpportunity]]:
        """Perform a single scan for all arbitrage types"""
        results = {
            "probability": [],
            "spread": [],
            "cross_platform": [],
        }
        
        # Fetch Kalshi markets (general + crypto)
        self.logger.info("Fetching Kalshi markets...")
        kalshi_markets = await self.kalshi.get_all_markets(self.config.MAX_MARKETS_PER_SCAN)
        self.logger.info(f"Found {len(kalshi_markets)} general Kalshi markets")
        
        # Also get crypto markets specifically
        self.logger.info("Fetching Kalshi crypto markets...")
        crypto_markets = await self.kalshi.get_crypto_markets()
        self.logger.info(f"Found {len(crypto_markets)} crypto markets")
        
        # Combine and deduplicate
        seen_tickers = set(m.ticker for m in kalshi_markets)
        for cm in crypto_markets:
            if cm.ticker not in seen_tickers:
                kalshi_markets.append(cm)
                seen_tickers.add(cm.ticker)
        
        self.logger.info(f"Total unique markets: {len(kalshi_markets)}")
        
        # Find internal Kalshi arbitrage
        results["probability"] = self.detector.find_probability_arbitrage(kalshi_markets)
        results["spread"] = self.detector.find_spread_arbitrage(kalshi_markets)
        
        # Fetch Polymarket and find cross-platform arb
        self.logger.info("Fetching Polymarket markets...")
        poly_markets = await self.polymarket.get_btc_hourly_markets()
        self.logger.info(f"Found {len(poly_markets)} Polymarket BTC markets")
        
        if poly_markets:
            results["cross_platform"] = self.detector.find_cross_platform_arbitrage(
                kalshi_markets, poly_markets
            )
        
        return results
    
    async def run_continuous(self):
        """Run continuous scanning"""
        self._running = True
        scan_count = 0
        
        while self._running:
            scan_count += 1
            self.logger.info(f"\n{'='*60}")
            self.logger.info(f"SCAN #{scan_count}")
            self.logger.info(f"{'='*60}")
            
            try:
                results = await self.scan_once()
                
                # Report results
                total_opps = sum(len(v) for v in results.values())
                
                if total_opps > 0:
                    self.logger.info(f"\n🎯 FOUND {total_opps} ARBITRAGE OPPORTUNITIES!")
                    
                    for arb_type, opportunities in results.items():
                        if opportunities:
                            self.logger.info(f"\n--- {arb_type.upper()} ({len(opportunities)}) ---")
                            for opp in opportunities[:5]:  # Show top 5
                                self.logger.info(f"\n{opp}")
                else:
                    self.logger.info("No arbitrage opportunities found this scan")
                
            except Exception as e:
                self.logger.error(f"Scan error: {e}")
            
            # Wait before next scan
            self.logger.info(f"\nNext scan in {self.config.SCAN_INTERVAL_SECONDS} seconds...")
            await asyncio.sleep(self.config.SCAN_INTERVAL_SECONDS)
    
    def stop(self):
        self._running = False

# =============================================================================
# CLI
# =============================================================================

async def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Kalshi Arbitrage Bot")
    parser.add_argument("--scan-once", action="store_true", help="Run single scan and exit")
    parser.add_argument("--analyze", action="store_true", help="Show market analysis even without arb")
    parser.add_argument("--interval", type=int, default=30, help="Scan interval in seconds")
    parser.add_argument("--min-profit", type=float, default=0.02, help="Minimum profit in dollars")
    args = parser.parse_args()
    
    config = Config()
    config.SCAN_INTERVAL_SECONDS = args.interval
    config.MIN_PROFIT_CENTS = int(args.min_profit * 100)
    
    bot = KalshiArbitrageBot(config)
    
    try:
        await bot.initialize()
        
        if args.scan_once or args.analyze:
            results = await bot.scan_once()
            
            total_opps = sum(len(v) for v in results.values())
            print(f"\n{'='*60}")
            print(f"SCAN COMPLETE - Found {total_opps} opportunities")
            print(f"{'='*60}")
            
            for arb_type, opportunities in results.items():
                if opportunities:
                    print(f"\n--- {arb_type.upper()} ({len(opportunities)}) ---")
                    for opp in opportunities[:10]:
                        print(f"\n{opp}")
            
            # Show analysis even without arb opportunities
            if args.analyze or total_opps == 0:
                print(f"\n{'='*60}")
                print("MARKET ANALYSIS - Closest to Arbitrage")
                print(f"{'='*60}")
                
                # Get crypto markets specifically
                crypto_markets = await bot.kalshi.get_crypto_markets()
                all_markets = await bot.kalshi.get_all_markets(500)
                
                # Combine for analysis
                seen = set(m.ticker for m in all_markets)
                for cm in crypto_markets:
                    if cm.ticker not in seen:
                        all_markets.append(cm)
                
                # Find closest to probability arb (lowest YES_ask + NO_ask)
                analyzed = []
                for m in all_markets:
                    if m.yes_ask and m.no_ask and m.yes_ask > 0 and m.no_ask > 0:
                        total = m.yes_ask + m.no_ask
                        gap = total - 1.0  # Distance from arb
                        analyzed.append((m, total, gap))
                
                analyzed.sort(key=lambda x: x[1])  # Sort by total cost (lowest first)
                
                print("\n🔍 TOP 15 CLOSEST TO PROBABILITY ARBITRAGE:")
                print("-" * 70)
                for m, total, gap in analyzed[:15]:
                    status = "✓ ARB!" if total < 1.0 else f"Gap: {gap:.1%}"
                    print(f"  {m.ticker[:40]:40} | YES ${m.yes_ask:.2f} + NO ${m.no_ask:.2f} = ${total:.2f} | {status}")
                
                # Find tightest spreads (bid close to ask)
                print("\n🔍 TOP 10 TIGHTEST SPREADS (Potential MM Opportunities):")
                print("-" * 70)
                spread_analyzed = []
                for m in all_markets:
                    if m.yes_ask and m.yes_bid and m.yes_ask > 0 and m.yes_bid > 0:
                        spread = m.yes_ask - m.yes_bid
                        if spread > 0:
                            spread_analyzed.append((m, spread, "YES"))
                    if m.no_ask and m.no_bid and m.no_ask > 0 and m.no_bid > 0:
                        spread = m.no_ask - m.no_bid
                        if spread > 0:
                            spread_analyzed.append((m, spread, "NO"))
                
                spread_analyzed.sort(key=lambda x: x[1])
                for m, spread, side in spread_analyzed[:10]:
                    if side == "YES":
                        print(f"  {m.ticker[:35]:35} | {side} Bid ${m.yes_bid:.2f} Ask ${m.yes_ask:.2f} | Spread ${spread:.2f}")
                    else:
                        print(f"  {m.ticker[:35]:35} | {side} Bid ${m.no_bid:.2f} Ask ${m.no_ask:.2f} | Spread ${spread:.2f}")
                
                # Crypto markets specifically
                print("\n🪙 CRYPTO MARKET OVERVIEW (Hourly BTC/ETH/SOL/XRP):")
                print("-" * 70)
                crypto = [m for m in crypto_markets if m.yes_ask and m.no_ask and m.yes_ask > 0]
                crypto.sort(key=lambda x: x.expiration_time)
                for m in crypto[:25]:
                    total = m.yes_ask + m.no_ask
                    exp_str = m.expiration_time.strftime("%H:%M") if m.expiration_time else "N/A"
                    print(f"  {m.ticker[:40]:40} | Y ${m.yes_ask:.2f} N ${m.no_ask:.2f} = ${total:.2f} | Exp: {exp_str}")
                
        else:
            await bot.run_continuous()
            
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        await bot.close()

if __name__ == "__main__":
    asyncio.run(main())
