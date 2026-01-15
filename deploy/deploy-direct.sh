#!/bin/bash
#===============================================================================
# Direct Deployment to Kalshi-Latency-Bot VPS
# Target: 134.199.194.220 (Ubuntu 22.04)
#===============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

VPS_IP="134.199.194.220"
VPS_USER="${1:-root}"
TARGET_DIR="/opt/kalshi-latency-bot"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${SCRIPT_DIR}/.."

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

echo ""
echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     Kalshi Latency Bot - Direct VPS Deployment                ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
log_info "Target VPS: ${VPS_USER}@${VPS_IP}"
log_info "Install directory: ${TARGET_DIR}"
echo ""

# Test SSH connection
log_info "Testing SSH connection..."
if ! ssh -o ConnectTimeout=10 "${VPS_USER}@${VPS_IP}" "echo 'Connected!'" 2>/dev/null; then
    log_error "Cannot connect to ${VPS_USER}@${VPS_IP}"
    log_warn "Make sure you have SSH access configured"
    exit 1
fi

# Create deployment archive
log_info "Creating deployment archive..."
TEMP_ARCHIVE="/tmp/kalshi-bot-deploy.tar.gz"

tar -czf "$TEMP_ARCHIVE" \
    -C "$PROJECT_ROOT" \
    --exclude='.git' \
    --exclude='deploy/deploy*.sh' \
    --exclude='deploy/multi-deploy.sh' \
    --exclude='deploy/servers.txt*' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='*.log' \
    --exclude='venv' \
    kalshi_latency_bot.py \
    backtester.py \
    monitor.py \
    requirements.txt \
    README.md \
    deploy/.env.production \
    deploy/kalshi_private_key.pem \
    deploy/.env.template \
    deploy/DEPLOYMENT_GUIDE.md

log_info "Archive created: $(du -h $TEMP_ARCHIVE | cut -f1)"

# Deploy to VPS
log_info "Deploying to VPS..."
ssh "${VPS_USER}@${VPS_IP}" << 'REMOTE_SCRIPT'
set -e

TARGET_DIR="/opt/kalshi-latency-bot"

echo "Creating target directory..."
mkdir -p $TARGET_DIR
cd $TARGET_DIR

echo "Extracting files..."
tar -xzf /tmp/kalshi-bot-deploy.tar.gz -C $TARGET_DIR

# Move deploy files to main directory
mv deploy/.env.production .env
mv deploy/kalshi_private_key.pem .
mv deploy/DEPLOYMENT_GUIDE.md .
rm -rf deploy

# Set secure permissions
chmod 600 .env
chmod 600 kalshi_private_key.pem

# Create Python virtual environment
echo "Setting up Python environment..."
python3 -m venv venv
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Create directories
mkdir -p logs data

# Create systemd service
echo "Installing systemd service..."
sudo tee /etc/systemd/system/kalshi-bot.service > /dev/null << 'SERVICEEOF'
[Unit]
Description=Kalshi Latency Arbitrage Bot
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=/opt/kalshi-latency-bot
Environment="PATH=/opt/kalshi-latency-bot/venv/bin:/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=/opt/kalshi-latency-bot/.env
ExecStart=/opt/kalshi-latency-bot/venv/bin/python /opt/kalshi-latency-bot/kalshi_latency_bot.py
Restart=on-failure
RestartSec=30
StandardOutput=append:/opt/kalshi-latency-bot/logs/bot.log
StandardError=append:/opt/kalshi-latency-bot/logs/bot_error.log

# Resource limits
LimitNOFILE=65535
Nice=-5

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
User=root
Group=root
WorkingDirectory=/opt/kalshi-latency-bot
Environment="PATH=/opt/kalshi-latency-bot/venv/bin:/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=/opt/kalshi-latency-bot/.env
ExecStart=/opt/kalshi-latency-bot/venv/bin/python /opt/kalshi-latency-bot/monitor.py
Restart=on-failure
RestartSec=10
StandardOutput=append:/opt/kalshi-latency-bot/logs/monitor.log
StandardError=append:/opt/kalshi-latency-bot/logs/monitor_error.log

[Install]
WantedBy=multi-user.target
MONITOREOF

sudo systemctl daemon-reload

echo ""
echo "✓ Deployment complete!"
REMOTE_SCRIPT

