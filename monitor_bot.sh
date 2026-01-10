#!/bin/bash

# Live Bot Monitoring Dashboard
# Press Ctrl+C to exit

REFRESH_INTERVAL=3

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color
BOLD='\033[1m'
DIM='\033[2m'

# Function to clear screen
clear_screen() {
    printf "\033c"
}

# Function to get bot uptime
get_uptime() {
    docker ps --filter "name=polymarket-bot" --format "{{.Status}}" 2>/dev/null | grep -oP 'Up \K.*' || echo "Not running"
}

# Function to check if bot is running
is_running() {
    docker ps --filter "name=polymarket-bot" --filter "status=running" --format "{{.Names}}" 2>/dev/null | grep -q "polymarket-bot"
}

# Function to get recent intents
get_recent_intents() {
    docker logs --tail 50 polymarket-bot 2>&1 | grep -oP 'Loop complete: \K\d+(?= intents)' | tail -1
}

# Function to get PnL
get_pnl() {
    docker logs --tail 50 polymarket-bot 2>&1 | grep -oP 'PnL=\K[0-9.-]+' | tail -1
}

# Function to get open orders
get_open_orders() {
    docker logs --tail 50 polymarket-bot 2>&1 | grep -oP '\d+(?= open orders)' | tail -1
}

# Function to get recent opportunities
get_opportunities() {
    docker logs --tail 100 polymarket-bot 2>&1 | grep -iE "edge|opportunity|intent" | tail -5
}

# Function to get recent trades
get_recent_trades() {
    docker logs --tail 200 polymarket-bot 2>&1 | grep -iE "filled|executed|trade" | tail -3
}

# Function to get errors
get_errors() {
    docker logs --tail 100 polymarket-bot 2>&1 | grep -iE "error|fail|exception" | grep -v "Binance" | tail -3
}

# Function to get market count
get_market_count() {
    docker logs polymarket-bot 2>&1 | grep -oP 'Loaded \K\d+(?= markets)' | tail -1
}

# Function to get system stats
get_system_stats() {
    # CPU
    CPU=$(docker stats --no-stream --format "{{.CPUPerc}}" polymarket-bot 2>/dev/null || echo "N/A")
    # Memory
    MEM=$(docker stats --no-stream --format "{{.MemUsage}}" polymarket-bot 2>/dev/null || echo "N/A")
    echo "$CPU|$MEM"
}

