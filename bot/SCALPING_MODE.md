# Scalping Mode - Breaking Feed Speed

Ultra-fast configuration matching the 1-2 minute trading frequency seen in Polymarket's Breaking feed.

⚡ **ULTRA HIGH FREQUENCY** - This is the fastest possible mode!

## What You're Seeing in Breaking Feed

**Activity Pattern:**
```
1 min ago: Sell ETH Down 97¢, 16 shares = $15.52
1 min ago: Buy BTC Down 53¢, 6.3 shares = $3.35
2 min ago: Buy BTC Down 53¢, 19 shares = $10.07
2 min ago: Buy BTC Up 44¢, 10.1 shares = $4.42
```

**This means:**
- New fills every 60-120 seconds
- Large price swings (44¢ to 97¢!)
- Quick position flips
- Both BUY and SELL within minutes
- Total positions: $3-32 per trade

## Scalping Configuration

### Speed Settings

```bash
LOOP_INTERVAL_MS=100          # Check every 0.1 seconds!
QUOTE_REFRESH_TTL_MS=1000     # Update quotes every 1 second
MAX_ORDERS_PER_MIN=60         # Up to 60 orders/minute
MAKER_HALF_SPREAD=0.005       # 0.5¢ spread (tightest possible)
TAKER_EDGE_THRESHOLD=0.015    # Take edges at 1.5¢+
```

### Position Sizing

```bash
MAX_NOTIONAL_PER_MARKET=40.0  # $40 per market
MAX_INVENTORY_PER_TOKEN=150   # 150 shares max
MAX_OPEN_ORDERS_TOTAL=12      # 12 concurrent orders
MAX_DAILY_LOSS=20.0           # $20 daily loss limit (20%)
```

## Quick Start

```bash
# 1. Copy scalping config
cp .env.scalper .env

# 2. Add private key
nano .env

# 3. CHECK YOUR MATIC - YOU NEED 50+!
python run.py --interactive
# Option 1: Check Balances

# 4. Configure short-term markets in markets.json
# Focus on: BTC/ETH Up or Down [Today/This Hour]

# 5. Dry-run test (6-12 hours minimum)
python run.py

# 6. Go live
# Set DRY_RUN=0
python run.py
```

## Account Requirements

### Minimum Setup

**For Scalping:**
- **$100 USDC** (minimum trading capital)
- **50 MATIC** (~$50 for gas) - NOT NEGOTIABLE
- **Total: $150 minimum**

**Recommended:**
- **$200 USDC** (better buffer)
- **75 MATIC** ($75 gas reserve)
- **Total: $275** for comfortable scalping

### Why So Much MATIC?

**Gas Cost Breakdown:**
```
Orders per day: 50-100
MATIC per order: 0.02-0.05
Daily cost: 2.5-5 MATIC = $2.50-5.00/day
Weekly cost: 17.5-35 MATIC = $17.50-35/week
```

**If you run out of MATIC:**
- Bot stops mid-session
- Can't cancel orders
- Stuck in bad positions
- Emergency situation

**50 MATIC gives you:**
- 10-20 days of runtime
- Buffer for high-activity periods
- Safety margin

## Target Markets

### Best Markets for Scalping

**Short-Term Binary:**
- ✅ BTC Up or Down - [Today at 7AM ET]
- ✅ ETH Up or Down - [Today at 7AM ET]
- ✅ Crypto Above/Below X by [Today/This Week]
- ✅ High-volume event outcomes (hourly/daily)

**Characteristics:**
- Short duration (hours, not days)
- High volatility
- Large price swings (20¢-$1 movements)
- Liquid both sides
- Clear, real-time pricing reference

**Avoid:**
- Long-term markets (weeks/months)
- Low-volume (<$50k total)
- Unclear pricing
- One-sided markets

### Example markets.json for Scalping

