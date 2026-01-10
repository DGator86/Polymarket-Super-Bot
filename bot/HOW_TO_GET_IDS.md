# How to Get Real Token IDs

Polymarket's API requires specific "Token IDs" to trade YES/NO shares. These IDs are unique to each outcome.

Since new markets are created constantly, you need to fetch the IDs for the specific markets you want to trade.

## Option 1: Use the Helper Script (Recommended)

I have created a script that fetches the IDs for you if you know the market's "slug" (the part of the URL after `market/`).

1. **Find the market URL:**
   Go to [polymarket.com](https://polymarket.com) and find the market you want to trade.
   
   Example URL: `https://polymarket.com/market/premier-league-winner-2024-25`
   The slug is: `premier-league-winner-2024-25`

2. **Run the script:**
   ```bash
   python fetch_market_ids.py premier-league-winner-2024-25
   ```

3. **Copy the IDs:**
   The script will print:
   ```
   YES Token ID: 210938...
   NO Token ID:  498123...
   ```
   Copy these into your `markets.json`.

## Option 2: Find Manually via Browser

1. Go to the market page.
2. Open Developer Tools (F12) -> Network tab.
3. Refresh the page.
4. Filter for `events` or `market`.
5. Look for the JSON response containing `clobTokenIds`.

## Option 3: Use the Gamma API Directly

You can query the API in your browser:
`https://gamma-api.polymarket.com/events?slug=YOUR_MARKET_SLUG_HERE`

Look for the `clobTokenIds` field in the response.
