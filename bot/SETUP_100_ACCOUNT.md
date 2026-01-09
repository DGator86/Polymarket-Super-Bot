# Setup Guide for $100 Account

Complete guide for running the Polymarket bot with a small account.

## Quick Setup

```bash
# 1. Copy optimized config
cp .env.100dollar .env

# 2. Add your private key to .env
nano .env  # or your preferred editor

# 3. Check balances first
python run.py --interactive
# Choose option 1: Check Balances

# 4. Test in dry-run (24-48 hours recommended)
python run.py

# 5. When ready, enable live trading
# Set DRY_RUN=0 in .env
python run.py
```

## Account Requirements

### Minimum Balances

- **USDC**: $100 (trading capital)
- **MATIC**: ~10-20 MATIC ($10-20) for gas fees
- **Total**: ~$110-120 to start safely

### Why MATIC is needed

Every order placement/cancellation costs gas:
- Order placement: ~0.01-0.05 MATIC
- Order cancellation: ~0.01-0.03 MATIC
- With 20-30 orders/day: ~1-2 MATIC/day

**Reserve at least 10 MATIC** to avoid running out mid-trading.

## Risk Configuration Explained

### Position Sizing (MAX_NOTIONAL_PER_MARKET=15)

```
$100 account → $15 max per market
```

**Reasoning:**
- 15% per market allows 6-7 markets maximum
- Prevents over-concentration
- Leaves buffer for price movements

**Start conservatively:**
- Week 1: Trade only 2 markets ($30 exposure)
- Week 2-3: Add 1-2 more markets
- Month 2+: Scale to 4-5 markets as comfortable

### Daily Loss Limit (MAX_DAILY_LOSS=5)

```
$5 daily loss = 5% of capital
```

**Purpose:**
- Protects against bad days
- Triggers kill switch automatically
- Prevents emotional decision-making

**What happens:**
- Bot cancels all orders
- Stops trading for the day
- Requires manual review and restart

### Inventory Limits (MAX_INVENTORY_PER_TOKEN=50)

```
50 shares @ $0.30 avg = $15 exposure ✓
50 shares @ $0.60 avg = $30 exposure ✗ (blocked by notional limit)
```

**Protection:**
- Prevents getting stuck in large positions
- Works with notional limit
- Adjusts based on average entry price

## Strategy Settings for Small Accounts

### Wider Spreads (MAKER_HALF_SPREAD=0.015)

```
Normal: 1¢ spread ($0.01)
Small account: 1.5¢ spread ($0.015)
```

**Why wider:**
- More profit per fill
- Compensates for smaller size
- Reduces wash trading risk

### Higher Edge Threshold (TAKER_EDGE_THRESHOLD=0.04)

```
Normal: 3¢ edge
Small account: 4¢ edge
```

**Why higher:**
- Be more selective with capital
- Only take best opportunities
- Reduce trading frequency/fees

### Lower Inventory Skew (INVENTORY_SKEW_FACTOR=0.00005)

```
Normal: 0.0001
Small account: 0.00005
```

**Why lower:**
- Less aggressive rebalancing
- Fewer unnecessary trades
- Lower gas costs

## Expected Performance

### Realistic Targets (Conservative)

**Daily:**
- Volume: $50-100 traded
- Gross profit: $1-3 (1-3%)
- Gas costs: ~$0.50-1.00
- Net profit: $0.50-2.00

**Monthly:**
- Net profit: $15-60
- ROI: 15-60% monthly
- Compounded: Could double in 2-4 months

### Break-Even Analysis

```
Fixed costs (gas): ~$15-20/month
Minimum profit needed: ~$20/month
Target: $30-50/month for safety margin
```

## Scaling Your Account

### Growth Milestones

**$100 → $150 (50% growth):**
```bash
# Update limits proportionally:
MAX_NOTIONAL_PER_MARKET=22.5  # was 15
MAX_DAILY_LOSS=7.5            # was 5
```

**$150 → $250:**
```bash
MAX_NOTIONAL_PER_MARKET=37.5
MAX_DAILY_LOSS=12.5
```

**$250 → $500:**
```bash
MAX_NOTIONAL_PER_MARKET=75.0
MAX_DAILY_LOSS=25.0
# Can now use standard settings
```

**$500+:**
```bash
# Use standard .env.example settings
MAX_NOTIONAL_PER_MARKET=100.0
MAX_DAILY_LOSS=50.0
```

## Pre-Flight Checklist

Before starting live trading:

### 1. Balance Verification ✓

```bash
python run.py --interactive
# Option 1: Check Balances
```

Verify:
- [ ] USDC ≥ $100
- [ ] MATIC ≥ 10 MATIC
- [ ] Balances show correctly

### 2. Allowance Setup ✓

```bash
# In interactive mode:
# Option 2: Check Allowances
```

Set unlimited allowance for convenience:
- [ ] USDC allowance set to unlimited (saves gas on future approvals)

### 3. Markets Configuration ✓

Edit `markets.json` - **Start with 1-2 markets only:**

