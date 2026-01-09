# Aggressive Trading Guide - Fast Gains Mode

Configuration for maximum trading velocity and rapid profit accumulation.

⚠️ **HIGH RISK / HIGH REWARD** - Read completely before using!

## Quick Start

```bash
# 1. Use aggressive config
cp .env.aggressive .env

# 2. Add your private key
nano .env

# 3. Ensure you have enough MATIC
python run.py --interactive
# Check: Need 30+ MATIC for gas

# 4. Test in dry-run (12-24 hours minimum)
python run.py

# 5. Go live
# Set DRY_RUN=0 in .env
python run.py
```

## What Makes This Aggressive

### Comparison: Conservative vs Aggressive

| Setting | Conservative | **Aggressive** | Impact |
|---------|--------------|----------------|--------|
| Maker spread | 1.5¢ | **0.8¢** | 2-3x more fills |
| Taker edge | 4¢ | **2.5¢** | More opportunities |
| Max per market | $15 | **$30** | Higher exposure |
| Max orders | 4 | **8** | More market coverage |
| Daily loss | $5 | **$15** | More risk tolerance |
| Loop speed | 500ms | **200ms** | Faster reactions |
| Quote refresh | 3s | **1.5s** | Stay competitive |

### Trading Velocity

**Conservative:**
- ~10-20 fills/day
- $50-100 volume/day
- $1-3 profit/day

**Aggressive:**
- ~30-60 fills/day
- $200-400 volume/day
- **$3-10 profit/day**

## Expected Performance

### Best Case Scenario ✅

**Daily:**
- Volume: $300-500
- Gross: $8-12 (2-3%)
- Gas: ~$1.50
- **Net: $6-10/day**

**Weekly:**
- **$40-70 profit**
- 40-70% weekly ROI

**Monthly:**
- Could **2x account ($100 → $200) in 2-4 weeks**
- Then compound to $400+ by month 2

### Realistic Scenario (More Likely)

**Daily:**
- Volume: $200-300
- Gross: $4-8
- Gas: ~$1.50
- **Net: $2.50-6.50/day**

**Monthly:**
- $75-200 profit
- 75-200% monthly ROI
- $100 → $175-300 in Month 1

### Worst Case Scenario ⚠️

**Bad Day:**
- Hit $15 daily loss limit
- High gas costs
- Poor market conditions

**Bad Week:**
- -$30 to -$50 loss
- Multiple bad days
- Need to pause and reassess

**Risk of Ruin:**
- With aggressive trading, could lose 30-50% of account in bad week
- Must be prepared to stop and adjust

## Account Requirements

### Minimum Setup

**For Aggressive Trading:**
- **$100 USDC** (trading capital)
- **30 MATIC** (~$30 for gas)
- **Total: $130 minimum**

### Why More MATIC?

Aggressive trading = more orders:
- 30-50 orders/day vs 10-20
- 1.5-2.5 MATIC/day vs 0.5-1
- Need buffer for spikes

**Gas Reserve Strategy:**
- Start with 30 MATIC
- Replenish when below 20
- Don't let MATIC run below 10

## Strategy Explained

### 1. Tight Spreads (0.8¢)

**Goal:** Maximize fill rate

```
Market mid: $0.50
Your bid:   $0.496 (0.4¢ below mid)
Your ask:   $0.504 (0.4¢ above mid)
Spread:     0.8¢ total
```

**Result:**
- You're almost always best bid/ask
- High probability of fills
- Lower profit per trade BUT more trades

### 2. Low Edge Threshold (2.5¢)

**Goal:** Take more opportunities

```
Fair price: $0.53
Market:     $0.505
Edge:       2.5¢ → TAKE IT!
```

**Conservative would skip (needs 4¢)**

**Result:**
- 2x more taker opportunities
- More aggressive when edge appears
- Capture smaller mispricings

### 3. Fast Rebalancing

**Goal:** Never get stuck on one side

```
Position: Long 50 shares
Skew:     -0.01 (shifts quotes down)
Result:   Ask becomes more aggressive
          Quickly sells out of position
```

**Result:**
- Inventory turns over faster
- Less directional risk
- More trading opportunities

### 4. Multiple Markets (3-4)

**Goal:** Always have action

