"""
NOAA / National Weather Service API Connector

Provides weather forecasts and observations for weather-related prediction markets:
- Temperature highs/lows
- Precipitation probability
- Severe weather alerts
- Historical observations

API Documentation: https://www.weather.gov/documentation/services-web-api
"""

import aiohttp
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from core.models import WeatherForecast

logger = logging.getLogger(__name__)


# Major US city coordinates for common weather markets
LOCATIONS = {
    "NYC": (40.7128, -74.0060),
    "LA": (34.0522, -118.2437),
    "CHICAGO": (41.8781, -87.6298),
    "HOUSTON": (29.7604, -95.3698),
    "PHOENIX": (33.4484, -112.0740),
    "PHILADELPHIA": (39.9526, -75.1652),
    "SAN_ANTONIO": (29.4241, -98.4936),
    "SAN_DIEGO": (32.7157, -117.1611),
    "DALLAS": (32.7767, -96.7970),
    "DENVER": (39.7392, -104.9903),
    "MIAMI": (25.7617, -80.1918),
    "SEATTLE": (47.6062, -122.3321),
    "BOSTON": (42.3601, -71.0589),
    "ATLANTA": (33.7490, -84.3880),
    "DETROIT": (42.3314, -83.0458),
    "DC": (38.9072, -77.0369),
}


@dataclass
class WeatherAlert:
    """Active weather alert"""
    id: str
    event: str  # e.g., "Winter Storm Warning"
    severity: str  # "Minor", "Moderate", "Severe", "Extreme"
    certainty: str  # "Observed", "Likely", "Possible", "Unlikely"
    headline: str
    description: str
    onset: datetime
    expires: datetime
    affected_zones: List[str]


@dataclass
class DailyForecast:
    """Single day forecast"""
    date: datetime
    name: str  # e.g., "Monday" or "Monday Night"
    temperature: int
    temperature_unit: str  # "F" or "C"
    is_daytime: bool
    precipitation_chance: Optional[int]  # Percentage
    wind_speed: str
    wind_direction: str
    short_forecast: str
    detailed_forecast: str


