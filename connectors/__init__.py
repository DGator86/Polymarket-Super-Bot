# Connectors package
# Lazy imports to avoid circular dependencies

def get_kalshi_client():
    from connectors.kalshi import KalshiClient, create_kalshi_client
    return KalshiClient, create_kalshi_client

def get_fred_client():
    from connectors.fred import FREDClient, create_fred_client
    return FREDClient, create_fred_client

def get_noaa_client():
    from connectors.noaa import NOAAClient, create_noaa_client
    return NOAAClient, create_noaa_client

def get_coinbase_client():
    from connectors.coinbase import CoinbaseClient, create_coinbase_client
    return CoinbaseClient, create_coinbase_client

def get_bls_client():
    from connectors.bls import BLSClient, create_bls_client
    return BLSClient, create_bls_client

__all__ = [
    'get_kalshi_client', 'get_fred_client', 'get_noaa_client', 
    'get_coinbase_client', 'get_bls_client'
]
