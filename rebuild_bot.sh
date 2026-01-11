#!/bin/bash
# Force rebuild of Docker container with latest code

set -e

echo "🔄 Forcing Docker container rebuild..."
echo ""

cd /home/user/Polymarket-Super-Bot/bot

echo "📦 Stopping and removing old container..."
docker-compose down

echo ""
echo "🏗️  Building new container (this may take a minute)..."
docker-compose build --no-cache

echo ""
echo "🚀 Starting new container..."
docker-compose up -d

echo ""
echo "⏳ Waiting for bot to initialize..."
sleep 5

echo ""
echo "📊 Checking logs for price_change handling..."
docker logs --tail 50 polymarket-bot | grep -E "price_change|First.*update|intents"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Rebuild complete!"
echo ""
echo "Check for:"
echo "  - NO 'Unknown message type' warnings"
echo "  - 'First price_change update' or 'First REST orderbook fetched'"
echo "  - Non-zero intents in bot loop"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
