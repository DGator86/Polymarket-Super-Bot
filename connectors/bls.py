"""
BLS (Bureau of Labor Statistics) API Connector

Provides access to detailed labor and inflation data:
- CPI sub-components (food, energy, housing, etc.)
- Employment data by sector
- Producer Price Index (PPI)
- Import/Export prices

More granular than FRED for specific CPI component predictions.

API Documentation: https://www.bls.gov/developers/
"""

import aiohttp
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from config import config
from core.models import EconomicDataPoint

logger = logging.getLogger(__name__)


# BLS Series IDs for CPI sub-components
# Full list: https://www.bls.gov/cpi/data.htm
CPI_SERIES = {
    # All Items
    "CPI_ALL": "CUSR0000SA0",           # All items, seasonally adjusted
    "CPI_ALL_NSA": "CUUR0000SA0",       # All items, not seasonally adjusted
    
    # Core CPI (excludes food and energy)
    "CPI_CORE": "CUSR0000SA0L1E",       # All items less food and energy
    
    # Food
    "CPI_FOOD": "CUSR0000SAF1",          # Food
    "CPI_FOOD_HOME": "CUSR0000SAF11",    # Food at home
    "CPI_FOOD_AWAY": "CUSR0000SEFV",     # Food away from home
    "CPI_MEATS": "CUSR0000SAF112",       # Meats, poultry, fish, and eggs
    "CPI_DAIRY": "CUSR0000SEFJ",         # Dairy and related products
    "CPI_FRUITS_VEG": "CUSR0000SAF113",  # Fruits and vegetables
    "CPI_CEREALS": "CUSR0000SAF111",     # Cereals and bakery products
    
    # Energy
    "CPI_ENERGY": "CUSR0000SA0E",        # Energy
    "CPI_GASOLINE": "CUSR0000SETB01",    # Gasoline (all types)
    "CPI_ELECTRICITY": "CUSR0000SEHF01", # Electricity
    "CPI_NATURAL_GAS": "CUSR0000SEHF02", # Utility (piped) gas service
    "CPI_FUEL_OIL": "CUSR0000SEHE01",    # Fuel oil
    
    # Housing
    "CPI_SHELTER": "CUSR0000SAH1",       # Shelter
    "CPI_RENT": "CUSR0000SEHA",          # Rent of primary residence
    "CPI_OER": "CUSR0000SEHC",           # Owners' equivalent rent
    "CPI_LODGING": "CUSR0000SEHB",       # Lodging away from home
    
    # Transportation
    "CPI_TRANSPORTATION": "CUSR0000SAT",  # Transportation
    "CPI_NEW_VEHICLES": "CUSR0000SETA01", # New vehicles
    "CPI_USED_VEHICLES": "CUSR0000SETA02", # Used cars and trucks
    "CPI_AIRLINE_FARES": "CUSR0000SETG01", # Airline fares
    "CPI_AUTO_INSURANCE": "CUSR0000SETE",  # Motor vehicle insurance
    
    # Medical Care
    "CPI_MEDICAL": "CUSR0000SAM",         # Medical care
    "CPI_MEDICAL_SERVICES": "CUSR0000SAM2", # Medical care services
    "CPI_HOSPITAL": "CUSR0000SEMD",       # Hospital services
    "CPI_PRESCRIPTION": "CUSR0000SEMF01", # Prescription drugs
    
    # Education & Communication
    "CPI_EDUCATION": "CUSR0000SAE1",      # Education
    "CPI_TUITION": "CUSR0000SEEB",        # Tuition, other school fees
    "CPI_COMMUNICATION": "CUSR0000SAE2",   # Communication
    
    # Recreation
    "CPI_RECREATION": "CUSR0000SAR",       # Recreation
    
    # Apparel
    "CPI_APPAREL": "CUSR0000SAA",          # Apparel
}