```json
{
  "markets": [
    {
      "slug": "btc-above-100k-by-march-2026",
      "strike": 100000.0,
      "expiry_ts": 1740787200,
      "yes_token_id": "REAL_TOKEN_ID_HERE",
      "no_token_id": "REAL_TOKEN_ID_HERE"
    }
  ]
}
```

**How to find real token IDs:**
- Visit market on polymarket.com
- Check URL or use their API
- Verify token IDs are correct

### 4. Dry-Run Testing ✓

```bash
# Ensure DRY_RUN=1
python run.py
```

Monitor for 24-48 hours:
- [ ] Fair prices look reasonable
- [ ] Quotes are placed at sensible levels
- [ ] Inventory skewing works correctly
- [ ] Risk limits trigger appropriately
- [ ] No errors in logs

### 5. Go Live ✓

```bash
# Edit .env: DRY_RUN=0
python run.py
```

First hour monitoring:
- [ ] Orders placing successfully
- [ ] Fills executing correctly
- [ ] PnL tracking works
- [ ] Gas costs reasonable

## Monitoring Your Bot

### Daily Routine

**Morning (before market opens):**
```bash
python run.py --interactive
# Check: Balances, Positions, PnL
```

**Evening (after trading day):**
```bash
# Check positions and daily PnL
# Review logs for issues
tail -50 bot_100dollar.log
```

### Key Metrics to Track

**In Database:**
```bash
sqlite3 bot_100dollar.db
```

```sql
-- Daily PnL
SELECT DATE(ts/1000, 'unixepoch') as date,
       SUM(CASE WHEN side='BUY' THEN -size*price ELSE size*price END) as pnl
FROM fills
GROUP BY date
ORDER BY date DESC;

-- Fill rate
SELECT COUNT(*) as total_fills,
       AVG(size) as avg_size,
       SUM(fee) as total_fees
FROM fills
WHERE ts > (strftime('%s','now')-86400)*1000;
```

**Watch for:**
- Declining fill rate (may need to tighten spreads)
- Increasing gas costs (reduce order frequency)
- Growing inventory on one side (check skew settings)

## Troubleshooting

### Issue: Not Getting Fills

**Symptoms:**
- Open orders but no executions
- 0 fills per day

**Solutions:**
1. Reduce `MAKER_HALF_SPREAD` to 0.01
2. Lower `TAKER_EDGE_THRESHOLD` to 0.03
3. Check that market has actual volume
4. Verify your quotes are competitive

### Issue: Too Much Gas Usage

**Symptoms:**
- MATIC balance depleting fast
- High cancel/replace frequency

**Solutions:**
1. Increase `QUOTE_REFRESH_TTL_MS` to 3000-5000
2. Reduce `MAX_ORDERS_PER_MIN` to 15
3. Increase `LOOP_INTERVAL_MS` to 500-1000
4. Stick to 1-2 markets instead of 4+

### Issue: Getting Stuck Long/Short

**Symptoms:**
- Large position on one side
- Can't rebalance inventory

**Solutions:**
1. Increase `INVENTORY_SKEW_FACTOR` to 0.0001
2. Check that fair price calculation is correct
3. Manually close position via interactive mode
4. Reduce position size limits

### Issue: Hit Daily Loss Limit

**Symptoms:**
- Kill switch activated
- Bot stopped trading

**Action:**
1. Review logs to understand what happened
2. Check if fair price model was correct
3. Verify market conditions weren't unusual
4. Consider if `MAX_DAILY_LOSS` too tight
5. Reset by restarting bot (kill switch clears)

## Advanced: Optimizing for Your Account

After 1-2 weeks of trading data:

### Analyze Your Performance

```sql
-- Win rate by market
SELECT token_id,
       COUNT(*) as trades,
       AVG(CASE WHEN side='BUY' THEN price ELSE 1-price END) as avg_entry,
       SUM(CASE WHEN side='BUY' THEN -size*price ELSE size*price END) as pnl
FROM fills
GROUP BY token_id;
```

### Tune Parameters

**If making good profits:**
- Tighten spreads (0.015 → 0.012)
- Lower edge threshold (0.04 → 0.035)
- Add another market

**If too many losses:**
- Widen spreads (0.015 → 0.02)
- Raise edge threshold (0.04 → 0.05)
- Reduce to 1 market and debug

**If not enough fills:**
- Tighten spreads (0.015 → 0.01)
- Increase position sizes slightly
- Check market selection

## Safety Reminders

🔴 **NEVER:**
- Trade with money you can't afford to lose
- Ignore the kill switch when it activates
- Override risk limits without understanding why
- Run on markets you don't understand

🟢 **ALWAYS:**
- Start in dry-run mode
- Monitor daily for first 2 weeks
- Keep MATIC reserve for gas
- Back up your database weekly
- Review logs when things seem off

## Support

If you run into issues:

1. Check logs: `tail -100 bot_100dollar.log`
2. Review database: `sqlite3 bot_100dollar.db`
3. Test in interactive mode: `python run.py -i`
4. Restart in dry-run to debug

Good luck with your $100 account! 🚀
