# Kalshi Super Prediction Bot

A multi-strategy automated trading system for Kalshi prediction markets with ML-powered paper trading validation.

## Features

- **Universe Engine**: Fast pre-filter eliminating 90% of markets before expensive computation
- **Multi-Strategy Support**: Value betting, latency arbitrage, multi-timeframe analysis
- **ML Volatility Forecasting**: GARCH-style volatility modeling with regime detection
- **Paper Trading**: Full simulation with ML feedback loop for strategy validation
- **Real-time Alerts**: Telegram and Discord notifications
- **Historical Database**: SQLite storage for trade history and analytics

## Architecture

```
Universe Engine → Data Connectors → Probability Engine → ML Predictor
                                          ↓
                     Strategy Layer → Risk Manager → Execution Engine
```

## Quick Start

### 1. Clone and Install

```bash
git clone https://github.com/DGator86/Super-Prediction-Bot.git
cd Super-Prediction-Bot
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your API credentials
```

### 3. Generate RSA Keys (for Kalshi auth)

```bash
openssl genrsa -out kalshi_private_key.pem 4096
openssl rsa -in kalshi_private_key.pem -pubout -out kalshi_public_key.pem
# Upload kalshi_public_key.pem to Kalshi dashboard
```

### 4. Run Paper Trading (Recommended First)

```bash
python3 run_paper_trading.py --capital 1000 --interval 60
```

### 5. Generate Reports

```bash
python3 generate_report.py --days 30 --format console
```

### 6. Run Live Trading

```bash
python3 main.py  # dry_run=True by default
```

## Project Structure

```
├── main.py                    # Live trading entry point
├── run_paper_trading.py       # Paper trading entry point
├── generate_report.py         # Report generation
├── config.py                  # Configuration
│
├── core/
│   ├── models.py              # Data models
│   ├── universe_engine.py     # Market filtering
│   ├── probability_engine.py  # Edge detection
│   ├── risk_manager.py        # Position sizing
│   └── ml_volatility.py       # Volatility forecasting
│
├── connectors/
│   ├── kalshi.py              # Kalshi API
│   ├── fred.py                # FRED economic data
│   ├── noaa.py                # Weather data
│   ├── coinbase.py            # Crypto prices
│   └── bls.py                 # BLS CPI data
│
├── strategies/
│   ├── latency_arb.py         # Latency arbitrage
│   └── multi_timeframe.py     # Multi-TF analysis
│
├── paper_trading/
│   ├── engine.py              # Paper trading simulation
│   ├── runner.py              # Paper trading orchestrator
│   └── analytics.py           # Performance analytics
│
├── ml/
│   └── predictor.py           # ML trade predictor
│
└── utils/
    ├── alerts.py              # Telegram/Discord alerts
    └── database.py            # Trade database
```

## Configuration

Key thresholds in `config.py`:

| Parameter | Value | Description |
|-----------|-------|-------------|
| Minimum edge | 5% | Filter marginal opportunities |
| Minimum liquidity | $50 | At best quote |
| Kelly fraction | 0.25x | Conservative sizing |
| Max position | 10% | Per market limit |
| Max daily loss | 5% | Circuit breaker |

## API Keys Required

- **Kalshi**: API key + RSA private key (required)
- **FRED**: https://fred.stlouisfed.org/docs/api/api_key.html
- **BLS**: https://www.bls.gov/developers/
- **Coinbase**: For crypto latency arb
- **Telegram/Discord**: For alerts (optional)

## Paper Trading Features

- Virtual portfolio with configurable capital
- Realistic fill simulation with slippage
- ML model trains on trade outcomes
- Edge calibration analysis
- Performance reports by category

## License

MIT License

## Disclaimer

This software is for educational purposes only. Trading prediction markets involves substantial risk of loss. Past performance does not guarantee future results.
