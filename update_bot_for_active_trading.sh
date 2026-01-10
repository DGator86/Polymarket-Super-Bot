#!/bin/bash

# Complete bot update script:
# 1. Fetch active markets across all categories
# 2. Replace Binance with Kraken (US-friendly)
# 3. Configure aggressive trading parameters

set -e

echo "=========================================="
echo " UPDATING BOT FOR ACTIVE TRADING"
echo "=========================================="
echo ""

cd /root/Polymarket-Super-Bot

# Step 1: Install dependencies for market fetching
echo "[1/5] Installing Python dependencies..."
pip3 install requests -q 2>/dev/null || true
echo "✓ Dependencies ready"
echo ""

# Step 2: Fetch active markets
echo "[2/5] Fetching active markets (NFL, NBA, NCAA, Soccer, Politics, Crypto)..."
cd bot
python3 ../fetch_active_markets.py

if [ ! -f "markets.json" ]; then
    echo "ERROR: Failed to create markets.json"
    exit 1
fi

echo "✓ Markets updated"
echo ""

# Step 3: Replace Binance with Kraken in app.py
echo "[3/5] Switching from Binance to Kraken (US-friendly)..."

# Backup original
cp src/app.py src/app.py.backup

# Update imports
sed -i 's/from src.feeds.spot_ws import SpotPriceFeed, SimulatedSpotFeed, BinanceSpotFeed/from src.feeds.spot_ws import SpotPriceFeed, SimulatedSpotFeed\nfrom src.feeds.kraken_feed import KrakenSpotFeed/' src/app.py

# Update initialization
sed -i 's/self.spot_feed = BinanceSpotFeed(symbols=\["BTCUSDT", "ETHUSDT", "SOLUSDT"\])/self.spot_feed = KrakenSpotFeed(symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT", "MATICUSDT"])/' src/app.py

echo "✓ Switched to Kraken feed"
echo ""

# Step 4: Update trading parameters for more opportunities
echo "[4/5] Configuring more aggressive trading parameters..."

if [ -f ".env" ]; then
    # Update thresholds to find more opportunities
    sed -i 's/^MAKER_HALF_SPREAD=.*/MAKER_HALF_SPREAD=0.008/' .env
    sed -i 's/^TAKER_EDGE_THRESHOLD=.*/TAKER_EDGE_THRESHOLD=0.02/' .env
    sed -i 's/^MAX_NOTIONAL_PER_MARKET=.*/MAX_NOTIONAL_PER_MARKET=200.0/' .env
    sed -i 's/^QUOTE_REFRESH_TTL_MS=.*/QUOTE_REFRESH_TTL_MS=2000/' .env

    echo "✓ Trading parameters updated:"
    echo "   • MAKER_HALF_SPREAD: 0.008 (was 0.01)"
    echo "   • TAKER_EDGE_THRESHOLD: 0.02 (was 0.03)"
    echo "   • MAX_NOTIONAL_PER_MARKET: $200 (was $100)"
    echo ""
else
    echo "⚠️  No .env file found - run configure_bot.sh first"
fi

# Step 5: Rebuild and restart
echo "[5/5] Rebuilding and restarting bot..."
docker-compose down
docker-compose build --no-cache
docker-compose up -d

echo ""
echo "✓ Bot rebuilt and restarted"
echo ""

# Wait for startup
sleep 5

echo "=========================================="
echo " UPDATE COMPLETE"
echo "=========================================="
echo ""
echo "Changes made:"
echo "  ✓ Loaded active markets across NFL, NBA, NCAA, Soccer, Politics, Crypto"
echo "  ✓ Switched from Binance to Kraken (US-friendly)"
echo "  ✓ Lowered trading thresholds for more opportunities"
echo "  ✓ Rebuilt Docker image with new code"
echo ""
echo "Checking bot status..."
docker ps | grep polymarket

echo ""
echo "Recent logs:"
docker logs --tail 30 polymarket-bot

echo ""
echo "=========================================="
echo "Monitor your bot:"
echo "  docker logs -f polymarket-bot"
echo ""
echo "If you see trading intents, it's working!"
echo "=========================================="
