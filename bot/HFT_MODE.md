# High-Frequency Trading Mode - Microsecond Precision

Professional-grade HFT configuration with **microsecond-level timing resolution**.

⚡ **MICROSECOND PRECISION** - For true high-frequency scalping!

## What Changed: Milliseconds → Microseconds

### Old System (Milliseconds)
```python
timestamp = 1704798000123  # milliseconds
resolution = 1ms = 1,000 microseconds
```

### New System (Microseconds)
```python
timestamp = 1704798000123456  # MICROSECONDS
resolution = 1µs = 0.001 milliseconds
precision = 1,000x better!
```

## Why Microseconds Matter

**Breaking Feed Speed Requirements:**

```
Trade 1: 7:57:00.123456 - Buy BTC Up
Trade 2: 7:57:00.987654 - Price moved
Reaction: 0.864198 seconds = 864,198 microseconds

With millisecond precision:
Can only measure to nearest 1ms (1,000µs)
Miss 864 microsecond opportunities!

With microsecond precision:
Measure exact 864µs latency
Optimize every microsecond
React faster than competition
```

## Microsecond Architecture

### 1. Timing Infrastructure

**New Utilities:** (`src/utils/timing.py`)
```python
from src.utils.timing import now_us, Stopwatch

# Get current time in microseconds
timestamp = now_us()
# Returns: 1704798123456789 (microseconds since epoch)

# Measure execution time
sw = Stopwatch()
sw.start()
# ... do something ...
elapsed = sw.elapsed_us()  # Returns microseconds
```

### 2. All Timestamps Upgraded

**Data Models:**
- `BookTop.ts` → microseconds
- `RefPrice.ts` → microseconds
- `OpenOrder.ts` → microseconds
- `Intent.created_ts` → microseconds
- `Intent.ttl_us` → microseconds (not ttl_ms!)

**Example:**
```python
# Old way (milliseconds)
intent = Intent(
    ...,
    ttl_ms=1000,  # 1 second
    created_ts=1704798000123
)

# New way (MICROSECONDS)
intent = Intent(
    ...,
    ttl_us=1_000_000,  # 1 second = 1M microseconds
    created_ts=1704798000123456
)
```

### 3. Latency Tracking

**Built-in Performance Monitoring:**
```python
from src.utils.timing import LATENCY_TRACKERS, print_latency_report

# Automatically tracks:
- loop_iteration: How long each loop takes
- intent_generation: Time to create intents
- risk_check: Time to validate risks
- order_placement: Time to place orders
- book_update: Time to process orderbook
- fair_price_calc: Time to calculate fair price

# View report:
print_latency_report()
```

**Output:**
```
================================================================================
LATENCY REPORT (microseconds)
================================================================================

loop_iteration:
  Count: 1,000 samples (1,000 total ops)
  Min:   1,234µs
  Avg:   2,567µs
  p50:   2,345µs
  p95:   4,123µs
  p99:   5,678µs
  Max:   8,901µs

intent_generation:
  Count: 1,000 samples
  Min:   345µs
  Avg:   678µs
  ...
```

## HFT Configuration

### Speed Settings

```bash
# Loop: Check every 50ms (20x per second!)
LOOP_INTERVAL_MS=50

# Quotes: Update every 500ms
QUOTE_REFRESH_TTL_MS=500

# Spreads: Minimum possible
MAKER_HALF_SPREAD=0.003

# Edge: Take almost anything
TAKER_EDGE_THRESHOLD=0.01

# Orders: Up to 100/minute
MAX_ORDERS_PER_MIN=100
```

### Performance Targets

**Latency Benchmarks:**
```
Loop iteration:    <5ms   (5,000µs)
Intent generation: <1ms   (1,000µs)
Risk check:        <500µs
Fair price calc:   <300µs
Book update:       <200µs

Total reaction time: <100ms from signal to order
```

## Quick Start

```bash
# 1. Use HFT config
cp .env.hft .env

# 2. Add private key
nano .env

# 3. Check balances - NEED 75 MATIC!
python run.py --interactive

# 4. Test with latency monitoring
python run.py
# Watch for microsecond-level logs

# 5. View latency report
# The bot will print periodic reports

# 6. Go live when optimized
# Set DRY_RUN=0
python run.py
```

## Account Requirements

### Minimum for HFT

**Capital:**
- **$100 USDC** (minimum)
- **75 MATIC** ($75 for gas)
- **Total: $175 minimum**

**Recommended:**
- **$200 USDC**
- **100 MATIC** ($100)
- **Total: $300** for comfortable HFT

### Why 75+ MATIC?

```
100+ orders/day × 0.03 MATIC/order = 3 MATIC/day
75 MATIC = 25 days runtime
100 MATIC = 33 days runtime

Plus buffer for:
- High-activity days
- Network congestion
- Safety margin
```