```
Market 1: $30 position (BTC)
Market 2: $25 position (ETH)
Market 3: $20 position (SOL)
Total:    $75 exposure
```

**Result:**
- Diversification
- More opportunities per hour
- Higher total volume

## Risk Management

### Daily Loss Limit ($15)

**Purpose:** Stop bad days from wiping account

**What happens:**
- Bot hits -$15 for the day
- Kill switch activates
- All orders cancelled
- Trading stops

**Action Required:**
- Review what went wrong
- Check if fair pricing was accurate
- Decide to continue or adjust
- Manually restart next day

### Position Sizing ($30/market)

**Max Exposure:**
```
3 markets × $30 = $90 exposure
Buffer:           $10 cash
Total:            $100 account
```

**Risk:**
- If all 3 markets move against you by 10%
- Loss = $90 × 10% = $9
- Still within daily loss limit

### Emergency Stop Conditions

**Auto-stop if:**
1. Daily loss hits $15
2. MATIC balance below 5 MATIC
3. Feed data stale >2 seconds
4. Manual kill switch activation

**Manual stop if:**
1. Unusual market behavior
2. Your fair pricing seems off
3. Getting adversely selected consistently
4. Gas costs exceeding profits

## Optimization Guide

### After First Week

**Analyze Performance:**

```sql
-- Check your stats
sqlite3 bot_aggressive.db

-- Daily PnL
SELECT DATE(ts/1000, 'unixepoch') as date,
       COUNT(*) as fills,
       SUM(CASE WHEN side='BUY' THEN -size*price ELSE size*price END) as pnl,
       SUM(fee) as gas_cost
FROM fills
GROUP BY date
ORDER BY date DESC;

-- Win rate by market
SELECT token_id,
       COUNT(*) as trades,
       AVG(size*price) as avg_trade_size,
       SUM(CASE WHEN side='BUY' THEN -size*price ELSE size*price END) as pnl
FROM fills
GROUP BY token_id;
```

**If Profitable (+$20+/week):**
- ✅ Keep settings
- Consider adding 4th market
- Slightly tighten spread to 0.007¢

**If Break-Even ($0-10/week):**
- Widen spread to 0.01¢
- Reduce to 2 markets
- Increase edge threshold to 0.03¢

**If Losing (-$10+/week):**
- 🔴 STOP and switch to conservative config
- Review fair pricing logic
- Check if markets are too volatile
- Consider different markets

### Gas Optimization

**If gas costs >30% of profits:**

```bash
# In .env, adjust:
QUOTE_REFRESH_TTL_MS=2500  # was 1500
MAX_ORDERS_PER_MIN=30      # was 40
LOOP_INTERVAL_MS=300       # was 200
```

**Trade-off:**
- Less responsive
- Fewer fills
- But much lower gas costs

### Market Selection

**Best Markets for Aggressive Trading:**

✅ **Good:**
- High volume (>$100k/day)
- Tight spreads (1-2¢)
- Liquid both sides
- Clear pricing (crypto-based)

❌ **Avoid:**
- Low volume (<$10k/day)
- Wide spreads (>5¢)
- One-sided markets
- Unclear fundamentals

**Example Good Markets:**
- BTC above X by date Y
- ETH above X by date Y
- Major election outcomes (high volume)

**Example Bad Markets:**
- Obscure sports events
- Low-volume political predictions
- Markets with one dominant side

## Scaling Strategy

### Week 1-2: Learn ($100)

**Goals:**
- Understand the system
- Verify profitability
- Tune parameters

**Metrics:**
- Daily fills: 30-60
- Daily net: $2-8
- Gas efficiency: <20% of gross

### Week 3-4: Compound ($150-200)

**Once account hits $150:**

```bash
# Scale proportionally
MAX_NOTIONAL_PER_MARKET=45.0  # was 30
MAX_DAILY_LOSS=22.5           # was 15
```

**New targets:**
- Daily net: $4-12
- Can now run 4 markets

### Month 2: Accelerate ($250-400)

**Once account hits $250:**

```bash
MAX_NOTIONAL_PER_MARKET=75.0
MAX_DAILY_LOSS=37.5
MAX_OPEN_ORDERS_TOTAL=12
```

