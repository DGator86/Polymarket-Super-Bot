#!/usr/bin/env python3
"""
Launcher script for Polymarket bot.

Allows choosing between automated and interactive modes.
"""
import sys
import argparse


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Polymarket Hybrid Trading Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run in automated mode (default)
  python run.py

  # Run in interactive CLI mode
  python run.py --interactive

  # Run in automated mode with custom config
  python run.py --mode auto
        """
    )

    parser.add_argument(
        "--mode",
        choices=["auto", "interactive"],
        default="auto",
        help="Operating mode (default: auto)"
    )

    parser.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="Run in interactive CLI mode (shorthand for --mode interactive)"
    )

    parser.add_argument(
        "--scan",
        action="store_true",
        help="Scan for active markets and update markets.json"
    )

    args = parser.parse_args()

    if args.scan:
        print("Scanning Polymarket for high-volume markets...")
        try:
            from src.utils.market_scanner import MarketScanner
            # Scan for keywords (Expanded sports coverage)
            keywords = [
                "Premier League",
                "Champions League",
                "NBA",
                "NFL",
                "NCAA Football",
                "College Football",
                "Bitcoin", 
                "Ethereum"
            ]
            
            # Lower volume threshold for specific sports markets as they might not have "Fed" level volume
            scanner = MarketScanner(min_volume=1000) 
            
            # Allow more markets to ensure we capture diverse set from all categories
            markets = scanner.scan_markets(keywords, limit=20)
            
            if markets:
                scanner.save_to_file(markets, "markets.json")
                print(f"Successfully updated markets.json with {len(markets)} active markets.")
                print("Markets found:")
                for m in markets:
                    print(f"- {m['slug']} (Vol: ${m['volume']:,.0f})")
            else:
                print("No markets found matching criteria.")
        except ImportError:
            print("Error: Could not import MarketScanner. Check your installation.")
        except Exception as e:
            print(f"Error during scan: {e}")
        return

    # Determine mode
    mode = "interactive" if args.interactive else args.mode

    if mode == "interactive":
        print("Starting Polymarket bot in INTERACTIVE mode...")
        from src.cli import main as cli_main
        cli_main()
    else:
        print("Starting Polymarket bot in AUTOMATED mode...")
        from src.app import main as app_main
        app_main()


if __name__ == "__main__":
    main()