# Employment series
EMPLOYMENT_SERIES = {
    "UNEMPLOYMENT_RATE": "LNS14000000",     # Unemployment rate
    "LABOR_FORCE_PART": "LNS11300000",      # Labor force participation rate
    "NONFARM_PAYROLLS": "CES0000000001",    # Total nonfarm payrolls
    "PRIVATE_PAYROLLS": "CES0500000001",    # Total private payrolls
    "AVG_HOURLY_EARNINGS": "CES0500000003", # Average hourly earnings
    "AVG_WEEKLY_HOURS": "CES0500000002",    # Average weekly hours
}

# Producer Price Index
PPI_SERIES = {
    "PPI_ALL": "WPUFD4",                    # Final demand
    "PPI_GOODS": "WPUFD41",                 # Final demand goods
    "PPI_SERVICES": "WPUFD42",              # Final demand services
    "PPI_CORE": "WPUFD49104",               # Final demand less foods and energy
}


@dataclass
class BLSDataPoint:
    """Single observation from BLS"""
    series_id: str
    value: Decimal
    year: int
    period: str  # e.g., "M01" for January
    period_name: str  # e.g., "January"
    latest: bool
    footnotes: List[str]
    
    @property
    def date(self) -> datetime:
        """Convert period to datetime"""
        month = int(self.period[1:]) if self.period.startswith("M") else 1
        return datetime(self.year, month, 1, tzinfo=timezone.utc)


@dataclass
class BLSSeriesInfo:
    """Metadata about a BLS series"""
    series_id: str
    title: str
    survey_name: str
    seasonality: str  # "S" = seasonal, "U" = not seasonal
    area_name: str
    item_name: str