```json
{
  "markets": [
    {
      "slug": "btc-up-or-down-jan-9-7am-et",
      "strike": null,
      "expiry_ts": 1704798000,
      "yes_token_id": "REAL_TOKEN_ID_1",
      "no_token_id": "REAL_TOKEN_ID_2",
      "tick_size": 0.01,
      "min_size": 0.1
    },
    {
      "slug": "eth-up-or-down-jan-9-7am-et",
      "strike": null,
      "expiry_ts": 1704798000,
      "yes_token_id": "REAL_TOKEN_ID_3",
      "no_token_id": "REAL_TOKEN_ID_4",
      "tick_size": 0.01,
      "min_size": 0.1
    }
  ]
}
```

## Expected Performance

### Best Case (Top 10% traders)

**Daily:**
- Fills: 60-100
- Volume: $600-1000
- Gross: $15-25 (15-25%!)
- Gas: $3-5
- **Net: $10-20/day**

**Weekly:**
- **$70-140/week**
- 70-140% weekly ROI

**Monthly:**
- Could **3x-5x account** ($100 → $300-500)

### Realistic Case (Average skilled trader)

**Daily:**
- Fills: 40-60
- Volume: $400-600
- Gross: $8-15
- Gas: $2-4
- **Net: $5-12/day**

**Weekly:**
- **$35-85/week**

**Monthly:**
- **$150-350 profit**
- 150-350% monthly ROI
- $100 → $250-450

### Worst Case (Poor execution/bad markets)

**Daily:**
- Fills: 20-40 (less activity)
- Hit daily loss limit ($20)
- High gas costs eating profits
- **Net: -$5 to +$2/day**

**Weekly:**
- **-$30 to +$10**
- Frustrating, unprofitable

**Month:**
- Could lose 30-50% of account
- Need to stop and reassess

## Trading Strategy

### How Scalping Works

**1. Spot Price Tracking**
```
BTC spot: $42,000
1 second later: $42,050 (+0.12%)
→ Market should move Up
→ Bot immediately buys Up side
```

**2. Rapid Quote Updates**
```
Every 1 second:
- Check spot price
- Recalculate fair value
- Update bid/ask
- If edge appears → TAKE IT
```

**3. Quick Position Flips**
```
0:00 - Buy UP at 52¢
0:30 - Spot pumps, price moves to 58¢
0:31 - Sell UP at 58¢
Profit: 6¢ × shares in 31 seconds
```

**4. Volume Accumulation**
```
Trade 1: +3¢
Trade 2: +2¢
Trade 3: -1¢ (small loss)
Trade 4: +5¢
Trade 5: +4¢
...
Total: 40 trades, +$12 net
```

### Position Management

**Entry:**
- Edge appears (1.5¢+)
- Take immediately
- Position size: 10-40 shares

**Hold:**
- Seconds to minutes (not hours!)
- Target: 2-10¢ profit
- Stop: 3-5¢ loss

**Exit:**
- Hit profit target → sell immediately
- Price reverses → cut loss
- Approaching expiry → flatten position

**Never:**
- Hold overnight
- Let losses run >5¢
- Freeze in losing position
- Ignore the bot alerts

## Monitoring Requirements

### Constant Vigilance Required

**Every 30-60 minutes:**
```bash
# Quick check
python run.py --interactive
# Options: 3 (positions), 4 (orders), 5 (PnL)
```

**Check for:**
- [ ] Stuck positions (>30 min old)
- [ ] PnL trending wrong direction
- [ ] Gas costs excessive
- [ ] Fill rate acceptable (8-15/hour)
- [ ] No errors in logs

### Real-Time Alerts

**Set up notifications for:**
- Daily loss approaching $15
- MATIC below 30
- No fills for 30+ minutes
- Large unrealized loss (>$5)

