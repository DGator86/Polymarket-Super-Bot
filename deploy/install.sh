#!/bin/bash
# Kalshi Prediction Bot - Installation Script
# Run with: sudo bash install.sh

set -e

echo "=============================================="
echo "Kalshi Prediction Bot - Installation"
echo "=============================================="

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root (sudo bash install.sh)"
    exit 1
fi

# Configuration
BOT_USER="kalshi"
BOT_DIR="/opt/kalshi-prediction-bot"
VENV_DIR="$BOT_DIR/venv"
LOG_DIR="/var/log/kalshi-bot"
DATA_DIR="/var/lib/kalshi-bot"

# Create bot user if doesn't exist
if ! id "$BOT_USER" &>/dev/null; then
    echo "Creating user: $BOT_USER"
    useradd -r -s /bin/false -m -d /home/$BOT_USER $BOT_USER
fi

# Install system dependencies
echo "Installing system dependencies..."
apt-get update
apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    git \
    openssl \
    curl

# Create directories
echo "Creating directories..."
mkdir -p $BOT_DIR
mkdir -p $LOG_DIR
mkdir -p $DATA_DIR

# Copy bot files
echo "Copying bot files..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cp -r $SCRIPT_DIR/* $BOT_DIR/
rm -rf $BOT_DIR/deploy  # Remove deploy folder from installed version

# Create Python virtual environment
echo "Creating virtual environment..."
python3 -m venv $VENV_DIR

# Install Python dependencies
echo "Installing Python dependencies..."
$VENV_DIR/bin/pip install --upgrade pip
$VENV_DIR/bin/pip install -r $BOT_DIR/requirements.txt

# Generate RSA keys if they don't exist
if [ ! -f "$BOT_DIR/kalshi_private_key.pem" ]; then
    echo "Generating RSA keys..."
    openssl genrsa -out $BOT_DIR/kalshi_private_key.pem 4096
    openssl rsa -in $BOT_DIR/kalshi_private_key.pem -pubout -out $BOT_DIR/kalshi_public_key.pem
    echo ""
    echo "IMPORTANT: Upload kalshi_public_key.pem to your Kalshi account!"
    echo "Location: $BOT_DIR/kalshi_public_key.pem"
fi

# Create .env file if doesn't exist
if [ ! -f "$BOT_DIR/.env" ]; then
    echo "Creating .env from template..."
    cp $BOT_DIR/.env.example $BOT_DIR/.env
    echo ""
    echo "IMPORTANT: Edit $BOT_DIR/.env with your API credentials!"
fi

# Update paths in .env
sed -i "s|DATABASE_PATH=.*|DATABASE_PATH=$DATA_DIR/trades.db|g" $BOT_DIR/.env
sed -i "s|KALSHI_PRIVATE_KEY_PATH=.*|KALSHI_PRIVATE_KEY_PATH=$BOT_DIR/kalshi_private_key.pem|g" $BOT_DIR/.env

# Set permissions
echo "Setting permissions..."
chown -R $BOT_USER:$BOT_USER $BOT_DIR
chown -R $BOT_USER:$BOT_USER $LOG_DIR
chown -R $BOT_USER:$BOT_USER $DATA_DIR
chmod 600 $BOT_DIR/kalshi_private_key.pem
chmod 600 $BOT_DIR/.env

# Install systemd service
echo "Installing systemd service..."
cat > /etc/systemd/system/kalshi-bot.service << EOF
[Unit]
Description=Kalshi Prediction Bot
After=network.target

[Service]
Type=simple
User=$BOT_USER
WorkingDirectory=$BOT_DIR
Environment="PATH=$VENV_DIR/bin"
ExecStart=$VENV_DIR/bin/python main.py
Restart=always
RestartSec=10

# Logging
StandardOutput=append:$LOG_DIR/bot.log
StandardError=append:$LOG_DIR/error.log

# Security
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$DATA_DIR $LOG_DIR
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd
systemctl daemon-reload

# Create log rotation
cat > /etc/logrotate.d/kalshi-bot << EOF
$LOG_DIR/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 $BOT_USER $BOT_USER
    sharedscripts
    postrotate
        systemctl reload kalshi-bot > /dev/null 2>&1 || true
    endscript
}
EOF

echo ""
echo "=============================================="
echo "Installation Complete!"
echo "=============================================="
echo ""
echo "Next steps:"
echo "1. Edit configuration: sudo nano $BOT_DIR/.env"
echo "2. Upload public key to Kalshi: $BOT_DIR/kalshi_public_key.pem"
echo "3. Start the bot: sudo systemctl start kalshi-bot"
echo "4. Enable on boot: sudo systemctl enable kalshi-bot"
echo "5. View logs: sudo journalctl -u kalshi-bot -f"
echo ""
echo "Useful commands:"
echo "  sudo systemctl status kalshi-bot  - Check status"
echo "  sudo systemctl restart kalshi-bot - Restart bot"
echo "  sudo systemctl stop kalshi-bot    - Stop bot"
echo "  tail -f $LOG_DIR/bot.log          - View logs"
echo ""