class BLSClient:
    """
    BLS API client for detailed economic data.
    
    Provides more granular CPI components than FRED.
    Useful for predicting specific inflation sub-categories.
    
    Usage:
        client = BLSClient(api_key)
        cpi_food = await client.get_series("CUSR0000SAF1")
        print(f"Food CPI: {cpi_food[0].value}")
    """
    
    BASE_URL = "https://api.bls.gov/publicAPI/v2"
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or config.data_sources.bls_api_key
        self.session: Optional[aiohttp.ClientSession] = None
        self._cache: Dict[str, List[BLSDataPoint]] = {}
        self._cache_ttl = 3600  # 1 hour (BLS data updates monthly)
        self._cache_times: Dict[str, float] = {}
    
    async def connect(self):
        """Initialize HTTP session"""
        self.session = aiohttp.ClientSession()
        logger.info("BLS client connected")
    
    async def close(self):
        """Close HTTP session"""
        if self.session:
            await self.session.close()
    
    async def _request(self, endpoint: str, payload: Dict) -> Dict:
        """Make API request"""
        if not self.session:
            await self.connect()
        
        url = f"{self.BASE_URL}/{endpoint}"
        
        # Add API key if available (increases rate limits)
        if self.api_key:
            payload["registrationkey"] = self.api_key
        
        async with self.session.post(url, json=payload) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"BLS API error: {resp.status} - {text}")
            
            data = await resp.json()
            
            if data.get("status") != "REQUEST_SUCCEEDED":
                raise Exception(f"BLS API error: {data.get('message', 'Unknown error')}")
            
            return data
    
    async def get_series(
        self,
        series_ids: List[str],
        start_year: int = None,
        end_year: int = None,
        calculations: bool = True,
        annual_average: bool = False
    ) -> Dict[str, List[BLSDataPoint]]:
        """
        Get data for one or more series.
        
        Args:
            series_ids: List of BLS series IDs
            start_year: Start year for data
            end_year: End year for data
            calculations: Include percent changes
            annual_average: Include annual averages
        
        Returns:
            Dict mapping series_id to list of BLSDataPoint
        """
        import time
        
        # Check cache
        cached_results = {}
        uncached_series = []
        
        for series_id in series_ids:
            if series_id in self._cache:
                cache_age = time.time() - self._cache_times.get(series_id, 0)
                if cache_age < self._cache_ttl:
                    cached_results[series_id] = self._cache[series_id]
                    continue
            uncached_series.append(series_id)
        
        if not uncached_series:
            return cached_results
        
        # Default to last 3 years
        current_year = datetime.now().year
        if not end_year:
            end_year = current_year
        if not start_year:
            start_year = current_year - 3
        
        payload = {
            "seriesid": uncached_series,
            "startyear": str(start_year),
            "endyear": str(end_year),
            "calculations": calculations,
            "annualaverage": annual_average
        }
        
        data = await self._request("timeseries/data/", payload)
        
        results = cached_results.copy()
        
        for series in data.get("Results", {}).get("series", []):
            series_id = series["seriesID"]
            points = []
            
            for item in series.get("data", []):
                try:
                    points.append(BLSDataPoint(
                        series_id=series_id,
                        value=Decimal(item["value"]),
                        year=int(item["year"]),
                        period=item["period"],
                        period_name=item["periodName"],
                        latest=item.get("latest", "false") == "true",
                        footnotes=[f.get("text", "") for f in item.get("footnotes", [])]
                    ))
                except (ValueError, KeyError) as e:
                    logger.warning(f"Failed to parse BLS data point: {e}")
            
            # Sort by date descending
            points.sort(key=lambda x: (x.year, x.period), reverse=True)
            
            results[series_id] = points
            self._cache[series_id] = points
            self._cache_times[series_id] = time.time()
        
        return results
    
    async def get_latest(self, series_id: str) -> Optional[BLSDataPoint]:
        """Get the most recent observation for a series"""
        data = await self.get_series([series_id])
        points = data.get(series_id, [])
        return points[0] if points else None
    
    async def get_series_info(self, series_id: str) -> Optional[BLSSeriesInfo]:
        """Get metadata about a series"""
        # Note: BLS doesn't have a direct series info endpoint
        # This would require scraping or hardcoded mappings
        return None
    
    # =========================================================================
    # CPI SUB-COMPONENT METHODS
    # =========================================================================
    
    async def get_cpi_all(self) -> Optional[BLSDataPoint]:
        """Get all items CPI"""
        return await self.get_latest(CPI_SERIES["CPI_ALL"])
    
    async def get_cpi_core(self) -> Optional[BLSDataPoint]:
        """Get core CPI (less food and energy)"""
        return await self.get_latest(CPI_SERIES["CPI_CORE"])
    
    async def get_cpi_food(self) -> Optional[BLSDataPoint]:
        """Get food CPI"""
        return await self.get_latest(CPI_SERIES["CPI_FOOD"])
    
    async def get_cpi_energy(self) -> Optional[BLSDataPoint]:
        """Get energy CPI"""
        return await self.get_latest(CPI_SERIES["CPI_ENERGY"])
    
    async def get_cpi_shelter(self) -> Optional[BLSDataPoint]:
        """Get shelter/housing CPI"""
        return await self.get_latest(CPI_SERIES["CPI_SHELTER"])
    
    async def get_cpi_gasoline(self) -> Optional[BLSDataPoint]:
        """Get gasoline CPI"""
        return await self.get_latest(CPI_SERIES["CPI_GASOLINE"])
    
    async def get_cpi_medical(self) -> Optional[BLSDataPoint]:
        """Get medical care CPI"""
        return await self.get_latest(CPI_SERIES["CPI_MEDICAL"])
    
    async def get_cpi_transportation(self) -> Optional[BLSDataPoint]:
        """Get transportation CPI"""
        return await self.get_latest(CPI_SERIES["CPI_TRANSPORTATION"])
    
    async def get_all_cpi_components(self) -> Dict[str, BLSDataPoint]:
        """
        Get all major CPI components in one call.
        Useful for comprehensive inflation analysis.
        """
        series_ids = [
            CPI_SERIES["CPI_ALL"],
            CPI_SERIES["CPI_CORE"],
            CPI_SERIES["CPI_FOOD"],
            CPI_SERIES["CPI_ENERGY"],
            CPI_SERIES["CPI_SHELTER"],
            CPI_SERIES["CPI_TRANSPORTATION"],
            CPI_SERIES["CPI_MEDICAL"],
            CPI_SERIES["CPI_APPAREL"],
            CPI_SERIES["CPI_RECREATION"],
            CPI_SERIES["CPI_EDUCATION"],
        ]
        
        data = await self.get_series(series_ids)
        
        result = {}
        for series_id, points in data.items():
            if points:
                # Find human-readable name
                for name, sid in CPI_SERIES.items():
                    if sid == series_id:
                        result[name] = points[0]
                        break
        
        return result
    
    # =========================================================================
    # YEAR-OVER-YEAR CALCULATIONS
    # =========================================================================
    
    async def calculate_yoy_change(self, series_id: str) -> Optional[Decimal]:
        """
        Calculate year-over-year percentage change.
        
        Returns:
            YoY change as percentage (e.g., 3.5 for 3.5%)
        """
        data = await self.get_series([series_id])
        points = data.get(series_id, [])
        
        if len(points) < 13:
            return None
        
        current = points[0]
        
        # Find same month last year
        target_year = current.year - 1
        target_period = current.period
        
        year_ago = None
        for point in points:
            if point.year == target_year and point.period == target_period:
                year_ago = point
                break
        
        if not year_ago or year_ago.value == 0:
            return None
        
        return ((current.value - year_ago.value) / year_ago.value) * 100
    
    async def get_cpi_yoy_breakdown(self) -> Dict[str, Decimal]:
        """
        Get YoY changes for all major CPI components.
        
        Returns:
            Dict mapping component name to YoY change percentage
        """
        components = {
            "ALL": CPI_SERIES["CPI_ALL"],
            "CORE": CPI_SERIES["CPI_CORE"],
            "FOOD": CPI_SERIES["CPI_FOOD"],
            "ENERGY": CPI_SERIES["CPI_ENERGY"],
            "SHELTER": CPI_SERIES["CPI_SHELTER"],
            "TRANSPORTATION": CPI_SERIES["CPI_TRANSPORTATION"],
            "MEDICAL": CPI_SERIES["CPI_MEDICAL"],
        }
        
        result = {}
        for name, series_id in components.items():
            yoy = await self.calculate_yoy_change(series_id)
            if yoy is not None:
                result[name] = yoy
        
        return result
    
    # =========================================================================
    # EMPLOYMENT DATA
    # =========================================================================
    
    async def get_unemployment_rate(self) -> Optional[BLSDataPoint]:
        """Get unemployment rate"""
        return await self.get_latest(EMPLOYMENT_SERIES["UNEMPLOYMENT_RATE"])
    
    async def get_nonfarm_payrolls(self) -> Optional[BLSDataPoint]:
        """Get total nonfarm payrolls (in thousands)"""
        return await self.get_latest(EMPLOYMENT_SERIES["NONFARM_PAYROLLS"])
    
    async def get_labor_force_participation(self) -> Optional[BLSDataPoint]:
        """Get labor force participation rate"""
        return await self.get_latest(EMPLOYMENT_SERIES["LABOR_FORCE_PART"])
    
    async def get_avg_hourly_earnings(self) -> Optional[BLSDataPoint]:
        """Get average hourly earnings"""
        return await self.get_latest(EMPLOYMENT_SERIES["AVG_HOURLY_EARNINGS"])
    
    # =========================================================================
    # PRODUCER PRICE INDEX
    # =========================================================================
    
    async def get_ppi(self) -> Optional[BLSDataPoint]:
        """Get Producer Price Index (final demand)"""
        return await self.get_latest(PPI_SERIES["PPI_ALL"])
    
    async def get_ppi_core(self) -> Optional[BLSDataPoint]:
        """Get core PPI (less foods and energy)"""
        return await self.get_latest(PPI_SERIES["PPI_CORE"])
    
    # =========================================================================
    # CONVERSION TO STANDARD FORMAT
    # =========================================================================
    
    def to_economic_data_point(self, bls_point: BLSDataPoint) -> EconomicDataPoint:
        """Convert BLS data point to standard EconomicDataPoint format"""
        return EconomicDataPoint(
            series_id=bls_point.series_id,
            value=bls_point.value,
            date=bls_point.date,
            source="bls",
            units="index" if "CU" in bls_point.series_id else "percent",
            notes="; ".join(bls_point.footnotes) if bls_point.footnotes else ""
        )


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

async def create_bls_client() -> BLSClient:
    """Factory function to create and connect a BLS client"""
    client = BLSClient()
    await client.connect()
    return client