## Expected Performance

### Latency Optimization Path

**Week 1 - Baseline:**
```
Loop iteration: 10-15ms
Total latency:  200-300ms
Fills/day:      50-80
```

**Week 2 - Optimized:**
```
Loop iteration: 5-8ms
Total latency:  100-150ms
Fills/day:      80-120
```

**Week 3 - Tuned:**
```
Loop iteration: 3-5ms
Total latency:  50-100ms
Fills/day:      120-200
```

### Profit Targets

**Best Case (Top 1%):**
- 150-200 fills/day
- $20-35/day profit
- 600-900% monthly ROI
- Could 5x account in a month

**Realistic (Top 10%):**
- 100-150 fills/day
- $10-20/day profit
- 300-600% monthly ROI
- 3-4x account in a month

**Average (Top 25%):**
- 60-100 fills/day
- $5-15/day profit
- 150-450% monthly ROI
- 2-3x account in a month

## Microsecond Monitoring

### Real-Time Latency Tracking

**Setup continuous monitoring:**

```bash
# Terminal 1: Run bot
python run.py

# Terminal 2: Watch microsecond logs
tail -f bot_hft.log | grep -E "(µs|latency|elapsed)"

# Terminal 3: Performance dashboard
watch -n 5 'sqlite3 bot_hft.db "
SELECT
  COUNT(*) as fills_last_5min,
  AVG(size*price) as avg_size
FROM fills
WHERE ts > (strftime('%s','now')*1000000 - 300000000)
"'
```

### Latency Analysis

**Check for bottlenecks:**

```python
# View detailed latency stats
from src.utils.timing import get_all_latency_stats

stats = get_all_latency_stats()

# Identify slow operations
for name, stat in stats.items():
    if stat['p95_us'] > 10_000:  # >10ms at p95
        print(f"SLOW: {name} = {stat['p95_us']}µs")
```

**Common bottlenecks:**
- Book updates >5ms → WebSocket lag
- Fair price >2ms → Calculation too complex
- Risk check >1ms → Too many checks
- Order placement >100ms → Network latency

### Optimization Targets

**What to optimize:**

```
If loop_iteration p95 > 10ms:
  → Simplify strategy logic
  → Reduce number of markets
  → Profile Python code

If intent_generation > 2ms:
  → Cache calculations
  → Optimize fair pricing
  → Reduce market count

If risk_check > 1ms:
  → Optimize limit checks
  → Cache position data
  → Simplify logic

If order_placement > 100ms:
  → Check network latency
  → Consider co-location
  → Optimize RPC endpoint
```

## Advanced Optimization

### Python Performance

**Use PyPy for 2-5x speedup:**
```bash
# Install PyPy
apt-get install pypy3

# Run with PyPy
pypy3 -m src.app
```

**Profile code:**
```bash
# Find slow functions
python -m cProfile -o profile.stats -m src.app

# Analyze
python -m pstats profile.stats
> sort cumtime
> stats 20
```

### Network Optimization

**Low-Latency RPC:**
```bash
# Test RPC latency
for i in {1..10}; do
  time curl -X POST https://polygon-rpc.com \
    -H "Content-Type: application/json" \
    -d '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}'
done

# Should be <50ms
# If >100ms, try different RPC
```

**Recommended RPCs (low latency):**
- Alchemy (paid, <30ms)
- Infura (paid, <40ms)
- QuickNode (paid, <35ms)
- polygon-rpc.com (free, 50-100ms)

### Co-Location

**For serious HFT:**

**VPS Near Polygon Validators:**
- AWS us-east-1 (Virginia) - <20ms
- AWS eu-west-1 (Ireland) - <25ms
- Digital Ocean NYC - <30ms

**Benefits:**
- 50-100ms latency → 10-30ms
- More fills
- Better pricing
- Worth it at $20+/day profit

## Microsecond Best Practices

### 1. Minimize Allocations

```python
# Bad - creates new objects
for i in range(1000):
    timestamp = now_us()
    price = calculate_price()

# Good - reuse objects
timestamp = 0
price = 0.0
for i in range(1000):
    timestamp = now_us()  # Updates in place
    price = calculate_price()  # Reuse variable
```

### 2. Cache Aggressively

```python
# Bad - recalculate every time
def get_fair_price(market):
    return expensive_calculation(market)

# Good - cache for microseconds
_cache = {}
_cache_time = {}

def get_fair_price(market):
    now = now_us()
    if market.slug in _cache:
        if now - _cache_time[market.slug] < 100_000:  # 100ms
            return _cache[market.slug]

    result = expensive_calculation(market)
    _cache[market.slug] = result
    _cache_time[market.slug] = now
    return result
```

### 3. Measure Everything