**How to monitor:**
```bash
# Terminal 1: Run bot
python run.py

# Terminal 2: Tail logs in real-time
tail -f bot_scalper.log | grep -E "(ERROR|WARNING|filled|PnL)"

# Terminal 3: DB queries every 5 min
watch -n 300 'sqlite3 bot_scalper.db "SELECT COUNT(*) FROM fills WHERE ts > (strftime('%s','now')-3600)*1000"'
```

## Performance Tracking

### Key Metrics

**Hourly Check:**
```sql
-- Fills in last hour
SELECT COUNT(*) as fills,
       SUM(size*price) as volume,
       AVG(size*price) as avg_trade
FROM fills
WHERE ts > (strftime('%s','now')-3600)*1000;

-- Should see: 8-15 fills/hour
```

**Daily Review:**
```sql
-- Today's performance
SELECT
  COUNT(*) as total_fills,
  SUM(CASE WHEN side='BUY' THEN -size*price ELSE size*price END) as pnl,
  SUM(fee) as gas_cost,
  AVG(size*price) as avg_size
FROM fills
WHERE ts > (strftime('%s','now')-86400)*1000;

-- Target: 40-60 fills, $5-15 PnL, <30% gas ratio
```

**Win Rate:**
```sql
-- Calculate win rate (approximate)
SELECT
  token_id,
  COUNT(*) as trades,
  AVG(CASE WHEN side='BUY' THEN price ELSE 1-price END) as avg_entry
FROM fills
GROUP BY token_id;

-- Need 55%+ win rate to profit with tight spreads
```

## Optimization

### After First Day

**If profitable (+$5+):**
- ✅ Continue
- Maybe tighten spread to 0.004¢
- Add 3rd market

**If break-even ($0-5):**
- 🟡 Review market selection
- Check if gas too high
- Verify fair pricing accurate

**If losing (-$5+):**
- 🔴 STOP
- Switch to aggressive mode
- Debug fair price calculation

### Tuning Parameters

**Too many fills, low profit:**
```bash
# Widen spreads slightly
MAKER_HALF_SPREAD=0.007  # was 0.005
```

**Too few fills:**
```bash
# Tighten spreads
MAKER_HALF_SPREAD=0.003  # was 0.005
# Lower edge threshold
TAKER_EDGE_THRESHOLD=0.01  # was 0.015
```

**Gas costs too high (>40% of gross):**
```bash
# Slow down
QUOTE_REFRESH_TTL_MS=2000  # was 1000
MAX_ORDERS_PER_MIN=40       # was 60
LOOP_INTERVAL_MS=200        # was 100
```

## Risk Management

### Circuit Breakers

**Auto-stop conditions:**
1. Daily loss hits $20 (20% of account)
2. MATIC below 10
3. Feed stale >1.5 seconds
4. Manual kill switch

**Manual stop if:**
1. 2+ hours with no fills
2. Consistent adverse selection
3. Fair pricing clearly wrong
4. Gas costs >50% of gross
5. 3+ bad trades in a row

### Position Limits

**Per Trade:**
- Max size: 40 shares
- Max notional: $40
- Max hold time: 30 minutes
- Max loss: $2 per trade

**Total Portfolio:**
- Max exposure: $80 (2 markets × $40)
- Max daily loss: $20
- Max open orders: 12

### Stress Scenarios

**Market Crashes:**
- If BTC drops 5% suddenly
- All your UP positions lose
- Could lose $10-15 instantly
- Daily loss limit saves you at $20

**Feed Latency:**
- Spot price lags 2+ seconds
- Your fair price wrong
- Get adversely selected
- Lose on every fill
- **Action:** Stop immediately if this happens

**Gas Price Spike:**
- Network congested
- Gas 3-5x normal
- Costs exceed profits
- **Action:** Reduce order frequency or pause

## Scaling Path

### Week 1: Learn ($100)

**Goals:**
- Understand rapid trading
- Get fill rhythm down
- Optimize parameters

**Targets:**
- Break-even to +$20
- 200-400 total fills
- Win rate 52%+

