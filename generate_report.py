#!/usr/bin/env python3
"""
Generate Performance Reports

Analyze paper trading results and generate reports:
    python generate_report.py

Options:
    --days N           Analyze last N days (default: 30)
    --output PATH      Output file path
    --format FORMAT    Output format: json, csv, or console (default: console)
"""

import argparse
import json
from pathlib import Path
from dataclasses import asdict

from paper_trading.analytics import AnalyticsEngine


def main():
    parser = argparse.ArgumentParser(description="Generate Paper Trading Reports")
    
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Analyze last N days (default: 30)"
    )
    
    parser.add_argument(
        "--data-dir",
        type=str,
        default="./paper_trading_data",
        help="Data directory (default: ./paper_trading_data)"
    )
    
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file path"
    )
    
    parser.add_argument(
        "--format",
        type=str,
        choices=["json", "csv", "console"],
        default="console",
        help="Output format (default: console)"
    )
    
    args = parser.parse_args()
    
    db_path = Path(args.data_dir) / "paper_trades.db"
    
    if not db_path.exists():
        print(f"No data found at {db_path}")
        print("Run paper trading first to generate data.")
        return
    
    analytics = AnalyticsEngine(str(db_path))
    analytics.connect()
    
    try:
        report = analytics.generate_report(days=args.days)
        
        if args.format == "console":
            print_console_report(report)
        
        elif args.format == "json":
            output_path = args.output or "performance_report.json"
            with open(output_path, "w") as f:
                json.dump(asdict(report), f, indent=2)
            print(f"Report saved to {output_path}")
        
        elif args.format == "csv":
            output_path = args.output or "trades_export.csv"
            analytics.export_trades_csv(output_path)
            print(f"Trades exported to {output_path}")
    
    finally:
        analytics.close()


def print_console_report(report):
    """Print report to console"""
    print()
    print("=" * 60)
    print("PAPER TRADING PERFORMANCE REPORT")
    print("=" * 60)
    print()
    print(f"Period: {report.period_start[:10]} to {report.period_end[:10]}")
    print()
    print("OVERALL PERFORMANCE")
    print("-" * 40)
    print(f"Total Trades:    {report.total_trades}")
    print(f"Wins:            {report.wins}")
    print(f"Losses:          {report.losses}")
    print(f"Win Rate:        {report.win_rate:.1%}")
    print()
    print(f"Total P&L:       ${report.total_pnl:.2f}")
    print(f"Avg Win:         ${report.avg_win:.2f}")
    print(f"Avg Loss:        ${report.avg_loss:.2f}")
    print(f"Profit Factor:   {report.profit_factor:.2f}")
    print()
    print(f"Max Drawdown:    {report.max_drawdown:.1%}")
    print(f"Sharpe Ratio:    {report.sharpe_ratio:.2f}")
    print()
    
    if report.by_category:
        print("BY CATEGORY")
        print("-" * 40)
        for cat, stats in report.by_category.items():
            print(f"  {cat}: {stats['trades']} trades, "
                  f"{stats['win_rate']:.1%} win rate, "
                  f"${stats['pnl']:.2f} P&L")
        print()
    
    if report.by_edge_bucket:
        print("BY EDGE BUCKET")
        print("-" * 40)
        for bucket, stats in report.by_edge_bucket.items():
            print(f"  {bucket}: {stats['trades']} trades, "
                  f"{stats['win_rate']:.1%} win rate, "
                  f"${stats['avg_pnl']:.2f} avg P&L")
        print()
    
    if report.edge_calibration:
        print("EDGE CALIBRATION")
        print("-" * 40)
        print("(Factor > 1.0 = edge underestimated, < 1.0 = overestimated)")
        for bucket, factor in report.edge_calibration.items():
            status = "✓" if 0.8 <= factor <= 1.2 else "!"
            print(f"  {bucket}: {factor:.2f} {status}")
        print()
    
    print("=" * 60)


if __name__ == "__main__":
    main()
