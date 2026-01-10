"""
Market scanner utility to discover and configure markets automatically.
"""
import requests
import json
import logging
import time
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("market_scanner")

class MarketScanner:
    """
    Scans Polymarket for active markets matching specific criteria.
    """
    
    BASE_URL = "https://gamma-api.polymarket.com"
    
    def __init__(self, min_volume: float = 1000.0, min_liquidity: float = 0.0):
        self.min_volume = min_volume
        self.min_liquidity = min_liquidity

    def scan_markets(self, keywords: List[str], limit: int = 10) -> List[Dict]:
        """
        Scan for markets matching keywords.
        """
        found_markets = []
        
        for keyword in keywords:
            logger.info(f"Scanning for '{keyword}'...")
            try:
                # Query events endpoint
                params = {
                    "limit": 50, # Fetch more to allow client-side filtering
                    "q": keyword,
                    "active": "true",
                    "closed": "false",
                    "archived": "false",
                    "order": "volume24hr",
                    "ascending": "false"
                }
                
                response = requests.get(f"{self.BASE_URL}/events", params=params)
                response.raise_for_status()
                events = response.json()
                
                keyword_lower = keyword.lower()
                
                for event in events:
                    # Client-side filtering: Ensure keyword is relevant
                    title = event.get("title", "").lower()
                    desc = event.get("description", "").lower()
                    slug = event.get("slug", "").lower()
                    
                    # Split keyword into terms and require at least one term match if it's a long phrase
                    # or require exact match for short ones. 
                    # Simpler: Check if the main concept is present.
                    if keyword_lower not in title and keyword_lower not in slug and keyword_lower not in desc:
                         # Try looser match for things like "Man City" -> "Manchester City"
                         # But generally we want strictness to avoid "Trump" spam when searching "Soccer"
                         continue

                    # Skip if we have enough
                    if len(found_markets) >= limit:
                        break
                        
                    # Process markets within event
                    event_markets = event.get("markets", [])
                    for market in event_markets:
                        
                        # Filter checks
                        if not self._is_valid_market(market):
                            continue
                            
                        # Extract token IDs
                        try:
                            token_ids = json.loads(market.get("clobTokenIds", "[]"))
                            if len(token_ids) != 2:
                                logger.warning(f"Skipping {market.get('slug')}: Expected 2 token IDs, got {len(token_ids)}")
                                continue
                                
                            yes_token_id = token_ids[0]
                            no_token_id = token_ids[1]
                        except Exception as e:
                            logger.warning(f"Error parsing token IDs for {market.get('slug')}: {e}")
                            continue

                        # Format for bot configuration
                        market_config = {
                            "slug": market.get("slug"),
                            "description": market.get("question"),
                            "strike": None, # Most sports markets don't have a simple strike price
                            "expiry_ts": self._parse_date(market.get("endDate")),
                            "yes_token_id": yes_token_id,
                            "no_token_id": no_token_id,
                            "tick_size": 0.01,
                            "min_size": 1.0,
                            "condition_id": market.get("conditionId"),
                            "volume": float(market.get("volume", 0))
                        }
                        
                        # Deduplication check
                        if not any(m["slug"] == market_config["slug"] for m in found_markets):
                            found_markets.append(market_config)
                            logger.info(f"Found: {market_config['slug']} (Vol: ${market_config['volume']:.2f})")
                
            except Exception as e:
                logger.error(f"Error scanning for {keyword}: {e}")
                
        return found_markets[:limit]

    def _is_valid_market(self, market: Dict) -> bool:
        """Check if market meets criteria."""
        # Must be active
        if not market.get("active"):
            return False
            
        # Check volume
        volume = float(market.get("volume", 0))
        if volume < self.min_volume:
            return False
            
        # Check if closed
        if market.get("closed"):
            return False
            
        return True

    def _parse_date(self, date_str: str) -> int:
        """Parse ISO date to timestamp."""
        try:
            # Handles 2024-05-19T15:00:00Z format
            dt = datetime.strptime(date_str.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z")
            return int(dt.timestamp())
        except:
            return int(time.time() + 86400 * 30) # Default to 30 days if parse fails

    def save_to_file(self, markets: List[Dict], filepath: str = "markets.json"):
        """Save discovered markets to JSON file."""
        output = {"markets": markets}
        
        with open(filepath, 'w') as f:
            json.dump(output, f, indent=2)
        logger.info(f"Saved {len(markets)} markets to {filepath}")

if __name__ == "__main__":
    scanner = MarketScanner(min_volume=5000) # Only liquid markets
    
    # Define keywords to scan for
    keywords = ["Premier League", "Champions League", "Bitcoin", "Ethereum", "Trump", "Biden"]
    
    print(f"Scanning for: {', '.join(keywords)}...")
    markets = scanner.scan_markets(keywords, limit=5)
    
    if markets:
        scanner.save_to_file(markets, "markets.json")
        print("\nSUCCESS! markets.json updated automatically.")
        print("You can now run 'python run.py'")
    else:
        print("\nNo matching markets found.")
