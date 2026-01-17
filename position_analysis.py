import sqlite3
import asyncio
from datetime import datetime, timezone

# Get current crypto prices
async def get_prices():
    import sys
    sys.path.insert(0, '.')
    try:
        from connectors.crypto_aggregator import get_aggregator
        agg = get_aggregator()
        prices = await agg.get_all_prices()
        return {s: p.fair_value for s, p in prices.items()}
    except:
        return {'BTC': 95400, 'ETH': 3303, 'SOL': 144}

# Main analysis
def analyze():
    prices = asyncio.run(get_prices())
    btc = prices.get('BTC', 95400)
    eth = prices.get('ETH', 3303)
    sol = prices.get('SOL', 144)
    
    print("=" * 70)
    print("PAPER TRADING POSITION ANALYSIS")
    print("=" * 70)
    print(f"\nCURRENT PRICES (as of {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC):")
    print(f"  BTC: ${btc:,.2f}")
    print(f"  ETH: ${eth:,.2f}")
    print(f"  SOL: ${sol:,.2f}")
    
    # Read trades from DB
    conn = sqlite3.connect('/root/kalshi-bot/integrated_paper_data/paper_trades.db')
    cur = conn.cursor()
    
    cur.execute("""
        SELECT ticker, side, SUM(quantity) as qty, 
               AVG(price) as avg_price, 
               SUM(quantity * price) as cost_basis,
               MIN(created_at) as first_trade,
               MAX(created_at) as last_trade
        FROM trades
        GROUP BY ticker, side
        ORDER BY ticker
    """)
    
    positions = {}
    for row in cur.fetchall():
        ticker, side, qty, avg_price, cost_basis, first_trade, last_trade = row
        if ticker not in positions:
            positions[ticker] = {'yes': 0, 'no': 0, 'yes_cost': 0, 'no_cost': 0, 
                                'first': first_trade, 'last': last_trade}
        positions[ticker][side] = qty
        positions[ticker][f'{side}_cost'] = cost_basis
        if first_trade < positions[ticker]['first']:
            positions[ticker]['first'] = first_trade
        if last_trade > positions[ticker]['last']:
            positions[ticker]['last'] = last_trade
    
    conn.close()
    
    # Calculate P&L
    print("\n" + "=" * 70)
    print("OPEN POSITIONS & P/L ANALYSIS")
    print("=" * 70)
    
    total_cost = 0
    total_potential_profit = 0
    total_at_risk = 0
    
    # Group by expiry
    expiry_17 = []
    expiry_23 = []
    other = []
    
    for ticker, pos in positions.items():
        # Parse ticker
        if 'B' in ticker:  # Binary strike
            parts = ticker.split('-')
            strike = int(parts[-1][1:])  # B95125 -> 95125
            expiry_str = parts[1]  # 26JAN1708 or 26JAN2317
        else:
            strike = None
            expiry_str = ticker.split('-')[1] if '-' in ticker else ''
        
        # Determine underlying
        if 'BTC' in ticker:
            current = btc
        elif 'ETH' in ticker:
            current = eth
        elif 'SOL' in ticker:
            current = sol
        else:
            current = None
        
        # Net position
        net_yes = pos['yes'] - pos['no']  # positive = long yes, negative = long no
        total_cost_basis = (pos['yes_cost'] + pos['no_cost']) / 100  # cents to dollars
        
        # Determine ITM/OTM for binary strikes
        if strike and current:
            is_itm_yes = current >= strike
            status = "ITM" if (net_yes > 0 and is_itm_yes) or (net_yes < 0 and not is_itm_yes) else "OTM"
            
            if net_yes > 0:  # Long YES
                # Profit if settles YES (price >= strike)
                potential_payout = abs(net_yes) * 1.00  # $1 per contract
                cost = pos['yes_cost'] / 100
                potential_profit = potential_payout - cost if is_itm_yes else 0
                at_risk = cost if not is_itm_yes else 0
            else:  # Long NO (short YES)
                # Profit if settles NO (price < strike)
                potential_payout = abs(net_yes) * 1.00
                cost = pos['no_cost'] / 100
                potential_profit = potential_payout - cost if not is_itm_yes else 0
                at_risk = cost if is_itm_yes else 0
        else:
            status = "N/A"
            potential_profit = 0
            at_risk = total_cost_basis
            is_itm_yes = None
        
        total_cost += total_cost_basis
        total_potential_profit += potential_profit
        total_at_risk += at_risk
        
        entry = {
            'ticker': ticker,
            'net': net_yes,
            'strike': strike,
            'current': current,
            'cost': total_cost_basis,
            'status': status,
            'profit': potential_profit,
            'risk': at_risk,
            'first': pos['first'],
            'last': pos['last'],
            'expiry': expiry_str
        }
        
        if '1708' in ticker:
            expiry_17.append(entry)
        elif '2317' in ticker:
            expiry_23.append(entry)
        else:
            other.append(entry)
    
    # Print 17:00 UTC expiry
    print("\n--- EXPIRY: JAN 26, 17:00 UTC (TODAY) ---")
    print(f"{'Ticker':<30} {'Position':<12} {'Strike':<8} {'Current':<10} {'Status':<6} {'Cost':<10} {'Profit/Risk':<15}")
    print("-" * 100)
    
    exp17_profit = 0
    exp17_risk = 0
    for e in sorted(expiry_17, key=lambda x: x['ticker']):
        pos_str = f"{'YES' if e['net'] > 0 else 'NO'} x {abs(e['net'])}"
        strike_str = f"${e['strike']:,}" if e['strike'] else "N/A"
        current_str = f"${e['current']:,.0f}" if e['current'] else "N/A"
        profit_str = f"+${e['profit']:.2f}" if e['profit'] > 0 else f"-${e['risk']:.2f} at risk"
        print(f"{e['ticker']:<30} {pos_str:<12} {strike_str:<8} {current_str:<10} {e['status']:<6} ${e['cost']:.2f}     {profit_str}")
        exp17_profit += e['profit']
        exp17_risk += e['risk']
    
    print(f"\n17:00 UTC Summary: Potential Profit: ${exp17_profit:.2f} | At Risk: ${exp17_risk:.2f}")
    
    # Print 23:00 UTC expiry  
    print("\n--- EXPIRY: JAN 26, 23:00 UTC (TONIGHT) ---")
    print(f"{'Ticker':<30} {'Position':<12} {'Strike':<8} {'Current':<10} {'Status':<6} {'Cost':<10} {'Profit/Risk':<15}")
    print("-" * 100)
    
    exp23_profit = 0
    exp23_risk = 0
    for e in sorted(expiry_23, key=lambda x: x['ticker']):
        pos_str = f"{'YES' if e['net'] > 0 else 'NO'} x {abs(e['net'])}"
        strike_str = f"${e['strike']:,}" if e['strike'] else "N/A"
        current_str = f"${e['current']:,.0f}" if e['current'] else "N/A"
        profit_str = f"+${e['profit']:.2f}" if e['profit'] > 0 else f"-${e['risk']:.2f} at risk"
        print(f"{e['ticker']:<30} {pos_str:<12} {strike_str:<8} {current_str:<10} {e['status']:<6} ${e['cost']:.2f}     {profit_str}")
        exp23_profit += e['profit']
        exp23_risk += e['risk']
    
    print(f"\n23:00 UTC Summary: Potential Profit: ${exp23_profit:.2f} | At Risk: ${exp23_risk:.2f}")
    
    # Print other positions
    if other:
        print("\n--- OTHER POSITIONS (15-min markets, etc.) ---")
        for e in other:
            print(f"{e['ticker']}: {'YES' if e['net'] > 0 else 'NO'} x {abs(e['net'])} | Cost: ${e['cost']:.2f} | Traded: {e['first'][:19]} - {e['last'][:19]}")
    
    # Overall summary
    print("\n" + "=" * 70)
    print("OVERALL SUMMARY")
    print("=" * 70)
    print(f"Total Cost Basis:      ${total_cost:.2f}")
    print(f"Total Potential Profit: ${total_potential_profit:.2f} (if all ITM positions settle)")
    print(f"Total At Risk:         ${total_at_risk:.2f} (if all OTM positions expire worthless)")
    print(f"\nBest Case P&L:  +${total_potential_profit:.2f} ({total_potential_profit/10:.1f}% return)")
    print(f"Worst Case P&L: -${total_at_risk:.2f} ({-total_at_risk/10:.1f}% loss)")
    
    # Breakeven analysis
    print("\n" + "=" * 70)
    print("BREAKEVEN ANALYSIS (key strike levels)")
    print("=" * 70)
    print(f"Current BTC: ${btc:,.2f}")
    print(f"\nIf BTC stays above $95,375 -> 17:00 LONG YES positions WIN")
    print(f"If BTC stays above $94,250 -> All 23:00 LONG YES positions WIN")
    print(f"If BTC drops below $95,125 -> 17:00 LONG NO position WINS")

if __name__ == '__main__':
    analyze()
