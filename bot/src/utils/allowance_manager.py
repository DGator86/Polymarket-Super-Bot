"""
Allowance manager for ERC20 token approvals.

Manages token allowances for Polymarket CLOB contracts.
"""
from typing import Optional
from src.logging_setup import get_logger

logger = get_logger("allowance_manager")


class AllowanceManager:
    """
    Manage ERC20 token allowances for Polymarket trading.

    Handles checking and setting allowances for USDC to the
    Polymarket CLOB contract.
    """

    # Polygon mainnet addresses
    USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    POLYMARKET_EXCHANGE = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"  # CTF Exchange
    USDC_DECIMALS = 6

    # Max uint256 for unlimited approval
    MAX_APPROVAL = 2**256 - 1

    def __init__(self, private_key: str, rpc_url: str = "https://polygon-rpc.com"):
        """
        Initialize allowance manager.

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

            logger.info(f"Allowance manager initialized for address: {self.address}")

        except ImportError:
            logger.warning("web3.py not installed. Install with: pip install web3")
            self._web3 = None
        except Exception as e:
            logger.error(f"Failed to initialize allowance manager: {e}")
            self._web3 = None

    def is_available(self) -> bool:
        """Check if allowance manager is available."""
        return self._web3 is not None and self._web3.is_connected()

    def get_allowance(self, token_address: Optional[str] = None, spender: Optional[str] = None) -> Optional[float]:
        """
        Get current allowance.

        Args:
            token_address: Token contract address (defaults to USDC)
            spender: Spender address (defaults to Polymarket exchange)

        Returns:
            Current allowance amount or None if unavailable
        """
        if not self.is_available():
            logger.warning("Allowance manager not available")
            return None

        token_address = token_address or self.USDC_ADDRESS
        spender = spender or self.POLYMARKET_EXCHANGE

        try:
            # ERC20 allowance ABI
            erc20_abi = [
                {
                    "constant": True,
                    "inputs": [
                        {"name": "_owner", "type": "address"},
                        {"name": "_spender", "type": "address"}
                    ],
                    "name": "allowance",
                    "outputs": [{"name": "remaining", "type": "uint256"}],
                    "type": "function"
                }
            ]

            token_contract = self._web3.eth.contract(
                address=self._web3.to_checksum_address(token_address),
                abi=erc20_abi
            )

            allowance_raw = token_contract.functions.allowance(
                self.address,
                self._web3.to_checksum_address(spender)
            ).call()

            allowance_usdc = allowance_raw / (10 ** self.USDC_DECIMALS)

            logger.debug(f"Current allowance: ${allowance_usdc:.2f}")
            return allowance_usdc

        except Exception as e:
            logger.error(f"Failed to get allowance: {e}")
            return None

    def set_allowance(
        self,
        amount: float,
        token_address: Optional[str] = None,
        spender: Optional[str] = None
    ) -> Optional[str]:
        """
        Set token allowance.

        Args:
            amount: Allowance amount in USDC (use -1 for unlimited)
            token_address: Token contract address (defaults to USDC)
            spender: Spender address (defaults to Polymarket exchange)

        Returns:
            Transaction hash or None if failed
        """
        if not self.is_available():
            logger.warning("Allowance manager not available")
            return None

        token_address = token_address or self.USDC_ADDRESS
        spender = spender or self.POLYMARKET_EXCHANGE

        try:
            # ERC20 approve ABI
            erc20_abi = [
                {
                    "constant": False,
                    "inputs": [
                        {"name": "_spender", "type": "address"},
                        {"name": "_value", "type": "uint256"}
                    ],
                    "name": "approve",
                    "outputs": [{"name": "success", "type": "bool"}],
                    "type": "function"
                }
            ]

            token_contract = self._web3.eth.contract(
                address=self._web3.to_checksum_address(token_address),
                abi=erc20_abi
            )

            # Convert amount to raw units
            if amount < 0:
                amount_raw = self.MAX_APPROVAL
                logger.info("Setting unlimited allowance")
            else:
                amount_raw = int(amount * (10 ** self.USDC_DECIMALS))
                logger.info(f"Setting allowance: ${amount:.2f}")

            # Build transaction
            tx = token_contract.functions.approve(
                self._web3.to_checksum_address(spender),
                amount_raw
            ).build_transaction({
                'from': self.address,
                'nonce': self._web3.eth.get_transaction_count(self.address),
                'gas': 100000,
                'gasPrice': self._web3.eth.gas_price
            })

            # Sign and send
            signed_tx = self._account.sign_transaction(tx)
            tx_hash = self._web3.eth.send_raw_transaction(signed_tx.rawTransaction)

            logger.info(f"Allowance transaction sent: {tx_hash.hex()}")

            # Wait for confirmation
            receipt = self._web3.eth.wait_for_transaction_receipt(tx_hash)

            if receipt['status'] == 1:
                logger.info(f"Allowance set successfully: {tx_hash.hex()}")
                return tx_hash.hex()
            else:
                logger.error(f"Allowance transaction failed: {tx_hash.hex()}")
                return None

        except Exception as e:
            logger.error(f"Failed to set allowance: {e}")
            return None

    def ensure_sufficient_allowance(self, required_amount: float) -> bool:
        """
        Ensure sufficient allowance exists, set if needed.

        Args:
            required_amount: Required allowance in USDC

        Returns:
            True if sufficient allowance is available
        """
        current_allowance = self.get_allowance()

        if current_allowance is None:
            logger.error("Unable to check current allowance")
            return False

        if current_allowance >= required_amount:
            logger.info(f"Sufficient allowance: ${current_allowance:.2f} >= ${required_amount:.2f}")
            return True

        logger.warning(
            f"Insufficient allowance: ${current_allowance:.2f} < ${required_amount:.2f}, "
            f"setting new allowance"
        )

        # Set allowance to 2x required amount or unlimited
        new_allowance = max(required_amount * 2, 10000)  # At least $10k or 2x required
        tx_hash = self.set_allowance(new_allowance)

        return tx_hash is not None


class MockAllowanceManager(AllowanceManager):
    """Mock allowance manager for testing/dry-run mode."""

    def __init__(self):
        """Initialize mock allowance manager."""
        self.address = "0x0000000000000000000000000000000000000000"
        self._mock_allowance = 1000000.0  # $1M mock allowance
        logger.info(f"Mock allowance manager initialized (allowance=${self._mock_allowance})")

    def is_available(self) -> bool:
        """Mock is always available."""
        return True

    def get_allowance(self, token_address: Optional[str] = None, spender: Optional[str] = None) -> float:
        """Return mock allowance."""
        return self._mock_allowance

    def set_allowance(
        self,
        amount: float,
        token_address: Optional[str] = None,
        spender: Optional[str] = None
    ) -> str:
        """Mock set allowance."""
        self._mock_allowance = amount if amount >= 0 else 1000000.0
        logger.info(f"[MOCK] Allowance set to ${self._mock_allowance:.2f}")
        return "0xmock_tx_hash"

    def ensure_sufficient_allowance(self, required_amount: float) -> bool:
        """Mock ensure always returns True."""
        return True
