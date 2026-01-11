#!/bin/bash

# Simple trading activity monitor
# Shows only the interesting stuff: intents, trades, opportunities, errors

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m'
BOLD='\033[1m'

echo -e "${BOLD}${CYAN}════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}${CYAN}   POLYMARKET BOT - LIVE TRADING ACTIVITY STREAM${NC}"
echo -e "${BOLD}${CYAN}════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${YELLOW}Watching for: Intents, Trades, Opportunities, Errors${NC}"
echo -e "${YELLOW}Press Ctrl+C to stop${NC}"
echo ""

# Follow logs and filter for interesting events
docker logs -f polymarket-bot 2>&1 | grep --line-buffered -iE "intent|trade|filled|executed|opportunity|edge|error|warning|fail|order" | while IFS= read -r line; do
    timestamp=$(date '+%H:%M:%S')

    # Color code based on content
    if echo "$line" | grep -iq "error\|fail\|exception"; then
        # Errors in red (but skip Binance errors)
        if ! echo "$line" | grep -iq "binance"; then
            echo -e "${RED}[${timestamp}] ✗ ${line}${NC}"
        fi
    elif echo "$line" | grep -iq "filled\|executed\|trade"; then
        # Trades in green
        echo -e "${GREEN}[${timestamp}] ✓ ${line}${NC}"
    elif echo "$line" | grep -iq "intent"; then
        # Intents in yellow
        echo -e "${YELLOW}[${timestamp}] ⚡ ${line}${NC}"
    elif echo "$line" | grep -iq "opportunity\|edge"; then
        # Opportunities in cyan
        echo -e "${CYAN}[${timestamp}] 💡 ${line}${NC}"
    elif echo "$line" | grep -iq "order"; then
        # Orders in magenta
        echo -e "${MAGENTA}[${timestamp}] 📋 ${line}${NC}"
    else
        # Everything else in default color
        echo -e "[${timestamp}] ${line}"
    fi
done
