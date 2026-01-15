"""
FRED (Federal Reserve Economic Data) Connector

Provides access to economic indicators for probability modeling:
- CPI (inflation)
- Unemployment rate
- Fed Funds Rate
- GDP
- And 800,000+ other series

API Documentation: https://fred.stlouisfed.org/docs/api/fred/
"""

import aiohttp
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from config import config
from core.models import EconomicDataPoint

logger = logging.getLogger(__name__)


# Common FRED series IDs for prediction markets
SERIES = {
    # Inflation
    "CPI": "CPIAUCSL",              # Consumer Price Index for All Urban Consumers
    "CPI_CORE": "CPILFESL",         # CPI Less Food and Energy
    "PCE": "PCEPI",                 # Personal Consumption Expenditures Price Index
    
    # Labor Market
    "UNEMPLOYMENT": "UNRATE",        # Unemployment Rate
    "NONFARM_PAYROLLS": "PAYEMS",   # Total Nonfarm Payrolls
    "INITIAL_CLAIMS": "ICSA",       # Initial Jobless Claims (weekly)
    
    # Interest Rates
    "FED_FUNDS": "FEDFUNDS",        # Effective Federal Funds Rate
    "FED_FUNDS_TARGET_UPPER": "DFEDTARU",  # Fed Funds Target Upper
    "FED_FUNDS_TARGET_LOWER": "DFEDTARL",  # Fed Funds Target Lower
    "TREASURY_10Y": "DGS10",        # 10-Year Treasury Rate
    "TREASURY_2Y": "DGS2",          # 2-Year Treasury Rate
    
    # GDP & Growth
    "GDP": "GDP",                   # Gross Domestic Product
    "GDP_REAL": "GDPC1",            # Real GDP
    "GDP_GROWTH": "A191RL1Q225SBEA", # Real GDP Growth Rate
    
    # Other Macro
    "RETAIL_SALES": "RSAFS",        # Retail Sales
    "INDUSTRIAL_PROD": "INDPRO",    # Industrial Production Index
    "HOUSING_STARTS": "HOUST",      # Housing Starts
}


@dataclass
class FREDRelease:
    """Upcoming data release information"""
    release_id: int
    name: str
    release_date: datetime
    series_ids: List[str]


