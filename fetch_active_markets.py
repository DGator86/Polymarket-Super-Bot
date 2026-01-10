#!/usr/bin/env python3
"""
Fetch active, high-volume Polymarket markets across multiple categories.
"""

import requests
import json
from datetime import datetime, timedelta
import sys

# Categories to fetch
CATEGORIES = [
    "sports",
    "crypto",
    "politics",
    "football",  # Soccer
    "nfl",
    "nba",
    "ncaa",
    "bundesliga",
]

def fetch_polymarket_markets(limit=200):
    """Fetch markets from Polymarket API."""
    url = "https://gamma-api.polymarket.com/markets"

    params = {
        "limit": limit,
        "active": "true",
        "_sort": "volume24hr",
        "_order": "desc"
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching markets: {e}")
        return []

def filter_markets(markets, min_volume=10000, max_days_until_expiry=60):
    """Filter markets by volume and expiry."""
    filtered = []
    now = datetime.now().timestamp()
    max_expiry = now + (max_days_until_expiry * 24 * 60 * 60)

    for market in markets:
        # Skip if no volume data
        volume = market.get("volume", 0) or market.get("volume24hr", 0)
        if volume < min_volume:
            continue

        # Check expiry
        end_date = market.get("endDate") or market.get("end_date_iso")
        if end_date:
            try:
                # Try parsing ISO format
                if isinstance(end_date, str):
                    expiry = datetime.fromisoformat(end_date.replace('Z', '+00:00')).timestamp()
                else:
                    expiry = end_date

                # Skip if expired or too far in future
                if expiry < now or expiry > max_expiry:
                    continue
            except:
                pass

        # Check if market matches our categories
        tags = [tag.lower() for tag in market.get("tags", [])]
        description = market.get("description", "").lower()
        question = market.get("question", "").lower()

        is_relevant = False

        # Check for sports
        sports_keywords = ["nfl", "nba", "ncaa", "football", "basketball", "soccer",
                          "premier league", "bundesliga", "sports", "game", "match",
                          "win", "championship", "playoff"]

        # Check for crypto
        crypto_keywords = ["bitcoin", "btc", "ethereum", "eth", "crypto", "solana",
                          "sol", "price", "usdc", "usdt"]

        # Check for politics
        politics_keywords = ["trump", "biden", "election", "president", "congress",
                           "senate", "governor", "vote", "poll", "democrat", "republican"]

        all_keywords = sports_keywords + crypto_keywords + politics_keywords

        for keyword in all_keywords:
            if (keyword in description or keyword in question or
                keyword in " ".join(tags)):
                is_relevant = True
                break

        if is_relevant:
            filtered.append(market)

    return filtered

def convert_to_bot_format(markets):
    """Convert Polymarket API format to bot's markets.json format."""
    bot_markets = []

    for market in markets:
        # Get condition ID and tokens
        condition_id = market.get("conditionId") or market.get("condition_id")
        if not condition_id:
            continue

        # Get token IDs
        tokens = market.get("tokens", [])
        if len(tokens) < 2:
            continue

        # Find YES and NO tokens
        yes_token = None
        no_token = None

        for token in tokens:
            outcome = token.get("outcome", "").upper()
            if outcome == "YES":
                yes_token = token.get("token_id") or token.get("tokenId")
            elif outcome == "NO":
                no_token = token.get("token_id") or token.get("tokenId")

        if not yes_token or not no_token:
            continue

        # Get expiry timestamp
        end_date = market.get("endDate") or market.get("end_date_iso")
        expiry_ts = None

        if end_date:
            try:
                if isinstance(end_date, str):
                    expiry_ts = int(datetime.fromisoformat(end_date.replace('Z', '+00:00')).timestamp())
                else:
                    expiry_ts = int(end_date)
            except:
                expiry_ts = None

        # Get volume
        volume = market.get("volume", 0) or market.get("volume24hr", 0) or 0

        bot_market = {
            "slug": market.get("slug", ""),
            "description": market.get("question") or market.get("description", ""),
            "strike": None,
            "expiry_ts": expiry_ts,
            "yes_token_id": yes_token,
            "no_token_id": no_token,
            "tick_size": 0.01,
            "min_size": 1.0,
            "condition_id": condition_id,
            "volume": float(volume)
        }

        bot_markets.append(bot_market)

    return bot_markets

def main():
    print("Fetching Polymarket markets...")
    print("")

    # Fetch markets
    all_markets = fetch_polymarket_markets(limit=300)
    print(f"Fetched {len(all_markets)} total markets")

    # Filter for relevant markets
    print("Filtering for high-volume, short-term markets in target categories...")
    filtered = filter_markets(all_markets, min_volume=5000, max_days_until_expiry=90)
    print(f"Found {len(filtered)} relevant markets")

    if not filtered:
        print("ERROR: No markets found matching criteria!")
        print("Try lowering min_volume or increasing max_days_until_expiry")
        sys.exit(1)

    # Convert to bot format
    bot_markets = convert_to_bot_format(filtered)
    print(f"Converted {len(bot_markets)} markets to bot format")

    # Sort by volume descending
    bot_markets.sort(key=lambda x: x["volume"], reverse=True)

    # Take top 50 markets
    bot_markets = bot_markets[:50]

    # Save to markets.json
    output = {"markets": bot_markets}

    with open("markets.json", "w") as f:
        json.dump(output, f, indent=2)

    print("")
    print(f"✓ Saved {len(bot_markets)} markets to markets.json")
    print("")
    print("Top 10 markets by volume:")
    print("-" * 80)

    for i, market in enumerate(bot_markets[:10], 1):
        desc = market["description"][:60] + "..." if len(market["description"]) > 60 else market["description"]
        volume = market["volume"]

        # Calculate days until expiry
        if market["expiry_ts"]:
            days = (market["expiry_ts"] - datetime.now().timestamp()) / 86400
            expiry_str = f"{int(days)}d"
        else:
            expiry_str = "N/A"

        print(f"{i:2d}. ${volume:,.0f} | {expiry_str:>4s} | {desc}")

    print("-" * 80)
    print("")
    print("Next step: Copy markets.json to your VPS and restart the bot")

if __name__ == "__main__":
    main()
