# Kalshi Arbitrage Bot - Deployment Guide

## Overview

The `kalshi_arbitrage_bot.py` is a standalone arbitrage detection system that scans for:
1. **Probability Arbitrage**: YES_ask + NO_ask < $1.00 (guaranteed profit)
2. **Spread Arbitrage**: Bid > Ask (instant profit by buy-sell)
3. **Cross-Platform Arbitrage**: Kalshi vs Polymarket price discrepancies

## Quick Start

### Local Testing
```bash
# Single scan with analysis
python3 kalshi_arbitrage_bot.py --analyze

# Continuous scanning (30-second intervals)
python3 kalshi_arbitrage_bot.py

# Custom settings
python3 kalshi_arbitrage_bot.py --interval 60 --min-profit 0.05
```

### VPS Deployment

1. **Copy files to VPS**:
```bash
scp kalshi_arbitrage_bot.py root@134.199.194.220:/opt/kalshi-latency-bot/
```

2. **Configure environment** (use existing .env from latency bot):
```bash
# On VPS, the bot uses the same credentials as latency bot
# Located at /opt/kalshi-latency-bot/.env
```

3. **Run the bot**:
```bash
# SSH into VPS
ssh root@134.199.194.220

# Activate venv and run
cd /opt/kalshi-latency-bot
source venv/bin/activate
python kalshi_arbitrage_bot.py --analyze  # Test scan
nohup python kalshi_arbitrage_bot.py >> logs/arbitrage.log 2>&1 &  # Background
```

4. **Create systemd service** (optional):
```bash
cat > /etc/systemd/system/kalshi-arbitrage.service << 'EOF'
[Unit]
Description=Kalshi Arbitrage Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/kalshi-latency-bot
ExecStart=/opt/kalshi-latency-bot/venv/bin/python kalshi_arbitrage_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable kalshi-arbitrage
systemctl start kalshi-arbitrage
```

## Configuration

Key settings in `kalshi_arbitrage_bot.py`:

```python
# Arbitrage thresholds
MIN_PROFIT_CENTS: int = 2      # Minimum profit per contract ($0.02)
MIN_PROFIT_PERCENT: float = 0.01  # 1% minimum margin
MAX_POSITION_SIZE: int = 100   # Max contracts per trade
MIN_LIQUIDITY: int = 100       # Minimum volume filter

# Scanning
SCAN_INTERVAL_SECONDS: int = 30
MAX_MARKETS_PER_SCAN: int = 1000
```

## Market Analysis Results (January 15, 2026)

### Current State of Kalshi Markets:
- **Total markets scanned**: 1,700 (1,000 general + 700 crypto)
- **Closest to arbitrage**: 1% gap (YES + NO = $1.01)
- **Pure arbitrage opportunities**: 0 (markets are well-arbitraged)

### Why No Pure Arbitrage?
- Kalshi has professional market makers maintaining tight spreads
- The ~1% gap equals their profit margin + fees
- True arbitrage opportunities are extremely rare and fleeting

### Best Opportunities Found:
1. **Tightest Spreads**: $0.01 on BTC markets (potential MM opportunity)
2. **Near-Arbitrage**: Markets at $1.01 total cost (1% from breakeven)

## External Repo Analysis

### 1. CarlosIbCu/polymarket-kalshi-btc-arbitrage-bot
**Logic Pattern**: Cross-platform scanner
- Fetches prices from both Polymarket and Kalshi
- Compares strike prices for overlapping coverage
- Alerts when total cost < $1.00

**Key Insight**: Focuses on BTC 1-hour markets only. Uses simple price comparison.

### 2. vladmeer/kalshi-arbitrage-bot
**Logic Pattern**: Internal Kalshi arbitrage
- Probability arbitrage: YES + NO < $1.00
- Spread trading: Bid > Ask

**Key Insight**: Professional fee calculation with tiered rates.

### 3. qoery-com/pmxt
**Logic Pattern**: Unified API library (like ccxt for prediction markets)
- Abstracts multiple platforms into single interface
- Useful for building cross-platform tools

**Key Insight**: Could use for cleaner multi-platform integration.

### 4. terauss/Polymarket-Kalshi-Arbitrage-bot (Rust)
**Logic Pattern**: High-performance scanner
- Same cross-platform logic but in Rust
- Potentially faster execution

**Note**: We built our own native implementation without copying code per user request.

## Polymarket Integration Status

- **Current**: Read-only client implemented
- **Issue**: No BTC hourly markets found (0 results)
- **Reason**: Polymarket may have different market structures or naming

### Next Steps for Cross-Platform:
1. Investigate Polymarket API for correct endpoints
2. Match market types between platforms
3. Consider adding bet105 for the Kalshi/bet105 arbitrage described in beginner's guide

## Files

| File | Purpose |
|------|---------|
| `kalshi_arbitrage_bot.py` | Main arbitrage scanner |
| `kalshi_latency_bot.py` | Latency-based trading bot |
| `check_account.py` | Account status checker |
| `find_hourly.py` | Hourly market finder |

## Architecture Comparison

### Latency Bot vs Arbitrage Bot

| Feature | Latency Bot | Arbitrage Bot |
|---------|-------------|---------------|
| Strategy | Price divergence from fair value | Cross-contract price gaps |
| Data source | Exchange price feeds | Kalshi orderbook only |
| Execution | Real-time, sub-second | Periodic scanning |
| Risk | Model-dependent | Risk-free (true arb) |
| Opportunity | Common (~100 signals/scan) | Rare (0-2/day) |

## Recommendations

1. **Run both bots**: They complement each other
2. **Monitor balance**: Current $0.40 cash limits trading
3. **Focus on latency bot**: More frequent opportunities
4. **Keep arbitrage bot scanning**: Catch rare opportunities when they appear
