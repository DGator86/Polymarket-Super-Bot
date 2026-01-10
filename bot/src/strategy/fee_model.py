"""
Fee-aware edge calculation.
Ensures trades are only taken if they cover fixed and variable costs.
Models the "Taker Fee Curve" (peaking at 0.50) and Maker Rebates.
"""
from src.logging_setup import get_logger

logger = get_logger("fee_model")

class FeeModel:
    """
    Calculates required edge to cover fees.
    """
    
    def __init__(self, gas_cost_usd: float = 0.01, base_taker_fee: float = 0.02, maker_rebate: float = 0.002):
        self.gas_cost_usd = gas_cost_usd
        self.base_taker_fee = base_taker_fee # Max fee at 0.50
        self.maker_rebate = maker_rebate # Rebate earned
        
    def get_taker_fee_rate(self, price: float, market_type: str = "default") -> float:
        """
        Estimate taker fee rate based on price.
        
        Args:
            price: Price level (0.0 to 1.0)
            market_type: "rolling15" or "default"
        """
        if market_type != "rolling15":
            return 0.0 # Most binary markets are fee-free for takers
            
        # Clamp price
        p = max(0.0, min(1.0, price))
        
        # Parabolic curve for Rolling 15s
        factor = 1.0 - 4.0 * ((p - 0.5) ** 2)
        factor = max(0.0, factor) # Ensure non-negative
        
        return self.base_taker_fee * factor

    def get_min_edge(self, trade_size_usd: float, price: float, is_taker: bool, market_type: str = "default") -> float:
        """
        Calculate minimum price edge required to break even.
        """
        if trade_size_usd <= 0:
            return 1.0
            
        # Fixed cost impact (Gas)
        fixed_impact = self.gas_cost_usd / trade_size_usd
        
        # Variable fees
        if is_taker:
            var_fee = self.get_taker_fee_rate(price, market_type)
        else:
            # Maker Rebate (Only on Rolling 15s)
            if market_type == "rolling15":
                var_fee = -self.maker_rebate
            else:
                var_fee = 0.0
        
        # Profit Buffer (Risk premium)
        buffer = 0.015 if is_taker else 0.005
        
        total_edge = fixed_impact + var_fee + buffer
        
        return max(0.0, total_edge)
