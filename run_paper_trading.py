#!/usr/bin/env python3
"""
Paper Trading Entry Point

Run the paper trading system:
    python run_paper_trading.py

Options:
    --capital AMOUNT    Starting capital (default: 1000)
    --interval SECONDS  Scan interval (default: 60)
    --max-positions N   Maximum open positions (default: 10)
    --data-dir PATH     Data directory (default: ./paper_trading_data)
"""

import argparse
import asyncio
from decimal import Decimal

from paper_trading.runner import PaperTradingRunner


def main():
    parser = argparse.ArgumentParser(description="Kalshi Paper Trading System")
    
    parser.add_argument(
        "--capital",
        type=float,
        default=1000,
        help="Starting capital in dollars (default: 1000)"
    )
    
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Scan interval in seconds (default: 60)"
    )
    
    parser.add_argument(
        "--max-positions",
        type=int,
        default=10,
        help="Maximum simultaneous positions (default: 10)"
    )
    
    parser.add_argument(
        "--data-dir",
        type=str,
        default="./paper_trading_data",
        help="Directory for storing data (default: ./paper_trading_data)"
    )
    
    parser.add_argument(
        "--min-ml-samples",
        type=int,
        default=20,
        help="Minimum trades before training ML model (default: 20)"
    )
    
    args = parser.parse_args()
    
    runner = PaperTradingRunner(
        starting_capital=Decimal(str(args.capital)),
        data_dir=args.data_dir,
        scan_interval=args.interval,
        max_positions=args.max_positions,
        min_ml_samples=args.min_ml_samples,
    )
    
    asyncio.run(runner.run())


if __name__ == "__main__":
    main()
