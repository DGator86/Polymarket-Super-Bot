#!/bin/bash
#===============================================================================
# Kalshi Latency Bot - Multi-Server SSH Deployment Script
# 
# Deploy to multiple VPS servers in parallel
#
# Usage: ./multi-deploy.sh servers.txt [target_dir]
# Example: ./multi-deploy.sh servers.txt /opt/kalshi-bot
#===============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVERS_FILE="${1:-servers.txt}"
TARGET_DIR="${2:-/opt/kalshi-latency-bot}"
LOG_DIR="/tmp/kalshi-deploy-logs"

usage() {
    echo -e "${BLUE}Kalshi Latency Bot - Multi-Server Deployment${NC}"
    echo ""
    echo "Usage: $0 <servers_file> [target_directory]"
    echo ""
    echo "Arguments:"
    echo "  servers_file      Text file with one SSH target per line (user@host)"
    echo "  target_directory  Optional. Default: /opt/kalshi-latency-bot"
    echo ""
    echo "Servers file format (one per line):"
    echo "  ubuntu@vps1.example.com"
    echo "  root@192.168.1.100"
    echo "  trader@vps2.example.com"
    echo ""
    echo "Example:"
    echo "  $0 servers.txt /opt/kalshi-bot"
    exit 1
}

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check arguments
if [ ! -f "$SERVERS_FILE" ]; then
    log_error "Servers file not found: $SERVERS_FILE"
    usage
fi

# Read servers
mapfile -t SERVERS < <(grep -v '^#' "$SERVERS_FILE" | grep -v '^$')

if [ ${#SERVERS[@]} -eq 0 ]; then
    log_error "No servers found in $SERVERS_FILE"
    exit 1
fi

echo ""
echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║    Kalshi Latency Bot - Multi-Server Deployment               ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
log_info "Found ${#SERVERS[@]} server(s) to deploy to:"
for server in "${SERVERS[@]}"; do
    echo "  - $server"
done
echo ""

# Create log directory
mkdir -p "$LOG_DIR"

# Deploy function for parallel execution
deploy_to_server() {
    local server="$1"
    local log_file="$LOG_DIR/${server//[@:\.]/_}.log"
    
    echo -e "${CYAN}[DEPLOYING]${NC} $server"
    
    if "$SCRIPT_DIR/deploy.sh" "$server" "$TARGET_DIR" > "$log_file" 2>&1; then
        echo -e "${GREEN}[SUCCESS]${NC} $server"
        return 0
    else
        echo -e "${RED}[FAILED]${NC} $server - check $log_file"
        return 1
    fi
}

export -f deploy_to_server
export SCRIPT_DIR TARGET_DIR LOG_DIR
export RED GREEN YELLOW BLUE CYAN NC

# Deploy in parallel (max 4 concurrent deployments)
echo "Starting parallel deployment..."
echo ""

FAILED=0
SUCCESS=0

for server in "${SERVERS[@]}"; do
    if deploy_to_server "$server"; then
        ((SUCCESS++))
    else
        ((FAILED++))
    fi
done

echo ""
echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║                  DEPLOYMENT SUMMARY                            ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${GREEN}Successful:${NC} $SUCCESS"
echo -e "  ${RED}Failed:${NC}     $FAILED"
echo -e "  Total:      ${#SERVERS[@]}"
echo ""
echo -e "Deployment logs: $LOG_DIR/"
echo ""

if [ $FAILED -gt 0 ]; then
    log_error "Some deployments failed. Check logs for details."
    exit 1
fi

log_info "All deployments completed successfully!"
echo ""
echo -e "${YELLOW}Remember to configure .env on each server with your Kalshi API credentials!${NC}"
echo ""
