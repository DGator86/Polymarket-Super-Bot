"""
Balance checker utility for Polymarket bot.

Checks USDC and MATIC balances on Polygon.
"""
from typing import Dict, Optional
from src.logging_setup import get_logger

logger = get_logger("balance_checker")


class BalanceChecker:
    """
    Check wallet balances for USDC and MATIC on Polygon.

    Uses web3 to query ERC20 token balances and native MATIC balance.
    """

    # Polygon mainnet addresses
    USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC on Polygon
    MATIC_DECIMALS = 18
    USDC_DECIMALS = 6

    def __init__(self, private_key: str, rpc_url: str = "https://polygon-rpc.com"):
        """
        Initialize balance checker.

        Args:
            private_key: Wallet private key
            rpc_url: Polygon RPC endpoint
        """
        self.rpc_url = rpc_url
        self._web3 = None
        self._account = None

        try:
            from web3 import Web3
            from eth_account import Account

            self._web3 = Web3(Web3.HTTPProvider(rpc_url))
            self._account = Account.from_key(private_key)
            self.address = self._account.address

            logger.info(f"Balance checker initialized for address: {self.address}")

        except ImportError:
            logger.warning("web3.py not installed. Install with: pip install web3")
            self._web3 = None
        except Exception as e:
            logger.error(f"Failed to initialize balance checker: {e}")
            self._web3 = None

    def is_available(self) -> bool:
        """Check if balance checker is available."""
        return self._web3 is not None and self._web3.is_connected()

    def get_matic_balance(self) -> Optional[float]:
        """
        Get MATIC balance.

        Returns:
            MATIC balance or None if unavailable
        """
        if not self.is_available():
            logger.warning("Balance checker not available")
            return None

        try:
            balance_wei = self._web3.eth.get_balance(self.address)
            balance_matic = balance_wei / (10 ** self.MATIC_DECIMALS)

            logger.debug(f"MATIC balance: {balance_matic:.4f}")
            return balance_matic

        except Exception as e:
            logger.error(f"Failed to get MATIC balance: {e}")
            return None

    def get_usdc_balance(self) -> Optional[float]:
        """
        Get USDC balance.

        Returns:
            USDC balance or None if unavailable
        """
        if not self.is_available():
            logger.warning("Balance checker not available")
            return None

        try:
            # ERC20 balanceOf ABI
            erc20_abi = [
                {
                    "constant": True,
                    "inputs": [{"name": "_owner", "type": "address"}],
                    "name": "balanceOf",
                    "outputs": [{"name": "balance", "type": "uint256"}],
                    "type": "function"
                }
            ]

            usdc_contract = self._web3.eth.contract(
                address=self._web3.to_checksum_address(self.USDC_ADDRESS),
                abi=erc20_abi
            )

            balance_raw = usdc_contract.functions.balanceOf(self.address).call()
            balance_usdc = balance_raw / (10 ** self.USDC_DECIMALS)

            logger.debug(f"USDC balance: {balance_usdc:.2f}")
            return balance_usdc

        except Exception as e:
            logger.error(f"Failed to get USDC balance: {e}")
            return None

    def get_all_balances(self) -> Dict[str, Optional[float]]:
        """
        Get all balances.

        Returns:
            Dict with MATIC and USDC balances
        """
        balances = {
            "MATIC": self.get_matic_balance(),
            "USDC": self.get_usdc_balance()
        }

        logger.info(
            f"Balances: MATIC={balances['MATIC']:.4f if balances['MATIC'] else 'N/A'}, "
            f"USDC=${balances['USDC']:.2f if balances['USDC'] else 'N/A'}"
        )

        return balances

    def check_sufficient_balance(
        self,
        required_usdc: float = 0.0,
        required_matic: float = 0.0
    ) -> tuple[bool, str]:
        """
        Check if wallet has sufficient balances.

        Args:
            required_usdc: Required USDC amount
            required_matic: Required MATIC amount

        Returns:
            (is_sufficient, message)
        """
        balances = self.get_all_balances()

        if balances["USDC"] is None or balances["MATIC"] is None:
            return False, "Unable to fetch balances"

        issues = []

        if required_usdc > 0 and balances["USDC"] < required_usdc:
            issues.append(
                f"Insufficient USDC: have ${balances['USDC']:.2f}, "
                f"need ${required_usdc:.2f}"
            )

        if required_matic > 0 and balances["MATIC"] < required_matic:
            issues.append(
                f"Insufficient MATIC: have {balances['MATIC']:.4f}, "
                f"need {required_matic:.4f}"
            )

        if issues:
            return False, "; ".join(issues)

        return True, "Sufficient balance"


class MockBalanceChecker(BalanceChecker):
    """Mock balance checker for testing/dry-run mode."""

    def __init__(self, mock_usdc: float = 1000.0, mock_matic: float = 10.0):
        """Initialize with mock balances."""
        self.address = "0x0000000000000000000000000000000000000000"
        self._mock_usdc = mock_usdc
        self._mock_matic = mock_matic
        logger.info(f"Mock balance checker initialized (USDC=${mock_usdc}, MATIC={mock_matic})")

    def is_available(self) -> bool:
        """Mock is always available."""
        return True

    def get_matic_balance(self) -> float:
        """Return mock MATIC balance."""
        return self._mock_matic

    def get_usdc_balance(self) -> float:
        """Return mock USDC balance."""
        return self._mock_usdc
