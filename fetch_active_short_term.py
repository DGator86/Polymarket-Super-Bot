#!/usr/bin/env python3
"""
Fetch high-activity, short-term Polymarket markets.
Focus on markets expiring within the next 7-30 days.
"""

import requests
import json
from datetime import datetime, timedelta
import sys

def fetch_polymarket_markets(limit=300):
    """Fetch markets from Polymarket API."""
    url = "https://gamma-api.polymarket.com/markets"

    params = {
        "limit": limit,
        "closed": "false",
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

def filter_short_term_markets(markets, min_volume=5000, min_days=1, max_days=30):
    """Filter for short-term, high-activity markets that are accepting orders."""
    filtered = []
    now = datetime.now().timestamp()
    min_expiry = now + (min_days * 24 * 60 * 60)
    max_expiry = now + (max_days * 24 * 60 * 60)

    for market in markets:
        # CRITICAL: Must be accepting orders NOW
        if not market.get("acceptingOrders"):
            continue

        # Must have order book enabled
        if not market.get("enableOrderBook"):
            continue

        # Skip negRisk markets (they use different trading mechanism)
        if market.get("negRisk"):
            continue

        # Check volume
        volume = market.get("volume24hr", 0) or market.get("volume", 0)
        try:
            volume = float(volume) if volume else 0
        except (ValueError, TypeError):
            volume = 0

        if volume < min_volume:
            continue

        # Check expiry
        end_date = market.get("endDate") or market.get("end_date_iso")
        if not end_date:
            continue

        try:
            if isinstance(end_date, str):
                expiry = datetime.fromisoformat(end_date.replace('Z', '+00:00')).timestamp()
            else:
                expiry = end_date

            # Only markets expiring in 1-30 days
            if expiry < min_expiry or expiry > max_expiry:
                continue

            days_until = (expiry - now) / 86400
            market['_days_until_expiry'] = days_until
            filtered.append(market)

        except Exception as e:
            continue

    return filtered

def convert_to_bot_format(markets):
    """Convert to bot format with hex token IDs."""
    bot_markets = []

    for market in markets:
        # Get condition ID
        condition_id = (market.get("conditionId") or
                       market.get("condition_id") or
                       market.get("questionID"))

        if not condition_id:
            continue

        # Get token IDs
        tokens = market.get("tokens", [])
        yes_token = None
        no_token = None

        # Try multiple methods to get token IDs
        if tokens and len(tokens) >= 2:
            for token in tokens:
                outcome = str(token.get("outcome", "")).upper()
                token_id = token.get("token_id") or token.get("tokenId") or token.get("id")

                if outcome == "YES" and token_id:
                    yes_token = token_id
                elif outcome == "NO" and token_id:
                    no_token = token_id

        # Fallback to clobTokenIds
        if not yes_token or not no_token:
            clob_tokens = market.get("clobTokenIds", [])

            # Parse JSON string if needed
            if isinstance(clob_tokens, str):
                try:
                    clob_tokens = json.loads(clob_tokens)
                except (json.JSONDecodeError, ValueError):
                    clob_tokens = []

            if clob_tokens and len(clob_tokens) >= 2:
                yes_token = clob_tokens[0]
                no_token = clob_tokens[1]

        if not yes_token or not no_token:
            continue

        # Validate token IDs are proper hex strings or integers
        if isinstance(yes_token, str):
            if not (yes_token.startswith('0x') or yes_token.isdigit()):
                continue
        if isinstance(no_token, str):
            if not (no_token.startswith('0x') or no_token.isdigit()):
                continue

        # Convert to hex if needed
        if isinstance(yes_token, int):
            yes_token = hex(yes_token)
        elif isinstance(yes_token, str) and yes_token.isdigit():
            yes_token = hex(int(yes_token))

        if isinstance(no_token, int):
            no_token = hex(no_token)
        elif isinstance(no_token, str) and no_token.isdigit():
            no_token = hex(int(no_token))

        if isinstance(condition_id, int):
            condition_id = hex(condition_id)
        elif isinstance(condition_id, str) and condition_id.isdigit():
            condition_id = hex(int(condition_id))

        # Get expiry
        end_date = market.get("endDate") or market.get("end_date_iso")
        expiry_ts = None
        if end_date:
            try:
                if isinstance(end_date, str):
                    expiry_ts = int(datetime.fromisoformat(end_date.replace('Z', '+00:00')).timestamp())
                else:
                    expiry_ts = int(end_date)
            except:
                pass

        # Get volume
        volume = market.get("volume24hr", 0) or market.get("volume", 0) or 0
        try:
            volume = float(volume)
        except:
            volume = 0.0

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

    return bot_markets

def main():
    print("Fetching short-term, high-activity markets...")
    print("")

    # Fetch markets
    all_markets = fetch_polymarket_markets(limit=300)
    print(f"Fetched {len(all_markets)} total markets")

    # Filter for short-term markets (1-30 days) - lower volume to find ANY markets
    print("Filtering for markets expiring in 1-30 days with orderbooks...")
    filtered = filter_short_term_markets(all_markets, min_volume=100, min_days=1, max_days=30)
    print(f"Found {len(filtered)} short-term markets")

    if not filtered:
        print("ERROR: No short-term markets found!")
        print("Try lowering min_volume or increasing max_days")
        sys.exit(1)

    # Sort by 24h volume
    filtered.sort(key=lambda x: float(x.get("volume24hr", 0) or 0), reverse=True)

    # Convert to bot format
    bot_markets = convert_to_bot_format(filtered)
    print(f"Converted {len(bot_markets)} markets to bot format")

    # Take top 50
    bot_markets = bot_markets[:50]

    # Save
    output = {"markets": bot_markets}
    with open("markets.json", "w") as f:
        json.dump(output, f, indent=2)

    print("")
    print(f"✓ Saved {len(bot_markets)} markets to markets.json")
    print("")
    print("Top 15 markets by 24h volume:")
    print("-" * 100)

    for i, market in enumerate(bot_markets[:15], 1):
        desc = market["description"][:70]
        volume = market["volume"]

        if market["expiry_ts"]:
            days = (market["expiry_ts"] - datetime.now().timestamp()) / 86400
            expiry_str = f"{int(days)}d"
        else:
            expiry_str = "N/A"

        print(f"{i:2d}. ${volume:>10,.0f} | {expiry_str:>4s} | {desc}")

    print("-" * 100)

if __name__ == "__main__":
    main()
