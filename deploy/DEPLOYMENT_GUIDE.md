# Kalshi Latency Bot - VPS Deployment Guide

## Quick Start

### Single Server Deployment

```bash
# Make scripts executable
chmod +x deploy.sh multi-deploy.sh

# Deploy to a single VPS
./deploy.sh ubuntu@your-vps-ip.com
```

### Multi-Server Deployment

```bash
# Create servers list
cp servers.txt.example servers.txt
nano servers.txt  # Add your VPS addresses

# Deploy to all servers
./multi-deploy.sh servers.txt
```

---

## Prerequisites

### On Your Local Machine
- SSH client
- SSH key-based authentication set up (recommended)
- Bash shell

### On Target VPS Servers
- Ubuntu 20.04+ / Debian 11+ / CentOS 8+ (or similar)
- Python 3.8 or higher
- pip (Python package manager)
- sudo access
- Internet connectivity to:
  - stream.binance.com:9443
  - ws-feed.exchange.coinbase.com
  - ws.kraken.com
  - api.kalshi.com

---

## Deployment Options

### Option 1: Automated Deployment Script (Recommended)

The `deploy.sh` script handles everything automatically:

```bash
./deploy.sh user@hostname [target_directory]
```

**What it does:**
1. Tests SSH connectivity
2. Verifies Python installation
3. Creates project directory
4. Transfers all files
5. Creates Python virtual environment
6. Installs dependencies
7. Sets up systemd services
8. Creates `.env` template

**Example:**
```bash
./deploy.sh ubuntu@192.168.1.100
./deploy.sh root@vps.example.com /home/trader/bot
```

### Option 2: Multi-Server Parallel Deployment

For deploying to multiple VPS servers at once:

```bash
# Create servers file
cat > servers.txt << EOF
ubuntu@vps1.example.com
root@vps2.example.com
trader@vps3.example.com
EOF

# Deploy to all
./multi-deploy.sh servers.txt
```

### Option 3: Manual Deployment

If you prefer manual control:

```bash
# 1. SSH into your VPS
ssh user@your-vps

# 2. Create directory
sudo mkdir -p /opt/kalshi-latency-bot
sudo chown $USER:$USER /opt/kalshi-latency-bot
cd /opt/kalshi-latency-bot

# 3. Transfer files (from local machine)
scp kalshi_latency_bot.py backtester.py monitor.py requirements.txt README.md user@your-vps:/opt/kalshi-latency-bot/

# 4. Set up virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 5. Configure environment
cp /path/to/.env.template .env
nano .env  # Add your Kalshi credentials

# 6. Test
python kalshi_latency_bot.py --dry-run
```

---

## Post-Deployment Configuration

### 1. Configure API Credentials

SSH into each server and edit the `.env` file:

```bash
ssh user@your-vps
nano /opt/kalshi-latency-bot/.env
```

Set your Kalshi API credentials:
```env
KALSHI_API_KEY=your_actual_api_key
KALSHI_API_SECRET=your_actual_api_secret
```

### 2. Test with Dry Run

Always test before live trading:

```bash
cd /opt/kalshi-latency-bot
source venv/bin/activate
python kalshi_latency_bot.py --dry-run
```

### 3. Run Backtest

Validate strategy performance:

```bash
cd /opt/kalshi-latency-bot
source venv/bin/activate
python backtester.py
```

---

## Service Management

### Starting the Bot

```bash
# Start as systemd service (recommended for production)
sudo systemctl start kalshi-bot

# Or run manually
cd /opt/kalshi-latency-bot
source venv/bin/activate
python kalshi_latency_bot.py
```

### Stopping the Bot

```bash
sudo systemctl stop kalshi-bot
```

### Checking Status

```bash
sudo systemctl status kalshi-bot
```

### Viewing Logs

```bash
# Real-time log following
tail -f /opt/kalshi-latency-bot/logs/bot.log

# Error logs
tail -f /opt/kalshi-latency-bot/logs/bot_error.log

# Or via journalctl
sudo journalctl -u kalshi-bot -f
```

### Enable Auto-Start on Boot

