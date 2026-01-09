"""
Interactive CLI for Polymarket bot.

Provides a command menu for manual operations.
"""
import sys
from typing import Optional
from datetime import datetime

from src.config import load_config
from src.logging_setup import setup_logging, get_logger
from src.market_registry import MarketRegistry
from src.utils.balance_checker import BalanceChecker, MockBalanceChecker
from src.utils.allowance_manager import AllowanceManager, MockAllowanceManager
from src.execution.clob_client import CLOBClient
from src.state.db import Database
from src.state.repositories import PositionRepository, OrderRepository
from src.state.pnl import PnLTracker

logger = get_logger("cli")


class InteractiveCLI:
    """
    Interactive command-line interface for the Polymarket bot.

    Provides manual control and inspection capabilities.
    """

    def __init__(self):
        self.config = None
        self.balance_checker = None
        self.allowance_manager = None
        self.clob_client = None
        self.registry = None
        self.db = None
        self.pnl_tracker = None
        self.running = True

    def initialize(self) -> None:
        """Initialize components."""
        logger.info("Initializing interactive CLI...")

        # Load configuration
        self.config = load_config()
        setup_logging(self.config.log_level, self.config.log_file)

        # Initialize database
        self.db = Database(self.config.db_path)
        self.db.connect()

        position_repo = PositionRepository(self.db)
        order_repo = OrderRepository(self.db)

        from src.state.repositories import FillRepository
        fill_repo = FillRepository(self.db)

        self.pnl_tracker = PnLTracker(position_repo, fill_repo)
        self.order_repo = order_repo

        # Initialize market registry
        self.registry = MarketRegistry(self.config.market_registry_path)

        # Initialize balance checker
        if self.config.execution.dry_run:
            self.balance_checker = MockBalanceChecker()
            self.allowance_manager = MockAllowanceManager()
        else:
            self.balance_checker = BalanceChecker(
                private_key=self.config.execution.private_key,
                rpc_url="https://polygon-rpc.com"
            )
            self.allowance_manager = AllowanceManager(
                private_key=self.config.execution.private_key,
                rpc_url="https://polygon-rpc.com"
            )

        # Initialize CLOB client
        self.clob_client = CLOBClient(
            private_key=self.config.execution.private_key,
            chain_id=self.config.execution.chain_id,
            clob_url=self.config.execution.clob_url,
            api_key=self.config.execution.api_key,
            api_secret=self.config.execution.api_secret,
            api_passphrase=self.config.execution.api_passphrase,
            dry_run=self.config.execution.dry_run
        )

        logger.info("Interactive CLI initialized")

    def print_banner(self) -> None:
        """Print welcome banner."""
        mode = "DRY-RUN" if self.config.execution.dry_run else "LIVE"
        print("\n" + "=" * 60)
        print("  Polymarket Hybrid Trading Bot - Interactive CLI")
        print(f"  Mode: {mode}")
        print("=" * 60 + "\n")

    def print_menu(self) -> None:
        """Print command menu."""
        print("\n--- Main Menu ---")
        print("1. Check Balances")
        print("2. Check Allowances")
        print("3. View Positions")
        print("4. View Open Orders")
        print("5. View PnL")
        print("6. List Markets")
        print("7. View Market Details")
        print("8. Place Order (Manual)")
        print("9. Cancel Order")
        print("0. Exit")
        print("-" * 40)

    def run(self) -> None:
        """Run the interactive CLI."""
        self.print_banner()

        while self.running:
            try:
                self.print_menu()
                choice = input("\nEnter choice: ").strip()

                if choice == "1":
                    self.check_balances()
                elif choice == "2":
                    self.check_allowances()
                elif choice == "3":
                    self.view_positions()
                elif choice == "4":
                    self.view_open_orders()
                elif choice == "5":
                    self.view_pnl()
                elif choice == "6":
                    self.list_markets()
                elif choice == "7":
                    self.view_market_details()
                elif choice == "8":
                    self.place_order()
                elif choice == "9":
                    self.cancel_order()
                elif choice == "0":
                    self.running = False
                    print("\nExiting...")
                else:
                    print("\nInvalid choice. Please try again.")

            except KeyboardInterrupt:
                print("\n\nInterrupted. Exiting...")
                self.running = False
            except Exception as e:
                logger.error(f"Error in CLI: {e}", exc_info=True)
                print(f"\nError: {e}")

    def check_balances(self) -> None:
        """Check wallet balances."""
        print("\n--- Wallet Balances ---")

        if not self.balance_checker.is_available():
            print("Balance checker not available")
            return

        balances = self.balance_checker.get_all_balances()

        print(f"Address: {self.balance_checker.address}")
        print(f"MATIC:   {balances['MATIC']:.4f}" if balances['MATIC'] else "MATIC:   N/A")
        print(f"USDC:    ${balances['USDC']:.2f}" if balances['USDC'] else "USDC:    N/A")

    def check_allowances(self) -> None:
        """Check token allowances."""
        print("\n--- Token Allowances ---")

        if not self.allowance_manager.is_available():
            print("Allowance manager not available")
            return

        allowance = self.allowance_manager.get_allowance()

        print(f"Address:   {self.allowance_manager.address}")
        print(f"USDC Allowance: ${allowance:.2f}" if allowance else "USDC Allowance: N/A")

        if allowance and allowance < 1000:
            response = input("\nAllowance is low. Set unlimited allowance? (y/n): ")
            if response.lower() == 'y':
                tx_hash = self.allowance_manager.set_allowance(-1)  # Unlimited
                if tx_hash:
                    print(f"Allowance set! TX: {tx_hash}")
                else:
                    print("Failed to set allowance")

    def view_positions(self) -> None:
        """View current positions."""
        print("\n--- Current Positions ---")

        positions = self.pnl_tracker.get_all_positions()

        if not positions:
            print("No open positions")
            return

        print(f"{'Token ID':<45} {'Quantity':>12} {'Avg Cost':>12} {'Realized PnL':>15}")
        print("-" * 90)

        for token_id, pos in positions.items():
            if pos.qty != 0:
                print(
                    f"{token_id[:42]+'...':<45} "
                    f"{pos.qty:>12.2f} "
                    f"${pos.avg_cost:>11.4f} "
                    f"${pos.realized_pnl:>14.2f}"
                )

    def view_open_orders(self) -> None:
        """View open orders."""
        print("\n--- Open Orders ---")

        orders = self.order_repo.get_open_orders()

        if not orders:
            print("No open orders")
            return

        print(f"{'Order ID':<20} {'Token ID':<45} {'Side':<6} {'Price':>10} {'Size':>10}")
        print("-" * 95)

        for order in orders:
            print(
                f"{order.order_id[:18]+'...':<20} "
                f"{order.token_id[:42]+'...':<45} "
                f"{order.side.value:<6} "
                f"{order.price:>10.4f} "
                f"{order.remaining_size:>10.2f}"
            )

    def view_pnl(self) -> None:
        """View PnL summary."""
        print("\n--- PnL Summary ---")

        # For current mids, we'd need live data
        # For now, just show realized PnL
        positions = self.pnl_tracker.get_all_positions()

        total_realized = sum(p.realized_pnl for p in positions.values())

        print(f"Total Realized PnL: ${total_realized:.2f}")
        print("\nNote: Unrealized PnL requires live market data")

    def list_markets(self) -> None:
        """List available markets."""
        print("\n--- Available Markets ---")

        current_ts = int(datetime.now().timestamp())
        markets = self.registry.get_active_markets(current_ts)

        if not markets:
            print("No active markets")
            return

        print(f"{'Slug':<50} {'Strike':>12} {'Expiry'}")
        print("-" * 80)

        for slug, market in markets.items():
            expiry_date = datetime.fromtimestamp(market.expiry_ts).strftime('%Y-%m-%d')
            strike_str = f"${market.strike:,.0f}" if market.strike else "N/A"
            print(f"{slug[:48]:<50} {strike_str:>12} {expiry_date}")

    def view_market_details(self) -> None:
        """View details for a specific market."""
        slug = input("\nEnter market slug: ").strip()

        market = self.registry.get_market(slug)

        if not market:
            print(f"Market not found: {slug}")
            return

        print(f"\n--- Market Details: {slug} ---")
        print(f"Strike:       ${market.strike:,.0f}" if market.strike else "Strike:       N/A")
        print(f"Expiry:       {datetime.fromtimestamp(market.expiry_ts)}")
        print(f"YES Token ID: {market.yes_token_id}")
        print(f"NO Token ID:  {market.no_token_id}")
        print(f"Tick Size:    ${market.tick_size}")
        print(f"Min Size:     {market.min_size}")

    def place_order(self) -> None:
        """Place a manual order."""
        print("\n--- Place Order (Manual) ---")
        print("This feature requires market data integration.")
        print("Use automated mode for full trading capabilities.")

    def cancel_order(self) -> None:
        """Cancel an order."""
        order_id = input("\nEnter order ID to cancel: ").strip()

        if not order_id:
            print("Order ID required")
            return

        success = self.clob_client.cancel_order(order_id)

        if success:
            print(f"Order {order_id} cancelled successfully")
            self.order_repo.update_order_status(order_id, "CANCELLED")
        else:
            print(f"Failed to cancel order {order_id}")

    def cleanup(self) -> None:
        """Cleanup resources."""
        if self.db:
            self.db.close()


def main():
    """Main entry point for interactive CLI."""
    cli = InteractiveCLI()

    try:
        cli.initialize()
        cli.run()
    except Exception as e:
        logger.critical(f"Fatal error in CLI: {e}", exc_info=True)
        sys.exit(1)
    finally:
        cli.cleanup()


if __name__ == "__main__":
    main()
