#!/bin/bash

# Polymarket Bot Configuration Script
# This will configure your bot with the correct credentials

set -e

echo "========================================="
echo "  CONFIGURING POLYMARKET BOT"
echo "========================================="
echo ""

# Navigate to bot directory
cd /root/Polymarket-Super-Bot/bot

# Backup existing .env if it exists
if [ -f ".env" ]; then
    echo "[1/3] Backing up existing .env..."
    cp .env .env.backup.$(date +%s)
    echo "✓ Backup created"
else
    echo "[1/3] No existing .env, creating new one..."
fi
echo ""

# Create .env file with proper configuration
echo "[2/3] Creating .env configuration..."

cat > .env << 'EOF'
# =============================================================================
# Polymarket Hybrid Bot Configuration
# =============================================================================

# EXECUTION SETTINGS
# -----------------------------------------------------------------------------
# CRITICAL: Set to 0 for live trading, 1 for dry-run (simulation only)
DRY_RUN=1

# Private key for signing transactions (REQUIRED for live trading)
PRIVATE_KEY=0xb6638d0714232ecedad8f06e7e3c5661cba1dcc7e0ae9b8c23feb70ee33bbd3f

# Optional: API credentials for authenticated Polymarket endpoints
# Note: Some strategies work without these, using only the private key
API_KEY=
API_SECRET=
API_PASSPHRASE=

# Chain ID (137 = Polygon mainnet, 80001 = Mumbai testnet)
CHAIN_ID=137

# CLOB API URL
CLOB_URL=https://clob.polymarket.com


# STRATEGY PARAMETERS
# -----------------------------------------------------------------------------
# Maker half-spread (distance from fair price for bid/ask quotes)
MAKER_HALF_SPREAD=0.015

# Taker edge threshold (minimum edge to trigger aggressive order)
TAKER_EDGE_THRESHOLD=0.04

# Quote refresh interval in milliseconds
QUOTE_REFRESH_TTL_MS=3000

# Inventory skew factor (how much to adjust quotes based on position)
INVENTORY_SKEW_FACTOR=0.0001

# Minimum volatility floor (prevents division by zero)
SIGMA_FLOOR=0.001

# Use normal CDF for fair price calculation (1=yes, 0=logistic function)
USE_NORMAL_CDF=1


# RISK LIMITS
# -----------------------------------------------------------------------------
# Maximum notional value per market (in dollars)
MAX_NOTIONAL_PER_MARKET=100.0

# Maximum inventory per token (in shares)
MAX_INVENTORY_PER_TOKEN=500.0

# Maximum total open orders
MAX_OPEN_ORDERS_TOTAL=10

# Maximum orders per minute (rate limit)
MAX_ORDERS_PER_MIN=30

# Maximum daily loss (in dollars) - triggers kill switch when exceeded
MAX_DAILY_LOSS=50.0

# Maximum taker slippage tolerance (in cents)
MAX_TAKER_SLIPPAGE=0.02

# Feed staleness threshold (milliseconds) - cancel orders if data stale
FEED_STALE_MS=2000


# SYSTEM SETTINGS
# -----------------------------------------------------------------------------
# Main loop interval in milliseconds
LOOP_INTERVAL_MS=500

# Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
LOG_LEVEL=INFO

# Optional: log file path
LOG_FILE=bot.log

# Database path (SQLite)
DB_PATH=bot_state_smart.db

# Market registry JSON path
MARKET_REGISTRY_PATH=markets.json

# EMERGENCY KILL SWITCH
# Set to 1 to immediately stop all trading and cancel orders
KILL_SWITCH=0
EOF

echo "✓ Configuration file created"
echo ""

# Set proper permissions
chmod 600 .env
echo "[3/3] Set secure file permissions (600)"
echo ""

echo "========================================="
echo "  CONFIGURATION COMPLETE"
echo "========================================="
echo ""
echo "Important Settings:"
echo "  • DRY_RUN: 1 (Testing mode - no real trades)"
echo "  • MAX_DAILY_LOSS: $50"
echo "  • MAX_NOTIONAL_PER_MARKET: $100"
echo "  • Private Key: Configured ✓"
echo ""
echo "⚠️  IMPORTANT SAFETY NOTES:"
echo "  1. Bot is in DRY_RUN mode (no real money)"
echo "  2. To enable live trading, set DRY_RUN=0 in .env"
echo "  3. Monitor logs carefully before going live"
echo ""
echo "Next steps:"
echo "  1. Restart the bot: docker-compose restart"
echo "  2. Watch logs: docker logs -f polymarket-bot"
echo "  3. Monitor for 30-60 minutes in dry-run mode"
echo "  4. If working well, edit .env and set DRY_RUN=0"
echo ""
