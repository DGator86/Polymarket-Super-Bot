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
        "closed": "false",  # Only open markets
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
        # Skip closed markets
        if market.get("closed") or market.get("closed") == "true":
            continue

        # Skip if market explicitly marked as inactive
        if market.get("active") == False or market.get("active") == "false":
            continue

        # Skip if no volume data
        volume = market.get("volume", 0) or market.get("volume24hr", 0)
        try:
            volume = float(volume) if volume else 0
        except (ValueError, TypeError):
            volume = 0

        if volume < min_volume:
            continue

        # Check expiry - skip expired markets
        end_date = market.get("endDate") or market.get("end_date_iso") or market.get("endDate")
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
                # If we can't parse the date, skip markets without clear expiry
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
    skipped = 0

    for market in markets:
        # Get condition ID - try multiple field names
        condition_id = (market.get("conditionId") or
                       market.get("condition_id") or
                       market.get("clobTokenIds") or
                       market.get("questionID"))

        if not condition_id:
            skipped += 1
            continue

        # Get token IDs - try multiple approaches
        tokens = market.get("tokens", [])
        yes_token = None
        no_token = None

        # Method 1: tokens array with outcome field
        if tokens and len(tokens) >= 2:
            for token in tokens:
                outcome = str(token.get("outcome", "")).upper()
                token_id = (token.get("token_id") or
                           token.get("tokenId") or
                           token.get("id"))

                if outcome == "YES" and token_id:
                    yes_token = token_id
                elif outcome == "NO" and token_id:
                    no_token = token_id

        # Method 2: Direct token ID fields
        if not yes_token or not no_token:
            yes_token = (market.get("yesTokenId") or
                        market.get("yes_token_id") or
                        (tokens[0].get("token_id") if len(tokens) > 0 else None) or
                        (tokens[0].get("tokenId") if len(tokens) > 0 else None))

            no_token = (market.get("noTokenId") or
                       market.get("no_token_id") or
                       (tokens[1].get("token_id") if len(tokens) > 1 else None) or
                       (tokens[1].get("tokenId") if len(tokens) > 1 else None))

        # Method 3: clobTokenIds array
        if not yes_token or not no_token:
            clob_tokens = market.get("clobTokenIds", [])
            if len(clob_tokens) >= 2:
                yes_token = clob_tokens[0]
                no_token = clob_tokens[1]

        if not yes_token or not no_token:
            skipped += 1
            continue

        # Convert token IDs to hex string format if they're integers
        if isinstance(yes_token, int):
            yes_token = hex(yes_token)
        elif isinstance(yes_token, str) and not yes_token.startswith('0x'):
            try:
                yes_token = hex(int(yes_token))
            except ValueError:
                pass

        if isinstance(no_token, int):
            no_token = hex(no_token)
        elif isinstance(no_token, str) and not no_token.startswith('0x'):
            try:
                no_token = hex(int(no_token))
            except ValueError:
                pass

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
        try:
            volume = float(volume) if volume else 0.0
        except (ValueError, TypeError):
            volume = 0.0

        # Ensure condition_id is a hex string if provided
        if condition_id:
            if isinstance(condition_id, int):
                condition_id = hex(condition_id)
            elif isinstance(condition_id, str) and not condition_id.startswith('0x'):
                # Already in correct format
                pass

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
            "volume": volume
        }

        bot_markets.append(bot_market)

    if skipped > 0:
        print(f"Skipped {skipped} markets due to missing token/condition data")

    return bot_markets

def main():
    print("Fetching Polymarket markets...")
    print("")

    # Fetch markets
    all_markets = fetch_polymarket_markets(limit=300)
    print(f"Fetched {len(all_markets)} total markets")

    # Filter for relevant markets
    print("Filtering for active markets in target categories...")
    filtered = filter_markets(all_markets, min_volume=1000, max_days_until_expiry=120)
    print(f"Found {len(filtered)} relevant markets after filtering")

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