**New targets:**
- Daily net: $8-20
- 5-6 markets simultaneously

### Month 3+: Scale or Diversify ($500+)

**Options:**

1. **Keep Compounding:**
   - Grow to $1000+
   - Increase position sizes
   - Add more markets

2. **Withdraw Profits:**
   - Take out original $100
   - Trade with profits only
   - Zero risk on initial capital

3. **Split Strategies:**
   - $250 aggressive
   - $250 conservative
   - Diversified approach

## Warning Signs

### Stop Trading If:

🔴 **Poor Fill Quality:**
- Getting filled only on bad side
- Always buying tops, selling bottoms
- Adverse selection >60% of time

**Action:** Fair pricing may be wrong

🔴 **Excessive Gas:**
- Gas costs >30% of gross profit
- MATIC depleting too fast

**Action:** Reduce frequency settings

🔴 **Consistent Losses:**
- 3+ days in a row negative
- Hitting daily loss limit repeatedly

**Action:** Switch to conservative or stop

🔴 **Market Conditions:**
- Extreme volatility
- No clear fair value
- Markets breaking down

**Action:** Pause until stable

## Daily Checklist

### Morning (Pre-Market)

```bash
python run.py --interactive
```

**Check:**
- [ ] USDC balance >$90
- [ ] MATIC balance >20
- [ ] No positions from overnight
- [ ] Logs show no errors
- [ ] Daily PnL reset to $0

### During Trading

**Monitor every 2-3 hours:**
- [ ] Fill rate reasonable (8-12/hour)
- [ ] PnL tracking upward
- [ ] Gas costs not excessive
- [ ] No stuck positions

### Evening (Post-Market)

```bash
# Review performance
tail -100 bot_aggressive.log

# Check PnL
python run.py --interactive
# Option 5: View PnL
```

**Record:**
- Daily fills: ___
- Gross profit: $___
- Gas costs: $___
- Net profit: $___
- Notes: ___________

## FAQ

### Q: Can I start with less than $100?

**A:** Not recommended with aggressive settings. Minimum $100 for:
- Proper position sizing
- Multiple markets
- Buffer for drawdowns

### Q: Should I run 24/7?

**A:** Depends on markets:
- US markets: Run during US hours only
- Crypto markets: Can run 24/7
- **Recommendation:** Start with limited hours, expand if profitable

### Q: What if I lose $50 in a week?

**A:**
1. STOP immediately
2. Switch to conservative config
3. Review ALL fills to understand why
4. May need to adjust fair pricing logic
5. Only restart after understanding issues

### Q: When should I take profits?

**A:**
- Week 1-2: Keep compounding
- Week 3-4: Consider taking 20-30%
- Month 2+: Take 50% out, trade with profits

### Q: How much can I realistically make?

**Conservative estimate:**
- Month 1: +$75-150 (75-150%)
- Month 2: +$150-300 (on larger base)
- Month 3: +$300-500

**Aggressive estimate (if skilled):**
- Month 1: +$150-300
- Month 2: +$400-800
- Month 3: +$800-1500

**Reality check:**
- Many will break even or lose initially
- Takes 2-4 weeks to optimize
- Not everyone succeeds at aggressive trading

## Final Warnings

⚠️ **This is NOT for beginners:**
- Start conservative first
- Learn the system
- Then switch to aggressive

⚠️ **You can lose faster:**
- Conservative loses slow
- Aggressive can lose $50 in bad week

⚠️ **Requires active monitoring:**
- Check 3-4x per day minimum
- Review logs daily
- Respond to issues quickly

⚠️ **Higher skill requirement:**
- Must understand fair pricing
- Need to optimize parameters
- Active market selection

## Success Checklist

✅ **Before going aggressive:**
- [ ] Ran conservative for 1+ week
- [ ] Understand the strategy
- [ ] Know how to read logs
- [ ] Can interpret database
- [ ] Have 30+ MATIC ready
- [ ] Comfortable with 15% daily loss risk
- [ ] Will monitor 3-4x per day
- [ ] Can handle the stress

If you checked all boxes → You're ready! 🚀

If not → Start conservative first, then upgrade later.

---

**Remember:** Aggressive = More reward AND more risk. Trade accordingly! ⚡
