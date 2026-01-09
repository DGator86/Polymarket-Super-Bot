# Polymarket Bot Deployment Guide

Complete guide to get your trading bot running on a DigitalOcean droplet.

## Prerequisites

- ✅ Termius (SSH access)
- ✅ DigitalOcean droplet
- ⏳ Polymarket account (we'll create this)
- ⏳ Wallet with funds

---

## Phase 1: Set Up Polymarket Account

### Step 1: Create Polymarket Account

1. **Go to**: https://polymarket.com
2. **Connect Wallet**: Click "Connect Wallet" (top right)
3. **Choose Wallet Type**:
   - **Option A (Recommended)**: Use Polymarket's built-in wallet (easier)
   - **Option B**: Connect existing MetaMask/WalletConnect wallet
4. **Save Your Credentials**:
   - If using Polymarket wallet: Save your seed phrase (12-24 words) SECURELY
   - If using MetaMask: You already have this

### Step 2: Fund Your Wallet

1. **Get Polygon USDC**:
   - Buy USDC on a CEX (Coinbase, Kraken, etc.)
   - Bridge to Polygon network using https://wallet.polygon.technology/
   - **OR** use Polymarket's built-in onramp

2. **Recommended Starting Amount**: $100-$500
   - Includes trading capital + gas fees (MATIC)

3. **Get MATIC for Gas**:
   - You need ~$5-10 worth of MATIC for transaction fees
   - Use Polygon faucet or bridge from exchange

### Step 3: Get API Credentials

Polymarket uses the CLOB (Central Limit Order Book) API:

1. **Go to**: https://docs.polymarket.com/#introduction
2. **Get API Key**:
   - Currently, Polymarket API doesn't require explicit API keys for most operations
   - You'll need your **private key** from your wallet

3. **Export Private Key**:

   **If using MetaMask:**
   - Click account icon → Account Details → Export Private Key
   - Enter password → Copy private key

   **If using Polymarket wallet:**
   - Settings → Security → Export Private Key
   - Copy and save securely

⚠️ **SECURITY WARNING**: Never share your private key! Anyone with it can drain your wallet.

---

## Phase 2: Set Up Your Droplet

### Step 1: Create/Access Droplet

**Recommended Specs:**
- **OS**: Ubuntu 22.04 LTS
- **Size**:
  - Conservative: 2GB RAM, 1 vCPU ($12/mo)
  - HFT Mode: 4GB RAM, 2 vCPU ($24/mo) - recommended
- **Region**: Choose closest to your location or:
  - **Best for latency**: NYC or San Francisco (close to US exchanges)

**Via DigitalOcean Dashboard:**
1. Create → Droplets
2. Choose Ubuntu 22.04
3. Choose plan (2GB+ RAM)
4. Add SSH key or use password
5. Create Droplet

### Step 2: Connect via Termius

1. Open Termius
2. Add new host:
   - **Alias**: Polymarket Bot
   - **Hostname**: Your droplet IP (from DigitalOcean)
   - **Username**: `root`
   - **Password/Key**: From droplet setup
3. Connect

### Step 3: Initial Server Setup

```bash
# Update system
apt update && apt upgrade -y

# Install essential tools
apt install -y python3.11 python3-pip git curl htop

# Install Python 3.11 (if not available)
apt install -y software-properties-common
add-apt-repository ppa:deadsnakes/ppa -y
apt update
apt install -y python3.11 python3.11-venv python3.11-dev

# Verify installation
python3.11 --version
```

---

## Phase 3: Deploy the Bot

### Step 1: Clone Repository

```bash
# Navigate to home directory
cd ~

# Clone the repository
git clone https://github.com/DGator86/Polymarket-Super-Bot.git
cd Polymarket-Super-Bot/bot

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 2: Configure Environment

```bash
# Copy example environment file
cp .env.100dollar .env

# Edit configuration
nano .env
```

**Required Configuration (paste into .env):**

```bash
# ===== EXECUTION SETTINGS =====
PRIVATE_KEY="your_private_key_here"  # From Step 3 of Phase 1
CHAIN_ID=137  # Polygon mainnet
CLOB_URL="https://clob.polymarket.com"
DRY_RUN=true  # Start with dry-run mode!

# ===== API CREDENTIALS (Optional) =====
# Most operations don't need these
API_KEY=""
API_SECRET=""
API_PASSPHRASE=""

# ===== RISK LIMITS ($100 Account) =====
MAX_NOTIONAL_PER_MARKET=15.0
MAX_INVENTORY_PER_TOKEN=150.0
MAX_OPEN_ORDERS_TOTAL=4
MAX_ORDERS_PER_MIN=20
MAX_DAILY_LOSS=5.0
MAX_TAKER_SLIPPAGE=0.02

# ===== STRATEGY SETTINGS =====
MAKER_HALF_SPREAD=0.015  # 1.5 cent spread
TAKER_EDGE_THRESHOLD=0.03  # 3 cent edge for aggressive orders
QUOTE_REFRESH_TTL_MS=3000  # 3 second quote TTL
INVENTORY_SKEW_FACTOR=0.0001
SIGMA_FLOOR=0.001

# ===== TIMING =====
LOOP_INTERVAL_MS=1000  # Check every 1 second
FEED_STALE_MS=2000

# ===== LOGGING =====
LOG_LEVEL=INFO
LOG_FILE=logs/bot.log

# ===== DATABASE =====
DB_PATH=data/polymarket_bot.db

# ===== MARKET REGISTRY =====
MARKET_REGISTRY_PATH=config/markets.json

# ===== WEB3 (For balance checking) =====
POLYGON_RPC_URL=https://polygon-rpc.com
```

**Save and exit**: Ctrl+X → Y → Enter

### Step 3: Create Market Registry

```bash
# Create config directory
mkdir -p config

# Create markets.json
nano config/markets.json
```

**Paste this template:**

```json
{
  "markets": [
    {
      "slug": "btc-100k-2025",
      "description": "Will Bitcoin reach $100k in 2025?",
      "strike": 100000,
      "expiry_ts": 1735689600,
      "yes_token_id": "0x...",
      "no_token_id": "0x...",
      "condition_id": "0x..."
    }
  ]
}
```

**To find real market data:**
1. Go to https://polymarket.com
2. Click on a market you want to trade
3. Use browser dev tools (F12) → Network → Look for API calls
4. Find token IDs in the responses

**Save and exit**: Ctrl+X → Y → Enter

### Step 4: Create Required Directories

```bash
# Create directories
mkdir -p logs data config

# Set permissions
chmod 700 .env  # Only owner can read private key
chmod -R 755 logs data config
```

---

## Phase 4: Test the Bot

### Step 1: Run Tests

```bash
# Activate virtual environment (if not already)
source venv/bin/activate

# Run unit tests
python -m pytest tests/ -v

# You should see: 16 passed
```

### Step 2: Run in Dry-Run Mode

```bash
# Start bot in dry-run mode (no real trades)
python -m src.app

# Watch the logs
# Press Ctrl+C to stop
```

**What to look for:**
- ✅ "Bot initialization complete"
- ✅ "Bot started"
- ✅ "Loop complete: X intents, Y open orders"
- ❌ Any errors about missing credentials or config

### Step 3: Check Interactive CLI

```bash
# Run interactive mode
python -m src.cli

# Available commands:
# 1. Check balances
# 2. Check allowances
# 3. View positions
# 4. View open orders
# 5. View PnL
# 6. List markets
# 7. Exit
```

---

## Phase 5: Go Live

### Step 1: Disable Dry-Run Mode

```bash
# Edit .env file
nano .env

# Change this line:
DRY_RUN=false  # Enable real trading

# Save and exit
```

### Step 2: Start Bot as Background Service

**Option A: Using screen (simple)**

```bash
# Install screen
apt install -y screen

# Start new screen session
screen -S polymarket-bot

# Run bot
cd ~/Polymarket-Super-Bot/bot
source venv/bin/activate
python -m src.app

# Detach from screen: Ctrl+A, then D
# Reattach later: screen -r polymarket-bot
# Kill session: screen -X -S polymarket-bot quit
```

**Option B: Using systemd (recommended for production)**

```bash
# Create service file
nano /etc/systemd/system/polymarket-bot.service
```

**Paste this:**

```ini
[Unit]
Description=Polymarket Trading Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/Polymarket-Super-Bot/bot
Environment="PATH=/root/Polymarket-Super-Bot/bot/venv/bin"
ExecStart=/root/Polymarket-Super-Bot/bot/venv/bin/python -m src.app
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Enable and start service:**

```bash
# Reload systemd
systemctl daemon-reload

# Enable service (start on boot)
systemctl enable polymarket-bot

# Start service
systemctl start polymarket-bot

# Check status
systemctl status polymarket-bot

# View logs
journalctl -u polymarket-bot -f
```

### Step 3: Monitor the Bot

```bash
# Watch logs in real-time
tail -f ~/Polymarket-Super-Bot/bot/logs/bot.log

# Check system resources
htop

# View service status
systemctl status polymarket-bot
```

---

## Phase 6: Configuration Profiles

Choose based on your risk tolerance:

### Conservative ($100 Account)
```bash
cp .env.100dollar .env
# Safe, slow growth
```

### Aggressive (Fast Gains)
```bash
cp .env.aggressive .env
# Higher risk, faster trades
```

### Scalper (1-2 min fills)
```bash
cp .env.scalper .env
# Very active trading
```

### HFT (Microsecond Precision)
```bash
cp .env.hft .env
# Maximum speed, requires good infrastructure
```

---

## Monitoring & Maintenance

### Check Bot Status

```bash
# View recent logs
tail -n 100 ~/Polymarket-Super-Bot/bot/logs/bot.log

# Check if bot is running
systemctl status polymarket-bot

# View real-time performance
python -m src.cli
```

### Update Bot

```bash
# Stop bot
systemctl stop polymarket-bot

# Pull latest changes
cd ~/Polymarket-Super-Bot
git pull origin main

# Install any new dependencies
cd bot
source venv/bin/activate
pip install -r requirements.txt --upgrade

# Restart bot
systemctl start polymarket-bot
```

### Emergency Stop

```bash
# Stop bot immediately
systemctl stop polymarket-bot

# Or if using screen:
screen -X -S polymarket-bot quit

# Or kill process:
pkill -f "python -m src.app"
```

### Check Performance

```bash
# View PnL and positions
python -m src.cli

# Check database
sqlite3 data/polymarket_bot.db "SELECT * FROM positions;"
sqlite3 data/polymarket_bot.db "SELECT * FROM fills ORDER BY timestamp DESC LIMIT 10;"
```

---

## Troubleshooting

### Issue: "Private key invalid"
- Check .env file has correct private key
- Remove "0x" prefix if present
- Ensure no extra spaces

### Issue: "Insufficient MATIC balance"
- Get more MATIC for gas fees
- Use Polygon faucet or bridge from exchange

### Issue: "Connection refused"
- Check internet connection
- Verify CLOB_URL is correct: https://clob.polymarket.com
- Try restarting bot

### Issue: "No active markets"
- Check markets.json has valid market data
- Verify expiry_ts is in future (Unix timestamp)
- Get fresh market data from Polymarket API

### Issue: "Rate limit exceeded"
- Reduce MAX_ORDERS_PER_MIN in .env
- Increase LOOP_INTERVAL_MS

### Issue: Bot keeps stopping
- Check logs: `tail -f logs/bot.log`
- Verify systemd service config
- Check for kill switch activation

---

## Security Checklist

- [ ] Private key stored securely in .env (chmod 700)
- [ ] .env file added to .gitignore (don't commit!)
- [ ] SSH key authentication enabled (not password)
- [ ] Firewall configured (UFW)
- [ ] Regular backups of .env and database
- [ ] Monitoring alerts set up
- [ ] Starting with dry-run mode
- [ ] Small account size for testing

---

## Performance Optimization

### For HFT Mode

```bash
# Use PyPy for better performance
apt install -y pypy3
pypy3 -m pip install -r requirements.txt

# Run with PyPy
pypy3 -m src.app
```

### Network Optimization

```bash
# Install and configure for low latency
sysctl -w net.ipv4.tcp_fin_timeout=15
sysctl -w net.ipv4.tcp_tw_reuse=1
```

### Move to Better Region

Consider droplets in regions closer to:
- NYC (Polymarket servers likely in US East)
- San Francisco (if West Coast)

---

## Next Steps

1. ✅ **Start in Dry-Run Mode** - Test for 24-48 hours
2. ✅ **Monitor Latency** - Check logs for performance metrics
3. ✅ **Verify Strategy** - Ensure intents match your expectations
4. ✅ **Go Live** - Enable real trading with small capital
5. ✅ **Scale Up** - Increase limits as you gain confidence

---

## Support

- **Documentation**: See README.md and other guides in repo
- **Logs**: Check `logs/bot.log` for detailed information
- **Database**: Use `sqlite3 data/polymarket_bot.db` to inspect state
- **Tests**: Run `pytest tests/ -v` to verify functionality

---

**Good luck trading! 🚀**