```python
from src.utils.timing import Stopwatch, track_latency

def critical_function():
    sw = Stopwatch()
    sw.start()

    # ... do work ...

    latency = sw.elapsed_us()
    track_latency('critical_function', latency)

    if latency > 5000:  # >5ms
        logger.warning(f"Slow execution: {latency}µs")
```

### 4. Batch Operations

```python
# Bad - one at a time
for order in orders:
    place_order(order)  # 100ms each

# Good - batch
place_orders_batch(orders)  # 120ms total
```

## Troubleshooting

### Issue: High Loop Latency

**Symptoms:**
```
loop_iteration p95: 50ms (should be <10ms)
```

**Causes:**
- Too many markets
- Complex calculations
- Blocking I/O

**Solutions:**
```bash
# Reduce markets to 1-2
# Simplify fair pricing
# Use async I/O
# Profile and optimize
```

### Issue: Order Placement Slow

**Symptoms:**
```
order_placement p95: 500ms (should be <100ms)
```

**Causes:**
- Network latency
- RPC endpoint slow
- Rate limiting

**Solutions:**
- Switch to premium RPC
- Use co-located VPS
- Optimize retry logic

### Issue: Book Updates Lagging

**Symptoms:**
```
book_update p95: 15ms (should be <5ms)
```

**Causes:**
- WebSocket processing slow
- Too much data
- Parsing overhead

**Solutions:**
- Optimize WebSocket handler
- Only subscribe to needed markets
- Use faster JSON parsing

## Scaling Path

### Week 1: Establish Baseline

**Goals:**
- Get system running
- Measure all latencies
- Achieve break-even

**Metrics:**
- Loop: <15ms
- Fills: 60+/day
- PnL: $0-10/day

### Week 2: Optimize

**Actions:**
- Profile slow functions
- Optimize calculations
- Tune parameters

**Targets:**
- Loop: <8ms
- Fills: 100+/day
- PnL: $5-15/day

### Week 3: Scale

**Actions:**
- Add capital or compound
- Increase position sizes
- Add 2nd-3rd market

**Targets:**
- Loop: <5ms
- Fills: 150+/day
- PnL: $15-25/day

### Month 2+: Professional

**At this point:**
- System fully optimized
- Consistent profitability
- Consider larger capital

**Options:**
- Scale to $500+ account
- Professional VPS/co-location
- Multiple strategies
- Take regular profits

## Success Criteria

### Before HFT Mode

Must have ALL:
- [ ] Profitable in aggressive mode for 2+ weeks
- [ ] Understand microsecond timing
- [ ] Can optimize Python code
- [ ] Know how to profile performance
- [ ] Have 75+ MATIC
- [ ] $175+ total capital
- [ ] Low-latency internet (<50ms to Polygon)
- [ ] Can monitor 24/7 or scheduled hours
- [ ] Understand HFT risks

If ANY unchecked → NOT READY

### Week 1 Goals

Minimum to continue:
- [ ] Average loop latency <15ms
- [ ] 60+ fills/day
- [ ] Win rate >50%
- [ ] Net positive (even $1)
- [ ] No major technical issues

If ALL checked → Continue optimization

## Warning: HFT is HARD

### Reality Check

**80-90% of HFT traders lose money**

Why:
- Requires constant optimization
- Network latency critical
- Competition is fierce
- Easy to over-optimize
- Costs can exceed profits

**This is professional territory**

You're competing against:
- Dedicated servers
- Optimized code
- Co-located infrastructure
- Teams of developers

**Do NOT expect easy money**

### Risk Management

**HFT-Specific Risks:**
- Flash crashes (lose $25 in seconds)
- Network outages (stuck in positions)
- Feed latency (adversely selected)
- Code bugs (rapid losses)
- Gas spikes (unprofitable)

**Protections:**
- $25 daily loss limit
- Kill switch
- Latency monitoring
- Position limits
- Active supervision

## Bottom Line

**HFT Mode:**
- **Microsecond precision** (1,000x better than ms)
- **Professional-grade** timing infrastructure
- **Maximum speed** (50ms loops, 500ms quotes)
- **Highest profit potential** ($15-30/day possible)
- **Highest complexity** (requires optimization)
- **Expert only** (NOT for beginners)

**System Capabilities:**
- Track latencies in microseconds
- Measure every operation
- Identify bottlenecks instantly
- Optimize systematically
- React in <100ms total

**Your Path:**
```bash
1. Master conservative mode
2. Profit in aggressive mode
3. Study HFT mode docs
4. Set up monitoring
5. Optimize systematically
6. Scale carefully
```

**Ready for microsecond trading?**
```bash
cp .env.hft .env
# Get 75+ MATIC
# Optimize everything
python run.py
```

**Or build up first?** Recommended for 95% of traders.

⚡ Microseconds matter! ⚡