```bash
sudo systemctl enable kalshi-bot
```

### Restart After Config Changes

```bash
sudo systemctl restart kalshi-bot
```

---

## Monitor Dashboard

Start the real-time monitoring dashboard:

```bash
# As a service
sudo systemctl start kalshi-monitor

# Or manually
cd /opt/kalshi-latency-bot
source venv/bin/activate
python monitor.py
```

---

## Directory Structure After Deployment

```
/opt/kalshi-latency-bot/
├── kalshi_latency_bot.py    # Main trading bot
├── backtester.py            # Backtesting engine
├── monitor.py               # Monitoring dashboard
├── requirements.txt         # Python dependencies
├── README.md                # Documentation
├── .env                     # Environment configuration (your credentials)
├── venv/                    # Python virtual environment
├── logs/                    # Log files
│   ├── bot.log
│   ├── bot_error.log
│   ├── monitor.log
│   └── monitor_error.log
└── data/                    # Data files (trades, metrics)
```

---

## Troubleshooting

### SSH Connection Failed

```bash
# Test SSH connection
ssh -v user@your-vps

# Check SSH key
ssh-add -l

# If no key, generate one
ssh-keygen -t ed25519
ssh-copy-id user@your-vps
```

### Python Not Found

```bash
# Install Python on Ubuntu/Debian
sudo apt update
sudo apt install python3 python3-pip python3-venv

# Install Python on CentOS/RHEL
sudo dnf install python38 python38-pip
```

### Permission Denied

```bash
# Fix ownership
sudo chown -R $USER:$USER /opt/kalshi-latency-bot

# Fix .env permissions
chmod 600 /opt/kalshi-latency-bot/.env
```

### Service Won't Start

```bash
# Check service status
sudo systemctl status kalshi-bot

# View detailed logs
sudo journalctl -u kalshi-bot -n 50 --no-pager

# Test manual run
cd /opt/kalshi-latency-bot
source venv/bin/activate
python kalshi_latency_bot.py --dry-run 2>&1 | head -50
```

### No Price Feeds

Ensure your VPS can reach the exchanges:

```bash
# Test Binance
curl -I https://stream.binance.com:9443

# Test Coinbase
curl -I https://ws-feed.exchange.coinbase.com

# Test Kraken
curl -I https://ws.kraken.com
```

### Firewall Issues

```bash
# UFW (Ubuntu)
sudo ufw allow out 443/tcp
sudo ufw allow out 9443/tcp

# firewalld (CentOS)
sudo firewall-cmd --add-port=443/tcp --permanent
sudo firewall-cmd --add-port=9443/tcp --permanent
sudo firewall-cmd --reload
```

---

## Security Best Practices

1. **API Keys**: Never commit `.env` files to version control
2. **SSH Keys**: Use key-based authentication, disable password auth
3. **Firewall**: Only allow necessary outbound connections
4. **Updates**: Keep the OS and Python packages updated
5. **Monitoring**: Set up alerts for service failures
6. **Backups**: Regularly backup trade logs and performance data

---

## Updating the Bot

To update to a new version:

```bash
# Stop the service
sudo systemctl stop kalshi-bot

# Re-run deployment script
./deploy.sh user@your-vps

# Restart
sudo systemctl start kalshi-bot
```

Or manually:

```bash
ssh user@your-vps
cd /opt/kalshi-latency-bot
source venv/bin/activate

# Pull new files (if using git)
git pull

# Or copy new files
# scp new_files... user@vps:/opt/kalshi-latency-bot/

# Update dependencies
pip install -r requirements.txt --upgrade

# Restart
sudo systemctl restart kalshi-bot
```

---

## Support

For issues:
1. Check logs: `tail -f /opt/kalshi-latency-bot/logs/bot.log`
2. Run in dry-run mode to test: `python kalshi_latency_bot.py --dry-run`
3. Verify API credentials are correct
4. Ensure network connectivity to exchanges and Kalshi

---

**⚠️ Risk Warning**: This is algorithmic trading software. Always start with small position sizes and use dry-run mode extensively before live trading. Past performance does not guarantee future results.
