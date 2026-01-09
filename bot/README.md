# Polymarket Hybrid Bot

A production-grade automated trading bot for Polymarket CLOB implementing a hybrid A+B strategy:

- **A) Lag Arbitrage**: Take aggressive orders when fair price significantly differs from market price
- **B) Market Making**: Provide liquidity around fair price with inventory-based skewing

## Architecture

The bot uses a clean, modular architecture:

```
Feeds → Strategy → Intents → Risk → Execution → State
```

- **Feeds**: WebSocket clients for orderbook and spot price data
- **Strategy**: Fair price calculation, lag arb, market making, and hybrid routing
- **Risk**: Comprehensive risk limits, rate limiting, and kill switch
- **Execution**: CLOB client wrapper and order management
- **State**: SQLite persistence for orders, fills, positions, and PnL

## Features

✅ **Dual Strategy**: Combines lag arbitrage (taker) with market making (maker)
✅ **Fair Price Model**: Normal CDF or logistic probability calculation
✅ **Inventory Management**: Automatic position skewing to avoid getting stuck
✅ **Risk Controls**: Position limits, notional limits, rate limits, daily loss limits
✅ **Kill Switch**: Emergency shutdown with order cancellation
✅ **PnL Tracking**: Real-time realized and unrealized PnL
✅ **Interactive CLI**: Manual control and inspection via command menu
✅ **Balance Checker**: Real-time USDC/MATIC balance verification
✅ **Allowance Manager**: Token approval tracking and management
✅ **Dual Modes**: Automated trading or interactive manual control
✅ **Dry-Run Mode**: Test without real money
✅ **Structured Logging**: Comprehensive logging with configurable levels
✅ **State Persistence**: SQLite database for all trading activity

## Prerequisites

- Python 3.9+
- Polygon wallet with USDC (for live trading)
- Private key for signing transactions

## Installation

1. **Clone the repository**:
```bash
cd bot
```

2. **Create virtual environment**:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies**:
```bash
pip install -r requirements.txt
```

4. **Configure environment**:
```bash
cp .env.example .env
# Edit .env with your settings
```

## Configuration

### Critical Settings

Edit `.env` before running:

1. **DRY_RUN**: Set to `1` for simulation, `0` for live trading
2. **PRIVATE_KEY**: Your Polygon wallet private key (REQUIRED for live trading)
3. **KILL_SWITCH**: Emergency stop (set to `1` to disable all trading)

### Strategy Parameters

- `MAKER_HALF_SPREAD`: Distance from fair price for quotes (default: 0.01 = 1¢)
- `TAKER_EDGE_THRESHOLD`: Minimum edge to trigger aggressive order (default: 0.03 = 3¢)
- `QUOTE_REFRESH_TTL_MS`: How often to refresh quotes (default: 3000ms)
- `INVENTORY_SKEW_FACTOR`: Position-based quote adjustment (default: 0.0001)

### Risk Limits

- `MAX_NOTIONAL_PER_MARKET`: Maximum $ exposure per market (default: $100)
- `MAX_INVENTORY_PER_TOKEN`: Maximum position size (default: 500 shares)
- `MAX_OPEN_ORDERS_TOTAL`: Maximum concurrent orders (default: 10)
- `MAX_ORDERS_PER_MIN`: Rate limit (default: 30/min)
- `MAX_DAILY_LOSS`: Daily loss limit triggering kill switch (default: $50)

## Market Configuration

Edit `markets.json` to define markets to trade:

```json
{
  "markets": [
    {
      "slug": "btc-above-100k-by-march-2026",
      "strike": 100000.0,
      "expiry_ts": 1740787200,
      "yes_token_id": "0x...",
      "no_token_id": "0x...",
      "tick_size": 0.01,
      "min_size": 1.0
    }
  ]
}
```

## Running the Bot

The bot supports **two modes**:
1. **Automated Mode**: Fully automated trading with hybrid A+B strategy
2. **Interactive Mode**: Manual control via command-line interface

### Quick Start with Launcher

```bash
# Automated mode (default)
python run.py

# Interactive CLI mode
python run.py --interactive
# or
python run.py --mode interactive
```

### Automated Mode (Continuous Trading)

**Dry-Run Mode (Recommended First)**