### Week 2-3: Profit ($120-180)

**Once profitable:**
- Add more capital or compound
- Scale to 3 markets
- Increase position sizes proportionally

**Targets:**
- +$40-80/week
- Scale to $150-200 account

### Month 2: Scale or Diversify ($250+)

**Options:**

**1. Full Scalp:**
- $250 all in scalping
- Increase limits 2.5x
- Target $15-30/day

**2. Split Strategy:**
- $125 scalping (fast money)
- $125 aggressive (steady growth)
- Diversified risk

**3. Take Profits:**
- Withdraw $150
- Trade with $100 profits only
- Risk-free trading

## Troubleshooting

### Issue: No Fills

**Symptoms:**
- Bot running but 0 fills per hour
- Orders placed but not executing

**Causes:**
1. Spreads too wide (not competitive)
2. Markets have no volume
3. Fair pricing way off market
4. Quotes not updating fast enough

**Solutions:**
- Tighten spreads to 0.003-0.004¢
- Switch to higher volume markets
- Verify spot price feed working
- Check loop is actually running

### Issue: All Losing Trades

**Symptoms:**
- Fills happening but every one loses money
- Adverse selection

**Causes:**
1. Fair pricing calculation wrong
2. Spot price feed lagged
3. Trading against informed flow
4. Wrong market type for strategy

**Solutions:**
- Debug fair price calculation
- Switch spot price source
- Use longer time horizon markets
- Switch to different strategy

### Issue: MATIC Depleting Fast

**Symptoms:**
- Started with 50 MATIC
- Down to 30 in 2 days

**Causes:**
- Too many orders (>80/day)
- Network gas prices high
- Inefficient order placement

**Solutions:**
- Reduce MAX_ORDERS_PER_MIN to 40
- Increase QUOTE_REFRESH_TTL to 2000ms
- Check Polygon gas prices (should be low)
- Consider pausing during high-gas periods

## Success Criteria

### Before Scalping

Check ALL:
- [ ] Have $150+ total ($100 USDC + 50 MATIC)
- [ ] Ran aggressive mode profitably for 1+ week
- [ ] Understand market dynamics deeply
- [ ] Can monitor constantly (every 30-60 min)
- [ ] Comfortable with 20% daily loss risk
- [ ] Have short-term markets to trade
- [ ] Spot price feeds working perfectly
- [ ] Can react to issues immediately

If ANY unchecked → NOT READY for scalping yet.

### Week 1 Goals

Minimum to continue:
- [ ] Net positive (even +$1 counts)
- [ ] Win rate >50%
- [ ] Gas costs <40% of gross
- [ ] No major technical issues
- [ ] Understanding why trades won/lost

If goals met → Continue and scale

If not → Drop back to aggressive mode

## Final Warning

### This Is NOT For Everyone

**Scalping requires:**
- ⚡ Expert skill level
- 👀 Constant attention
- 🧠 Deep market understanding
- 💪 Emotional control
- 💰 Larger capital base
- ⚙️ Technical competence

**Most traders should:**
- Start conservative
- Move to aggressive when profitable
- Only try scalping if crushing it

**Reality check:**
- 80% of scalpers lose money
- It's HARD to be profitable
- Requires perfect execution
- One mistake = day's profits gone

## Bottom Line

**Scalping Mode:**
- **Fastest possible** (Breaking feed speed)
- **Highest profit potential** (10-20%/day possible)
- **Highest risk** (20% daily loss possible)
- **Most expensive** ($2-5/day gas)
- **Most demanding** (constant monitoring)

**You wanted FAST?** This is **MAXIMUM SPEED**. ⚡⚡⚡

**Ready to scalp?**
```bash
cp .env.scalper .env
# Add PRIVATE_KEY
# Get 50+ MATIC
python run.py
```

**OR start slower and work up to it?** 🤔

Your choice! 🚀
