# Kalshi Prediction Bot - VPS Deployment Guide

## Quick Deploy (One-Command Setup)

```bash
# Clone and deploy
git clone https://github.com/DGator86/Polymarket-Super-Bot.git kalshi-bot
cd kalshi-bot
chmod +x deploy/vps_setup.sh
./deploy/vps_setup.sh
```

## Manual Deployment Steps

### 1. Prerequisites
- Ubuntu 20.04+ or Debian 11+ VPS
- Python 3.10+
- At least 1GB RAM, 10GB disk

### 2. Clone Repository
```bash
git clone https://github.com/DGator86/Polymarket-Super-Bot.git kalshi-bot
cd kalshi-bot
```

### 3. Create Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Configure Credentials

Create `.env` file:
```bash
cat > .env << 'EOF'
# Kalshi API Credentials
KALSHI_API_KEY=0bc7ca02-29fc-46e0-95ac-f1256213db58
KALSHI_PRIVATE_KEY_PATH=./kalshi_private_key.pem

# PAPER TRADING MODE - Set to true for testing
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
```

### 5. Create RSA Private Key

You need to upload your Kalshi RSA private key. Create the file:
```bash
nano kalshi_private_key.pem
# Paste your private key content, then save (Ctrl+X, Y, Enter)
chmod 600 kalshi_private_key.pem
```

**Important**: The private key must match what you registered on Kalshi's dashboard.

### 6. Validate Setup
```bash
python3 validate_setup.py
```

Expected output: `7/7 checks passed`

### 7. Test API Connection
```bash
python3 test_kalshi_connection.py
```

### 8. Start Paper Trading

**Option A: Direct Run (foreground)**
```bash
python3 run_paper_trading.py --capital 1000 --interval 60
```

**Option B: Background with nohup**
```bash
nohup python3 run_paper_trading.py --capital 1000 --interval 60 > paper_trading.log 2>&1 &
echo $! > bot.pid
```

**Option C: Using PM2 (recommended)**
```bash
npm install -g pm2
pm2 start run_paper_trading.py --name "kalshi-paper" --interpreter python3 -- --capital 1000 --interval 60
pm2 save
pm2 startup  # Enable auto-start on reboot
```

**Option D: Using systemd**
```bash
sudo cp deploy/kalshi-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable kalshi-bot
sudo systemctl start kalshi-bot
```

## Monitoring

### View Logs
```bash
# Real-time logs
tail -f paper_trading.log

# With PM2
pm2 logs kalshi-paper

# With systemd
sudo journalctl -u kalshi-bot -f
```

### Check Status
```bash
# View positions and P&L
python3 generate_report.py --days 7 --format console

# Export to JSON
python3 generate_report.py --days 30 --format json --output report.json
```

### Stop Bot
```bash
# If using nohup
kill $(cat bot.pid)

# If using PM2
pm2 stop kalshi-paper

# If using systemd
sudo systemctl stop kalshi-bot
```

## Configuration Options

### Paper Trading CLI Arguments
```
--capital       Starting capital (default: 1000)
--interval      Scan interval in seconds (default: 60)
--max-positions Maximum open positions (default: 10)
--data-dir      Data directory (default: ./paper_trading_data)
--min-ml-samples Minimum trades before ML training (default: 20)
```

### Key Configuration Thresholds (in config.py)
- Minimum edge: 5%
- Minimum liquidity: $50
- Kelly fraction: 0.25x
- Max position per market: 10%
- Max correlated exposure: 25%
- Max daily loss: 5%

## Switching to Live Trading

⚠️ **WARNING**: Only switch to live trading after extensive paper trading validation!

1. Set `KALSHI_USE_DEMO=false` in `.env`
2. Edit `main.py` line 115: `self.dry_run = False`
3. Start with small capital
4. Monitor closely

## Troubleshooting

### 403 Forbidden Error
- Check your VPS IP isn't geo-blocked (Kalshi is US-only)
- Verify API key and private key match Kalshi dashboard
- Ensure private key file has correct permissions (600)

### Import Errors
```bash
pip install -r requirements.txt
```

### Permission Denied
```bash
chmod 600 kalshi_private_key.pem
chmod 600 .env
```

### Database Errors
```bash
mkdir -p data paper_trading_data
```

## Support

- Kalshi API Docs: https://trading-api.readme.io/reference
- FRED API: https://fred.stlouisfed.org/docs/api/api_key.html
- Issues: https://github.com/DGator86/Polymarket-Super-Bot/issues
