#!/bin/bash
#
# Kalshi Prediction Bot - VPS Quick Setup Script
# Run this on a fresh Ubuntu/Debian VPS
#

set -e

echo "=============================================="
echo "KALSHI PREDICTION BOT - VPS SETUP"
echo "=============================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    echo -e "${YELLOW}Warning: Running as root. Consider using a non-root user.${NC}"
fi

# Update system
echo -e "\n${GREEN}[1/7] Updating system packages...${NC}"
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-pip python3-venv git

# Check Python version
PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2 | cut -d'.' -f1,2)
echo "Python version: $PYTHON_VERSION"

# Create directories
echo -e "\n${GREEN}[2/7] Creating directories...${NC}"
mkdir -p data paper_trading_data ml_models logs

# Create virtual environment
echo -e "\n${GREEN}[3/7] Setting up Python virtual environment...${NC}"
python3 -m venv venv
source venv/bin/activate

# Install dependencies
echo -e "\n${GREEN}[4/7] Installing Python dependencies...${NC}"
pip install --upgrade pip -q
pip install -r requirements.txt -q

# Check for .env file
echo -e "\n${GREEN}[5/7] Checking configuration...${NC}"
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}Creating .env from template...${NC}"
    cp .env.example .env 2>/dev/null || cat > .env << 'EOF'
# Kalshi API Credentials
KALSHI_API_KEY=0bc7ca02-29fc-46e0-95ac-f1256213db58
KALSHI_PRIVATE_KEY_PATH=./kalshi_private_key.pem

# PAPER TRADING MODE
KALSHI_USE_DEMO=true

# Optional Data Sources
FRED_API_KEY=
BLS_API_KEY=
COINBASE_API_KEY=
COINBASE_API_SECRET=

# Optional Alerts
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
DISCORD_WEBHOOK_URL=

# Database & Logging
DATABASE_PATH=./data/trades.db
LOG_LEVEL=INFO
EOF
    chmod 600 .env
    echo -e "${YELLOW}Please edit .env with your API credentials${NC}"
fi

# Check for private key
echo -e "\n${GREEN}[6/7] Checking RSA private key...${NC}"
if [ ! -f "kalshi_private_key.pem" ]; then
    echo -e "${RED}WARNING: kalshi_private_key.pem not found!${NC}"
    echo "You need to create this file with your Kalshi RSA private key."
    echo ""
    echo "Create it with:"
    echo "  nano kalshi_private_key.pem"
    echo "  (paste your private key, then Ctrl+X, Y, Enter)"
    echo "  chmod 600 kalshi_private_key.pem"
    echo ""
else
    chmod 600 kalshi_private_key.pem
    echo -e "${GREEN}Private key found and secured${NC}"
fi

# Validate setup
echo -e "\n${GREEN}[7/7] Validating setup...${NC}"
if [ -f "kalshi_private_key.pem" ]; then
    python3 validate_setup.py || echo -e "${YELLOW}Validation had issues - check configuration${NC}"
else
    echo -e "${YELLOW}Skipping validation - private key not configured${NC}"
fi

# Create systemd service file
echo -e "\n${GREEN}Creating systemd service file...${NC}"
WORK_DIR=$(pwd)
cat > deploy/kalshi-bot.service << EOF
[Unit]
Description=Kalshi Prediction Bot - Paper Trading
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$WORK_DIR
ExecStart=$WORK_DIR/venv/bin/python3 $WORK_DIR/run_paper_trading.py --capital 1000 --interval 60
Restart=always
RestartSec=10
StandardOutput=append:$WORK_DIR/logs/bot.log
StandardError=append:$WORK_DIR/logs/bot_error.log

[Install]
WantedBy=multi-user.target
EOF

echo ""
echo "=============================================="
echo -e "${GREEN}SETUP COMPLETE!${NC}"
echo "=============================================="
echo ""
echo "Next steps:"
echo ""
echo "1. Configure your RSA private key (if not done):"
echo "   nano kalshi_private_key.pem"
echo "   chmod 600 kalshi_private_key.pem"
echo ""
echo "2. Edit .env with any additional API keys:"
echo "   nano .env"
echo ""
echo "3. Test the connection:"
echo "   source venv/bin/activate"
echo "   python3 test_kalshi_connection.py"
echo ""
echo "4. Start paper trading:"
echo "   python3 run_paper_trading.py --capital 1000 --interval 60"
echo ""
echo "   Or use systemd for auto-start:"
echo "   sudo cp deploy/kalshi-bot.service /etc/systemd/system/"
echo "   sudo systemctl daemon-reload"
echo "   sudo systemctl enable kalshi-bot"
echo "   sudo systemctl start kalshi-bot"
echo ""
echo "5. Monitor logs:"
echo "   tail -f paper_trading.log"
echo ""
echo "=============================================="
