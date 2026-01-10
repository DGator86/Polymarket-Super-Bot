import requests
import sys
import json

def get_market_info(slug):
    """
    Fetch market info from Gamma API by slug.
    """
    url = f"https://gamma-api.polymarket.com/events?slug={slug}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        
        if not data:
            print(f"No event found for slug: {slug}")
            return

        event = data[0]
        print(f"\n--- Event: {event.get('title')} ---")
        
        markets = event.get('markets', [])
        for market in markets:
            print(f"\nQuestion: {market.get('question')}")
            print(f"Slug: {market.get('slug')}")
            print(f"Condition ID: {market.get('conditionId')}")
            
            # Parse clobTokenIds
            try:
                token_ids = json.loads(market.get('clobTokenIds', '[]'))
                if len(token_ids) >= 2:
                    print(f"YES Token ID: {token_ids[0]}")
                    print(f"NO Token ID:  {token_ids[1]}")
                else:
                    print("Token IDs not found in expected format")
            except:
                print(f"Raw Token IDs: {market.get('clobTokenIds')}")
                
    except Exception as e:
        print(f"Error fetching data: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python fetch_market_ids.py <market-slug>")
        print("Example: python fetch_market_ids.py premier-league-winner-2024-25")
        sys.exit(1)
        
    slug = sys.argv[1]
    get_market_info(slug)