Test without real money:

```bash
# Ensure DRY_RUN=1 in .env
python run.py
# or
python -m src.app
```

The bot will:
- Log all decisions and orders
- NOT place real orders
- Use simulated orderbook data

**Live Trading**

⚠️ **WARNING: Live trading uses real money!**

1. Verify configuration:
   - Set `DRY_RUN=0` in `.env`
   - Add your `PRIVATE_KEY`
   - Review all risk limits

2. Start with small limits:
   ```bash
   MAX_NOTIONAL_PER_MARKET=10.0
   MAX_INVENTORY_PER_TOKEN=50.0
   ```

3. Run the bot:
   ```bash
   python run.py
   ```

4. Monitor logs carefully:
   ```bash
   tail -f bot.log  # if LOG_FILE is set
   ```

### Interactive Mode (Manual Control)

The interactive CLI provides a menu-driven interface for manual operations:

```bash
python run.py --interactive
```

**Available Commands:**
- **Check Balances**: View USDC and MATIC wallet balances
- **Check Allowances**: View and set token approvals
- **View Positions**: See current open positions
- **View Open Orders**: List active orders
- **View PnL**: Display profit/loss summary
- **List Markets**: Show available markets
- **View Market Details**: Get info about specific markets
- **Place Order**: Manual order placement
- **Cancel Order**: Cancel specific orders

Interactive mode is perfect for:
- Checking balances before starting automated trading
- Manually managing positions
- Inspecting bot state and activity
- Learning the system without automated trading

## Testing

Run unit tests:

```bash
pytest -v
```

Run specific test modules:

```bash
pytest tests/test_fair_price.py -v
pytest tests/test_inventory_skew.py -v
pytest tests/test_risk_engine.py -v
```

## Safety Features

### Kill Switch

The bot includes multiple safety mechanisms:

1. **Manual Kill Switch**: Set `KILL_SWITCH=1` in `.env` or environment
2. **Daily Loss Limit**: Automatically activates kill switch if losses exceed threshold
3. **Emergency Shutdown**: All kill switch activations cancel all open orders

When kill switch activates:
- ❌ All new trading blocked
- ❌ All open orders cancelled
- ✅ Bot continues running but idle
- ✅ Positions remain unchanged

### Feed Staleness

If market data becomes stale (>2s old by default):
- ⚠️ Bot cancels all orders
- ⚠️ No new orders placed until data fresh

### Risk Limits

All limits are enforced before order placement:
- Position limits per token
- Notional limits per market
- Open order limits
- Order rate limits

## Docker Deployment

Build and run with Docker:

```bash
cd docker
docker build -t polymarket-bot .
docker run -it --env-file ../.env polymarket-bot
```

Or use docker-compose:

```bash
docker-compose up -d
docker-compose logs -f
```

## Project Structure

```
bot/
├── src/
│   ├── models.py              # Data models
│   ├── config.py              # Configuration loader
│   ├── market_registry.py     # Market definitions
│   ├── cli.py                 # Interactive CLI
│   ├── app.py                 # Main orchestrator (automated)
│   ├── feeds/
│   │   ├── polymarket_ws.py   # Orderbook WebSocket
│   │   └── spot_ws.py         # Spot price WebSocket
│   ├── strategy/
│   │   ├── fair_price.py      # Fair probability calculation
│   │   ├── lag_arb.py         # Lag arbitrage strategy
│   │   ├── market_maker.py    # Market making strategy
│   │   └── hybrid_router.py   # Strategy orchestration
│   ├── risk/
│   │   ├── limits.py          # Risk limit definitions
│   │   ├── kill_switch.py     # Emergency kill switch
│   │   └── risk_engine.py     # Risk enforcement
│   ├── execution/
│   │   ├── clob_client.py     # CLOB API wrapper
│   │   ├── order_manager.py   # Order reconciliation
│   │   └── rate_limiter.py    # Rate limiting
│   ├── utils/
│   │   ├── balance_checker.py # USDC/MATIC balance checker
│   │   └── allowance_manager.py # Token approval manager
│   └── state/
│       ├── db.py              # Database initialization
│       ├── repositories.py    # Data repositories
│       └── pnl.py             # PnL tracking
├── tests/
│   ├── test_fair_price.py
│   ├── test_inventory_skew.py
│   └── test_risk_engine.py
├── run.py                     # Launcher (automated or interactive)
├── markets.json               # Market registry
├── requirements.txt
├── .env.example
└── README.md
```