# Main monitoring loop
main() {
    while true; do
        clear_screen

        echo -e "${BOLD}${CYAN}╔════════════════════════════════════════════════════════════════════╗${NC}"
        echo -e "${BOLD}${CYAN}║         POLYMARKET BOT - LIVE MONITORING DASHBOARD                 ║${NC}"
        echo -e "${BOLD}${CYAN}╚════════════════════════════════════════════════════════════════════╝${NC}"
        echo ""

        # Current time
        echo -e "${DIM}Last Updated: $(date '+%Y-%m-%d %H:%M:%S')${NC}"
        echo -e "${DIM}Refresh: ${REFRESH_INTERVAL}s | Press Ctrl+C to exit${NC}"
        echo ""

        # Bot Status
        echo -e "${BOLD}${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "${BOLD}🤖 BOT STATUS${NC}"
        echo -e "${BOLD}${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

        if is_running; then
            UPTIME=$(get_uptime)
            echo -e "Status:        ${GREEN}●${NC} ${BOLD}${GREEN}RUNNING${NC}"
            echo -e "Uptime:        ${CYAN}$UPTIME${NC}"
        else
            echo -e "Status:        ${RED}●${NC} ${BOLD}${RED}STOPPED${NC}"
            echo -e "Action:        ${YELLOW}Run: docker-compose up -d${NC}"
        fi

        # System Stats
        STATS=$(get_system_stats)
        CPU_USAGE=$(echo "$STATS" | cut -d'|' -f1)
        MEM_USAGE=$(echo "$STATS" | cut -d'|' -f2)
        echo -e "CPU Usage:     ${MAGENTA}$CPU_USAGE${NC}"
        echo -e "Memory:        ${MAGENTA}$MEM_USAGE${NC}"
        echo ""

        # Trading Activity
        echo -e "${BOLD}${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "${BOLD}📊 TRADING ACTIVITY${NC}"
        echo -e "${BOLD}${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

        INTENTS=$(get_recent_intents)
        ORDERS=$(get_open_orders)
        PNL=$(get_pnl)
        MARKETS=$(get_market_count)

        echo -e "Markets:       ${CYAN}${MARKETS:-0}${NC} loaded"
        echo -e "Intents:       ${YELLOW}${INTENTS:-0}${NC} generated (last iteration)"
        echo -e "Open Orders:   ${YELLOW}${ORDERS:-0}${NC} active"

        if [ -n "$PNL" ]; then
            if (( $(echo "$PNL > 0" | bc -l 2>/dev/null || echo 0) )); then
                echo -e "PnL:           ${GREEN}+$${PNL}${NC}"
            elif (( $(echo "$PNL < 0" | bc -l 2>/dev/null || echo 0) )); then
                echo -e "PnL:           ${RED}$${PNL}${NC}"
            else
                echo -e "PnL:           ${DIM}$${PNL:-0.00}${NC}"
            fi
        else
            echo -e "PnL:           ${DIM}\$0.00${NC}"
        fi
        echo ""

        # Recent Opportunities
        echo -e "${BOLD}${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "${BOLD}💡 RECENT OPPORTUNITIES (Last 5)${NC}"
        echo -e "${BOLD}${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

        OPPS=$(get_opportunities)
        if [ -n "$OPPS" ]; then
            echo "$OPPS" | while IFS= read -r line; do
                # Highlight different types
                if echo "$line" | grep -q "intent"; then
                    echo -e "${YELLOW}→${NC} ${DIM}$line${NC}"
                elif echo "$line" | grep -q "edge"; then
                    echo -e "${GREEN}→${NC} ${DIM}$line${NC}"
                else
                    echo -e "${CYAN}→${NC} ${DIM}$line${NC}"
                fi
            done
        else
            echo -e "${DIM}No opportunities detected yet...${NC}"
        fi
        echo ""

        # Recent Trades
        echo -e "${BOLD}${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "${BOLD}💰 RECENT TRADES (Last 3)${NC}"
        echo -e "${BOLD}${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

        TRADES=$(get_recent_trades)
        if [ -n "$TRADES" ]; then
            echo "$TRADES" | while IFS= read -r line; do
                echo -e "${GREEN}✓${NC} ${DIM}$line${NC}"
            done
        else
            echo -e "${DIM}No trades executed yet...${NC}"
        fi
        echo ""

        # Errors/Warnings
        echo -e "${BOLD}${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "${BOLD}⚠️  ERRORS & WARNINGS (Last 3)${NC}"
        echo -e "${BOLD}${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

        ERRORS=$(get_errors)
        if [ -n "$ERRORS" ]; then
            echo "$ERRORS" | while IFS= read -r line; do
                echo -e "${RED}✗${NC} ${DIM}$line${NC}"
            done
        else
            echo -e "${GREEN}No errors detected ✓${NC}"
        fi
        echo ""

        # Quick Actions
        echo -e "${BOLD}${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "${BOLD}⚡ QUICK ACTIONS${NC}"
        echo -e "${BOLD}${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "${DIM}View full logs:     ${NC}docker logs -f polymarket-bot"
        echo -e "${DIM}Restart bot:        ${NC}docker-compose restart"
        echo -e "${DIM}Stop bot:           ${NC}docker-compose down"
        echo -e "${DIM}Check database:     ${NC}sqlite3 bot/bot_state_smart.db"
        echo -e "${DIM}Edit config:        ${NC}nano bot/.env"
        echo ""

        # Footer
        echo -e "${BOLD}${CYAN}╚════════════════════════════════════════════════════════════════════╝${NC}"

        # Sleep before next refresh
        sleep $REFRESH_INTERVAL
    done
}

# Trap Ctrl+C
trap 'echo -e "\n${YELLOW}Monitoring stopped.${NC}"; exit 0' INT

# Check if docker is available
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Error: Docker is not installed or not in PATH${NC}"
    exit 1
fi

# Start monitoring
main
