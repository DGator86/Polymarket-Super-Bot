#!/bin/bash

# Quick bot statistics display (compact view)

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'
BOLD='\033[1m'

echo ""
echo -e "${BOLD}${CYAN}POLYMARKET BOT - QUICK STATS${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check if running
if docker ps --filter "name=polymarket-bot" --filter "status=running" --format "{{.Names}}" 2>/dev/null | grep -q "polymarket-bot"; then
    echo -e "Status:    ${GREEN}● RUNNING${NC}"
    UPTIME=$(docker ps --filter "name=polymarket-bot" --format "{{.Status}}" | grep -oP 'Up \K.*')
    echo -e "Uptime:    ${CYAN}$UPTIME${NC}"
else
    echo -e "Status:    ${RED}● STOPPED${NC}"
    echo ""
    exit 1
fi

# Markets
MARKETS=$(docker logs polymarket-bot 2>&1 | grep -oP 'Loaded \K\d+(?= markets)' | tail -1)
echo -e "Markets:   ${CYAN}${MARKETS:-0}${NC}"

# Recent activity
INTENTS=$(docker logs --tail 50 polymarket-bot 2>&1 | grep -oP 'Loop complete: \K\d+(?= intents)' | tail -1)
ORDERS=$(docker logs --tail 50 polymarket-bot 2>&1 | grep -oP '\d+(?= open orders)' | tail -1)
PNL=$(docker logs --tail 50 polymarket-bot 2>&1 | grep -oP 'PnL=\K[0-9.-]+' | tail -1)

echo -e "Intents:   ${YELLOW}${INTENTS:-0}${NC} (last loop)"
echo -e "Orders:    ${YELLOW}${ORDERS:-0}${NC} open"

if [ -n "$PNL" ]; then
    if (( $(echo "$PNL > 0" | bc -l 2>/dev/null || echo 0) )); then
        echo -e "PnL:       ${GREEN}+\$$PNL${NC}"
    elif (( $(echo "$PNL < 0" | bc -l 2>/dev/null || echo 0) )); then
        echo -e "PnL:       ${RED}\$$PNL${NC}"
    else
        echo -e "PnL:       \$$PNL"
    fi
else
    echo -e "PnL:       \$0.00"
fi

# System stats
CPU=$(docker stats --no-stream --format "{{.CPUPerc}}" polymarket-bot 2>/dev/null || echo "N/A")
MEM=$(docker stats --no-stream --format "{{.MemUsage}}" polymarket-bot 2>/dev/null || echo "N/A")
echo -e "CPU:       ${CYAN}$CPU${NC}"
echo -e "Memory:    ${CYAN}$MEM${NC}"

# Recent errors (excluding Binance)
ERROR_COUNT=$(docker logs --tail 100 polymarket-bot 2>&1 | grep -iE "error|fail" | grep -v "Binance" | wc -l)
if [ "$ERROR_COUNT" -gt 0 ]; then
    echo -e "Errors:    ${RED}$ERROR_COUNT${NC} in last 100 lines"
else
    echo -e "Errors:    ${GREEN}0${NC}"
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "View dashboard:  ./monitor_bot.sh"
echo "Watch activity:  ./watch_trades.sh"
echo "Full logs:       docker logs -f polymarket-bot"
echo ""