## How It Works

### 1. Fair Price Calculation

For markets like "BTC above $100k by date T":

- **Input**: Spot price, strike, time to expiry, volatility
- **Model**: Normal CDF: `p_fair = Φ(z)` where `z = (spot - strike) / (σ * √τ)`
- **Output**: Fair YES probability

### 2. Strategy Logic

**Lag Arbitrage (A)**:
- Calculate `edge = p_fair - p_market`
- If `|edge| >= TAKER_EDGE_THRESHOLD`: place aggressive order
- Direction: Buy YES if edge > 0, sell YES if edge < 0

**Market Making (B)**:
- Calculate inventory skew: `skew = -position / max_inventory * factor`
- Adjust center: `p_center = p_fair + skew`
- Place quotes: `bid = p_center - spread`, `ask = p_center + spread`

**Hybrid Routing**:
- Priority 1: If strong taker edge → emit taker intent
- Priority 2: Otherwise → emit maker intents (bid/ask)

### 3. Execution Flow

1. **Generate Intents**: Strategy creates desired trades
2. **Risk Check**: Each intent validated against all limits
3. **Reconcile**: Compare intents with open orders
4. **Execute**: Place/cancel/replace orders as needed
5. **Persist**: Log all decisions and state to database

### 4. Position Management

- **Average Cost Basis**: Tracks entry prices for PnL
- **Realized PnL**: Calculated on each fill
- **Unrealized PnL**: Marked-to-market with current mid
- **Inventory Skew**: Adjusts quotes to rebalance position

## Monitoring

### Logs

The bot outputs structured logs:

```
2026-01-09 10:00:00.123 [INFO] app:run_iteration:234 - Loop complete: 2 intents, 2 open orders, PnL=5.23 (realized=3.45, unrealized=1.78)
```

Set `LOG_LEVEL=DEBUG` for verbose output.

### Database

Query the SQLite database:

```sql
-- View recent fills
SELECT * FROM fills ORDER BY ts DESC LIMIT 10;

-- View positions
SELECT * FROM positions WHERE qty != 0;

-- View decisions
SELECT * FROM decisions ORDER BY ts DESC LIMIT 20;
```

## Extending the Bot

### Real Market Data

Replace simulated feeds with real WebSocket clients:

**Polymarket orderbook**: Use the real `PolymarketBookFeed` (already implemented)

**Spot prices**: Implement `BinanceSpotFeed` or your preferred data source:

```python
# In src/app.py
self.spot_feed = BinanceSpotFeed(symbols=["BTCUSDT", "ETHUSDT"])
```

### Market Discovery

For automatic market discovery, replace the JSON registry with API calls to Polymarket's market endpoints.

### Custom Strategies

Add new strategies by:
1. Creating a new module in `src/strategy/`
2. Implementing intent generation logic
3. Adding to `HybridRouter`

## Troubleshooting

### Orders not placing

- ✅ Check `DRY_RUN=0` for live trading
- ✅ Verify `PRIVATE_KEY` is set
- ✅ Check risk limits aren't exceeded
- ✅ Ensure kill switch is off (`KILL_SWITCH=0`)

### Kill switch activated

Check logs for reason:
- Daily loss limit exceeded?
- Manual activation in config?

Reset by setting `KILL_SWITCH=0` and restarting.

### Rate limited

Reduce `MAX_ORDERS_PER_MIN` or increase `QUOTE_REFRESH_TTL_MS`.

## Disclaimer

**⚠️ USE AT YOUR OWN RISK ⚠️**

This bot is for educational purposes. Trading involves substantial risk of loss. Past performance is not indicative of future results.

- Always test in dry-run mode first
- Start with small position limits
- Monitor the bot continuously
- Understand all code before running
- Never share your private key

## License

MIT License - see LICENSE file for details.

## Support

For issues or questions:
- Review logs and database
- Check configuration settings
- Test with dry-run mode
- Review risk limits

---

**Happy trading! But trade responsibly. 🎯**
