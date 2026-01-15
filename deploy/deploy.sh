#!/bin/bash
#===============================================================================
# Kalshi Latency Bot - SSH Deployment Script
# 
# Usage: ./deploy.sh [user@host] [optional: target_dir]
# Example: ./deploy.sh ubuntu@192.168.1.100
#          ./deploy.sh root@vps1.example.com /opt/kalshi-bot
#===============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_NAME="kalshi-latency-bot"
DEFAULT_TARGET_DIR="/opt/${PROJECT_NAME}"
PYTHON_VERSION="3.8"

# Parse arguments
SSH_TARGET="${1:-}"
TARGET_DIR="${2:-$DEFAULT_TARGET_DIR}"

usage() {
    echo -e "${BLUE}Kalshi Latency Bot - SSH Deployment Script${NC}"
    echo ""
    echo "Usage: $0 <user@host> [target_directory]"
    echo ""
    echo "Arguments:"
    echo "  user@host         SSH connection string (e.g., ubuntu@192.168.1.100)"
    echo "  target_directory  Optional. Default: /opt/kalshi-latency-bot"
    echo ""
    echo "Examples:"
    echo "  $0 ubuntu@vps1.example.com"
    echo "  $0 root@10.0.0.5 /home/trader/kalshi-bot"
    echo ""
    echo "Prerequisites on target server:"
    echo "  - Python 3.8+"
    echo "  - pip"
    echo "  - sudo access (for systemd service installation)"
    exit 1
}

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Validate arguments
if [ -z "$SSH_TARGET" ]; then
    usage
fi

# Validate SSH target format
if [[ ! "$SSH_TARGET" =~ ^[^@]+@[^@]+$ ]]; then
    log_error "Invalid SSH target format. Expected: user@host"
    usage
fi

echo ""
echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     Kalshi Latency Arbitrage Bot - Deployment Script          ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""

log_info "Target: $SSH_TARGET"
log_info "Install directory: $TARGET_DIR"
echo ""

# Test SSH connection
log_info "Testing SSH connection..."
if ! ssh -o ConnectTimeout=10 -o BatchMode=yes "$SSH_TARGET" "echo 'SSH connection successful'" 2>/dev/null; then
    log_error "Cannot connect to $SSH_TARGET"
    log_error "Please ensure:"
    log_error "  1. The host is reachable"
    log_error "  2. SSH keys are set up or you'll be prompted for password"
    log_error "  3. The user has appropriate permissions"
    exit 1
fi
log_info "SSH connection verified!"

# Check Python version on remote
log_info "Checking Python version on remote host..."
REMOTE_PYTHON=$(ssh "$SSH_TARGET" "python3 --version 2>/dev/null || echo 'NOT_FOUND'")
if [[ "$REMOTE_PYTHON" == "NOT_FOUND" ]]; then
    log_error "Python 3 not found on remote host"
    log_error "Please install Python 3.8+ on the target server"
    exit 1
fi
log_info "Remote Python: $REMOTE_PYTHON"

# Create temporary archive
log_info "Creating deployment archive..."
TEMP_ARCHIVE="/tmp/${PROJECT_NAME}_deploy_$(date +%Y%m%d_%H%M%S).tar.gz"

# Create archive from project root (parent of deploy directory)
PROJECT_ROOT="${SCRIPT_DIR}/.."
tar -czf "$TEMP_ARCHIVE" \
    -C "$PROJECT_ROOT" \
    --exclude='.git' \
    --exclude='deploy' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.env' \
    --exclude='*.log' \
    --exclude='venv' \
    --exclude='.venv' \
    kalshi_latency_bot.py \
    backtester.py \
    monitor.py \
    requirements.txt \
    README.md

log_info "Archive created: $TEMP_ARCHIVE"

# Create remote directory and deploy
log_info "Creating remote directory structure..."
ssh "$SSH_TARGET" "sudo mkdir -p $TARGET_DIR && sudo chown \$(whoami):\$(whoami) $TARGET_DIR"

# Copy files
log_info "Transferring files to remote host..."
scp "$TEMP_ARCHIVE" "${SSH_TARGET}:/tmp/"
REMOTE_ARCHIVE="/tmp/$(basename $TEMP_ARCHIVE)"

# Extract and set up on remote
log_info "Extracting and setting up on remote host..."
ssh "$SSH_TARGET" << EOF
set -e

cd $TARGET_DIR

# Extract files
tar -xzf $REMOTE_ARCHIVE -C $TARGET_DIR

# Create virtual environment
echo "Creating Python virtual environment..."
python3 -m venv venv