# Copy archive
log_info "Copying archive to VPS..."
scp "$TEMP_ARCHIVE" "${VPS_USER}@${VPS_IP}:/tmp/"

# Run remote deployment
log_info "Running remote setup..."
ssh "${VPS_USER}@${VPS_IP}" << 'SETUP_SCRIPT'
set -e
TARGET_DIR="/opt/kalshi-latency-bot"

echo "Creating target directory..."
mkdir -p $TARGET_DIR
cd $TARGET_DIR

echo "Extracting files..."
tar -xzf /tmp/kalshi-bot-deploy.tar.gz -C $TARGET_DIR

# Move deploy files to main directory
if [ -d "deploy" ]; then
    mv deploy/.env.production .env 2>/dev/null || true
    mv deploy/kalshi_private_key.pem . 2>/dev/null || true
    mv deploy/DEPLOYMENT_GUIDE.md . 2>/dev/null || true
    rm -rf deploy
fi

# Set secure permissions
chmod 600 .env 2>/dev/null || true
chmod 600 kalshi_private_key.pem 2>/dev/null || true

# Create Python virtual environment
echo "Setting up Python environment..."
python3 -m venv venv
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Create directories
mkdir -p logs data

# Create systemd service for the trading bot
echo "Installing systemd services..."
cat > /etc/systemd/system/kalshi-bot.service << 'SERVICEEOF'
[Unit]
Description=Kalshi Latency Arbitrage Bot
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=/opt/kalshi-latency-bot
Environment="PATH=/opt/kalshi-latency-bot/venv/bin:/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=/opt/kalshi-latency-bot/.env
ExecStart=/opt/kalshi-latency-bot/venv/bin/python /opt/kalshi-latency-bot/kalshi_latency_bot.py
Restart=on-failure
RestartSec=30
StandardOutput=append:/opt/kalshi-latency-bot/logs/bot.log
StandardError=append:/opt/kalshi-latency-bot/logs/bot_error.log
LimitNOFILE=65535
Nice=-5

[Install]
WantedBy=multi-user.target
SERVICEEOF

# Create systemd service for monitoring
cat > /etc/systemd/system/kalshi-monitor.service << 'MONITOREOF'
[Unit]
Description=Kalshi Bot Monitor Dashboard
After=kalshi-bot.service

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=/opt/kalshi-latency-bot
Environment="PATH=/opt/kalshi-latency-bot/venv/bin:/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=/opt/kalshi-latency-bot/.env
ExecStart=/opt/kalshi-latency-bot/venv/bin/python /opt/kalshi-latency-bot/monitor.py
Restart=on-failure
RestartSec=10
StandardOutput=append:/opt/kalshi-latency-bot/logs/monitor.log
StandardError=append:/opt/kalshi-latency-bot/logs/monitor_error.log

[Install]
WantedBy=multi-user.target
MONITOREOF

systemctl daemon-reload

# Clean up
rm -f /tmp/kalshi-bot-deploy.tar.gz

echo ""
echo "========================================="
echo "        DEPLOYMENT COMPLETE!"
echo "========================================="
echo ""
echo "Files installed to: /opt/kalshi-latency-bot/"
echo ""
echo "Next steps:"
echo "  1. Test: /opt/kalshi-latency-bot/venv/bin/python /opt/kalshi-latency-bot/kalshi_latency_bot.py --dry-run"
echo "  2. Start: systemctl start kalshi-bot"
echo "  3. Enable: systemctl enable kalshi-bot"
echo "  4. Logs: tail -f /opt/kalshi-latency-bot/logs/bot.log"
echo ""
SETUP_SCRIPT

# Clean up local temp file
rm -f "$TEMP_ARCHIVE"

echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                  DEPLOYMENT SUCCESSFUL!                        ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}To test the bot:${NC}"
echo "  ssh ${VPS_USER}@${VPS_IP} '/opt/kalshi-latency-bot/venv/bin/python /opt/kalshi-latency-bot/kalshi_latency_bot.py --dry-run'"
echo ""
echo -e "${YELLOW}To start the bot:${NC}"
echo "  ssh ${VPS_USER}@${VPS_IP} 'systemctl start kalshi-bot'"
echo ""
echo -e "${YELLOW}To view logs:${NC}"
echo "  ssh ${VPS_USER}@${VPS_IP} 'tail -f /opt/kalshi-latency-bot/logs/bot.log'"
echo ""
