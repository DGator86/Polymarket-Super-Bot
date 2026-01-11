#!/bin/bash

# Fix permissions for Docker container
# The bot runs as user 'botuser' (UID 1000) inside the container

echo "Fixing file permissions for Docker container..."

cd /root/Polymarket-Super-Bot/bot

# Make .env readable by the container user
if [ -f ".env" ]; then
    chmod 644 .env
    echo "✓ Fixed .env permissions"
fi

# Make sure the bot directory is accessible
chown -R 1000:1000 /root/Polymarket-Super-Bot/bot 2>/dev/null || true

echo "✓ Permissions fixed"
echo ""
echo "Restarting bot..."
docker-compose restart

echo ""
echo "Checking logs..."
sleep 3
docker logs --tail 30 polymarket-bot