class FREDClient:
    """
    FRED API client for economic data.
    
    Usage:
        client = FREDClient(api_key)
        cpi = await client.get_latest("CPIAUCSL")
        print(f"CPI: {cpi.value}")
    """
    
    BASE_URL = "https://api.stlouisfed.org/fred"
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or config.data_sources.fred_api_key
        self.session: Optional[aiohttp.ClientSession] = None
        self._cache: Dict[str, EconomicDataPoint] = {}
        self._cache_ttl = 300  # 5 minutes
        self._cache_times: Dict[str, float] = {}
    
    async def connect(self):
        """Initialize HTTP session"""
        self.session = aiohttp.ClientSession()
        logger.info("FRED client connected")
    
    async def close(self):
        """Close HTTP session"""
        if self.session:
            await self.session.close()
    
    async def _request(self, endpoint: str, params: Dict = None) -> Dict:
        """Make API request"""
        if not self.session:
            await self.connect()
        
        url = f"{self.BASE_URL}/{endpoint}"
        params = params or {}
        params["api_key"] = self.api_key
        params["file_type"] = "json"
        
        async with self.session.get(url, params=params) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"FRED API error: {resp.status} - {text}")
            return await resp.json()
    
    async def get_series_observations(
        self,
        series_id: str,
        start_date: datetime = None,
        end_date: datetime = None,
        limit: int = 100,
        sort_order: str = "desc"
    ) -> List[EconomicDataPoint]:
        """
        Get observations for a series.
        
        Args:
            series_id: FRED series ID (e.g., "CPIAUCSL")
            start_date: Start of date range
            end_date: End of date range
            limit: Max observations to return
            sort_order: "asc" or "desc"
        
        Returns:
            List of EconomicDataPoint observations
        """
        params = {
            "series_id": series_id,
            "limit": limit,
            "sort_order": sort_order
        }
        
        if start_date:
            params["observation_start"] = start_date.strftime("%Y-%m-%d")
        if end_date:
            params["observation_end"] = end_date.strftime("%Y-%m-%d")
        
        data = await self._request("series/observations", params)
        
        observations = []
        for obs in data.get("observations", []):
            if obs.get("value") == ".":  # FRED uses "." for missing data
                continue
            
            try:
                observations.append(EconomicDataPoint(
                    series_id=series_id,
                    value=Decimal(obs["value"]),
                    date=datetime.strptime(obs["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc),
                    source="fred",
                    units=data.get("units", ""),
                    notes=""
                ))
            except (ValueError, KeyError) as e:
                logger.warning(f"Failed to parse observation: {e}")
        
        return observations
    
    async def get_latest(self, series_id: str, use_cache: bool = True) -> Optional[EconomicDataPoint]:
        """
        Get the most recent observation for a series.
        
        Args:
            series_id: FRED series ID
            use_cache: Whether to use cached value if available
        
        Returns:
            Most recent EconomicDataPoint or None
        """
        import time
        
        # Check cache
        if use_cache and series_id in self._cache:
            cache_age = time.time() - self._cache_times.get(series_id, 0)
            if cache_age < self._cache_ttl:
                return self._cache[series_id]
        
        observations = await self.get_series_observations(series_id, limit=1)
        
        if observations:
            self._cache[series_id] = observations[0]
            self._cache_times[series_id] = time.time()
            return observations[0]
        
        return None
    
    async def get_series_info(self, series_id: str) -> Dict[str, Any]:
        """Get metadata about a series"""
        data = await self._request("series", {"series_id": series_id})
        series_list = data.get("seriess", [])
        return series_list[0] if series_list else {}
    
    async def get_release_dates(
        self,
        release_id: int = None,
        include_release_dates_with_no_data: bool = False
    ) -> List[FREDRelease]:
        """
        Get upcoming release dates.
        
        Useful for knowing when new data will be published.
        
        Common release IDs:
        - 10: Employment Situation (jobs report)
        - 21: H.15 Selected Interest Rates
        - 53: Gross Domestic Product
        - 283: Consumer Price Index
        """
        params = {
            "include_release_dates_with_no_data": str(include_release_dates_with_no_data).lower()
        }
        if release_id:
            params["release_id"] = release_id
        
        data = await self._request("releases/dates", params)
        
        releases = []
        for r in data.get("release_dates", []):
            releases.append(FREDRelease(
                release_id=r.get("release_id", 0),
                name=r.get("release_name", ""),
                release_date=datetime.strptime(r["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc),
                series_ids=[]  # Would need additional call to get series
            ))
        
        return releases
    
    async def search_series(self, search_text: str, limit: int = 20) -> List[Dict]:
        """Search for series by keyword"""
        params = {
            "search_text": search_text,
            "limit": limit
        }
        data = await self._request("series/search", params)
        return data.get("seriess", [])
    
    # =========================================================================
    # CONVENIENCE METHODS FOR COMMON INDICATORS
    # =========================================================================
    
    async def get_cpi(self) -> Optional[EconomicDataPoint]:
        """Get latest CPI reading"""
        return await self.get_latest(SERIES["CPI"])
    
    async def get_unemployment_rate(self) -> Optional[EconomicDataPoint]:
        """Get latest unemployment rate"""
        return await self.get_latest(SERIES["UNEMPLOYMENT"])
    
    async def get_fed_funds_rate(self) -> Optional[EconomicDataPoint]:
        """Get latest effective fed funds rate"""
        return await self.get_latest(SERIES["FED_FUNDS"])
    
    async def get_fed_funds_target(self) -> tuple[Optional[Decimal], Optional[Decimal]]:
        """Get current fed funds target range (lower, upper)"""
        lower = await self.get_latest(SERIES["FED_FUNDS_TARGET_LOWER"])
        upper = await self.get_latest(SERIES["FED_FUNDS_TARGET_UPPER"])
        return (
            lower.value if lower else None,
            upper.value if upper else None
        )
    
    async def get_gdp_growth(self) -> Optional[EconomicDataPoint]:
        """Get latest real GDP growth rate"""
        return await self.get_latest(SERIES["GDP_GROWTH"])
    
    async def get_cpi_history(self, months: int = 12) -> List[EconomicDataPoint]:
        """Get CPI history for trend analysis"""
        start = datetime.now(timezone.utc) - timedelta(days=months * 31)
        return await self.get_series_observations(
            SERIES["CPI"],
            start_date=start,
            sort_order="asc"
        )
    
    async def calculate_yoy_change(self, series_id: str) -> Optional[Decimal]:
        """
        Calculate year-over-year percentage change.
        Useful for inflation calculations.
        """
        observations = await self.get_series_observations(series_id, limit=13)
        
        if len(observations) < 13:
            return None
        
        current = observations[0].value
        year_ago = observations[12].value
        
        if year_ago == 0:
            return None
        
        return ((current - year_ago) / year_ago) * 100


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

async def create_fred_client() -> FREDClient:
    """Factory function to create and connect a FRED client"""
    client = FREDClient()
    await client.connect()
    return client