# Activate and install dependencies
echo "Installing dependencies..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Create necessary directories
mkdir -p logs
mkdir -p data

# Create .env template if it doesn't exist
if [ ! -f .env ]; then
    cat > .env << 'ENVEOF'
# Kalshi API Credentials
# Get these from your Kalshi account settings
KALSHI_API_KEY=your_api_key_here
KALSHI_API_SECRET=your_api_secret_here

# Optional: Trading Parameters
# MIN_EDGE_THRESHOLD=0.03
# MAX_POSITION_SIZE=100
# KELLY_FRACTION=0.25
# MAX_DAILY_LOSS=500

# Optional: Logging
# LOG_LEVEL=INFO
ENVEOF
    echo "Created .env template - please configure your API credentials!"
fi

# Set permissions
chmod +x kalshi_latency_bot.py
chmod +x backtester.py
chmod +x monitor.py
chmod 600 .env

# Clean up
rm -f $REMOTE_ARCHIVE

echo "Deployment files extracted successfully!"
EOF

# Clean up local temp file
rm -f "$TEMP_ARCHIVE"

# Deploy systemd service
log_info "Setting up systemd service..."
ssh "$SSH_TARGET" << EOF
sudo tee /etc/systemd/system/kalshi-bot.service > /dev/null << 'SERVICEEOF'
[Unit]
Description=Kalshi Latency Arbitrage Bot
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=$(whoami)
Group=$(whoami)
WorkingDirectory=$TARGET_DIR
Environment="PATH=$TARGET_DIR/venv/bin:/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=$TARGET_DIR/.env
ExecStart=$TARGET_DIR/venv/bin/python $TARGET_DIR/kalshi_latency_bot.py
Restart=on-failure
RestartSec=30
StandardOutput=append:$TARGET_DIR/logs/bot.log
StandardError=append:$TARGET_DIR/logs/bot_error.log

# Resource limits
LimitNOFILE=65535
Nice=-5

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$TARGET_DIR/logs $TARGET_DIR/data

[Install]
WantedBy=multi-user.target
SERVICEEOF

# Monitor service
sudo tee /etc/systemd/system/kalshi-monitor.service > /dev/null << 'MONITOREOF'
[Unit]
Description=Kalshi Bot Monitor Dashboard
After=kalshi-bot.service

[Service]
Type=simple
User=$(whoami)
Group=$(whoami)
WorkingDirectory=$TARGET_DIR
Environment="PATH=$TARGET_DIR/venv/bin:/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=$TARGET_DIR/.env
ExecStart=$TARGET_DIR/venv/bin/python $TARGET_DIR/monitor.py
Restart=on-failure
RestartSec=10
StandardOutput=append:$TARGET_DIR/logs/monitor.log
StandardError=append:$TARGET_DIR/logs/monitor_error.log

[Install]
WantedBy=multi-user.target
MONITOREOF

sudo systemctl daemon-reload
echo "Systemd services installed!"
EOF

log_info "Deployment completed successfully!"
echo ""
echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║                    DEPLOYMENT COMPLETE                         ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${GREEN}Next Steps:${NC}"
echo ""
echo "1. ${YELLOW}Configure API credentials:${NC}"
echo "   ssh $SSH_TARGET"
echo "   nano $TARGET_DIR/.env"
echo ""
echo "2. ${YELLOW}Test with dry-run first:${NC}"
echo "   ssh $SSH_TARGET '$TARGET_DIR/venv/bin/python $TARGET_DIR/kalshi_latency_bot.py --dry-run'"
echo ""
echo "3. ${YELLOW}Start the bot service:${NC}"
echo "   ssh $SSH_TARGET 'sudo systemctl start kalshi-bot'"
echo ""
echo "4. ${YELLOW}Enable on boot (optional):${NC}"
echo "   ssh $SSH_TARGET 'sudo systemctl enable kalshi-bot'"
echo ""
echo "5. ${YELLOW}Check status:${NC}"
echo "   ssh $SSH_TARGET 'sudo systemctl status kalshi-bot'"
echo ""
echo "6. ${YELLOW}View logs:${NC}"
echo "   ssh $SSH_TARGET 'tail -f $TARGET_DIR/logs/bot.log'"
echo ""
echo -e "${GREEN}Service Commands:${NC}"
echo "  sudo systemctl start kalshi-bot     # Start trading bot"
echo "  sudo systemctl stop kalshi-bot      # Stop trading bot"
echo "  sudo systemctl restart kalshi-bot   # Restart trading bot"
echo "  sudo systemctl status kalshi-bot    # Check status"
echo "  sudo systemctl start kalshi-monitor # Start monitor dashboard"
echo ""