class NOAAClient:
    """
    NOAA/NWS API client for weather data.
    
    No API key required - public API with rate limiting.
    
    Usage:
        client = NOAAClient()
        forecast = await client.get_forecast(40.7128, -74.0060)  # NYC
        print(f"High: {forecast[0].temperature}°F")
    """
    
    BASE_URL = "https://api.weather.gov"
    USER_AGENT = "KalshiPredictionBot (contact@example.com)"
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self._point_cache: Dict[tuple, Dict] = {}  # Cache grid points
    
    async def connect(self):
        """Initialize HTTP session"""
        headers = {"User-Agent": self.USER_AGENT, "Accept": "application/geo+json"}
        self.session = aiohttp.ClientSession(headers=headers)
        logger.info("NOAA client connected")
    
    async def close(self):
        """Close HTTP session"""
        if self.session:
            await self.session.close()
    
    async def _request(self, url: str) -> Dict:
        """Make API request"""
        if not self.session:
            await self.connect()
        
        async with self.session.get(url) as resp:
            if resp.status == 503:
                raise Exception("NOAA API temporarily unavailable")
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"NOAA API error: {resp.status} - {text}")
            return await resp.json()
    
    async def _get_point_metadata(self, lat: float, lon: float) -> Dict:
        """
        Get grid point metadata for a location.
        Required before fetching forecasts.
        """
        cache_key = (round(lat, 4), round(lon, 4))
        
        if cache_key in self._point_cache:
            return self._point_cache[cache_key]
        
        url = f"{self.BASE_URL}/points/{lat:.4f},{lon:.4f}"
        data = await self._request(url)
        
        self._point_cache[cache_key] = data
        return data
    
    async def get_forecast(self, lat: float, lon: float) -> List[DailyForecast]:
        """
        Get 7-day forecast for a location.
        
        Args:
            lat: Latitude
            lon: Longitude
        
        Returns:
            List of DailyForecast objects (typically 14 periods: day/night for 7 days)
        """
        point_data = await self._get_point_metadata(lat, lon)
        forecast_url = point_data["properties"]["forecast"]
        
        forecast_data = await self._request(forecast_url)
        
        forecasts = []
        for period in forecast_data["properties"]["periods"]:
            # Parse precipitation chance from detailed forecast if not provided
            precip_chance = period.get("probabilityOfPrecipitation", {}).get("value")
            
            forecasts.append(DailyForecast(
                date=datetime.fromisoformat(period["startTime"]),
                name=period["name"],
                temperature=period["temperature"],
                temperature_unit=period["temperatureUnit"],
                is_daytime=period["isDaytime"],
                precipitation_chance=precip_chance,
                wind_speed=period["windSpeed"],
                wind_direction=period["windDirection"],
                short_forecast=period["shortForecast"],
                detailed_forecast=period["detailedForecast"]
            ))
        
        return forecasts
    
    async def get_hourly_forecast(self, lat: float, lon: float) -> List[Dict]:
        """
        Get hourly forecast for next 156 hours.
        More granular than daily forecast.
        """
        point_data = await self._get_point_metadata(lat, lon)
        hourly_url = point_data["properties"]["forecastHourly"]
        
        hourly_data = await self._request(hourly_url)
        return hourly_data["properties"]["periods"]
    
    async def get_current_observation(self, lat: float, lon: float) -> Dict:
        """
        Get current weather observation from nearest station.
        
        Returns actual measured conditions, not forecast.
        """
        point_data = await self._get_point_metadata(lat, lon)
        stations_url = point_data["properties"]["observationStations"]
        
        stations_data = await self._request(stations_url)
        
        if not stations_data["features"]:
            raise Exception("No observation stations found for location")
        
        # Get observation from nearest station
        station_id = stations_data["features"][0]["properties"]["stationIdentifier"]
        obs_url = f"{self.BASE_URL}/stations/{station_id}/observations/latest"
        
        obs_data = await self._request(obs_url)
        return obs_data["properties"]
    
    async def get_alerts(
        self,
        lat: float = None,
        lon: float = None,
        state: str = None,
        zone: str = None,
        active: bool = True
    ) -> List[WeatherAlert]:
        """
        Get weather alerts for a location or area.
        
        Args:
            lat, lon: Specific coordinates
            state: Two-letter state code (e.g., "NY")
            zone: NWS zone ID
            active: Only return active alerts
        
        Returns:
            List of WeatherAlert objects
        """
        params = []
        if active:
            params.append("status=actual")
        if lat is not None and lon is not None:
            params.append(f"point={lat:.4f},{lon:.4f}")
        if state:
            params.append(f"area={state}")
        if zone:
            params.append(f"zone={zone}")
        
        url = f"{self.BASE_URL}/alerts"
        if params:
            url += "?" + "&".join(params)
        
        data = await self._request(url)
        
        alerts = []
        for feature in data.get("features", []):
            props = feature["properties"]
            
            alerts.append(WeatherAlert(
                id=props.get("id", ""),
                event=props.get("event", ""),
                severity=props.get("severity", ""),
                certainty=props.get("certainty", ""),
                headline=props.get("headline", ""),
                description=props.get("description", ""),
                onset=datetime.fromisoformat(props["onset"]) if props.get("onset") else datetime.now(timezone.utc),
                expires=datetime.fromisoformat(props["expires"]) if props.get("expires") else datetime.now(timezone.utc),
                affected_zones=props.get("affectedZones", [])
            ))
        
        return alerts
    
    # =========================================================================
    # CONVENIENCE METHODS
    # =========================================================================
    
    async def get_forecast_for_city(self, city: str) -> List[DailyForecast]:
        """Get forecast using predefined city coordinates"""
        city = city.upper().replace(" ", "_")
        if city not in LOCATIONS:
            raise ValueError(f"Unknown city: {city}. Available: {list(LOCATIONS.keys())}")
        
        lat, lon = LOCATIONS[city]
        return await self.get_forecast(lat, lon)
    
    async def get_high_temperature(self, lat: float, lon: float, days_ahead: int = 0) -> Optional[int]:
        """
        Get forecasted high temperature for a specific day.
        
        Args:
            lat, lon: Location coordinates
            days_ahead: 0 = today, 1 = tomorrow, etc.
        
        Returns:
            High temperature in Fahrenheit
        """
        forecasts = await self.get_forecast(lat, lon)
        
        # Find daytime forecasts (they have the high temps)
        daytime_forecasts = [f for f in forecasts if f.is_daytime]
        
        if days_ahead < len(daytime_forecasts):
            return daytime_forecasts[days_ahead].temperature
        
        return None
    
    async def get_low_temperature(self, lat: float, lon: float, days_ahead: int = 0) -> Optional[int]:
        """Get forecasted low temperature for a specific day"""
        forecasts = await self.get_forecast(lat, lon)
        
        # Find nighttime forecasts (they have the low temps)
        nighttime_forecasts = [f for f in forecasts if not f.is_daytime]
        
        if days_ahead < len(nighttime_forecasts):
            return nighttime_forecasts[days_ahead].temperature
        
        return None
    
    async def will_it_rain(self, lat: float, lon: float, days_ahead: int = 0) -> tuple[bool, int]:
        """
        Check precipitation probability.
        
        Returns:
            (likely_to_rain: bool, probability: int)
        """
        forecasts = await self.get_forecast(lat, lon)
        
        # Get both day and night periods for the target day
        target_periods = forecasts[days_ahead * 2: (days_ahead + 1) * 2]
        
        max_precip = 0
        for period in target_periods:
            if period.precipitation_chance:
                max_precip = max(max_precip, period.precipitation_chance)
        
        return (max_precip >= 50, max_precip)
    
    async def to_normalized_forecast(self, lat: float, lon: float) -> WeatherForecast:
        """Convert to normalized WeatherForecast model"""
        forecasts = await self.get_forecast(lat, lon)
        
        if not forecasts:
            raise Exception("No forecast data available")
        
        today = forecasts[0]
        precip = today.precipitation_chance or 0
        
        # Parse wind speed (format: "5 to 10 mph" or "10 mph")
        wind_str = today.wind_speed
        wind_speed = None
        if wind_str:
            import re
            nums = re.findall(r'\d+', wind_str)
            if nums:
                wind_speed = float(nums[-1])  # Take the higher number
        
        return WeatherForecast(
            latitude=lat,
            longitude=lon,
            forecast_time=today.date,
            temperature_f=float(today.temperature) if today.temperature_unit == "F" else None,
            precipitation_chance=float(precip) / 100,
            wind_speed_mph=wind_speed,
            conditions=today.short_forecast,
            raw_data={"periods": [f.__dict__ for f in forecasts[:4]]}
        )


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

async def create_noaa_client() -> NOAAClient:
    """Factory function to create and connect a NOAA client"""
    client = NOAAClient()
    await client.connect()
    return client
