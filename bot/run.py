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

    args = parser.parse_args()

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
