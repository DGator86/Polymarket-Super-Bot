#!/bin/bash
# Quick update script to pull latest changes and restart bot

set -e

echo "🔄 Updating Polymarket Bot..."
echo ""

cd /root/Polymarket-Super-Bot

echo "📥 Pulling latest changes..."
git pull origin claude/check-bot-status-TDbVL

echo ""
echo "🔄 Rebuilding and restarting bot..."
cd bot
docker-compose up -d --build

echo ""
echo "⏳ Waiting for bot to initialize..."
sleep 5

echo ""
echo "✓ Bot restarted! Checking status..."
docker logs --tail 20 polymarket-bot

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Update complete!"
echo "Run: ./bot_stats.sh to check if markets loaded"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
