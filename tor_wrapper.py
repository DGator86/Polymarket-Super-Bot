#!/usr/bin/env python3
"""
Tor Proxy Wrapper for Kalshi API
Routes all requests through Tor SOCKS5 proxy to bypass CloudFront blocks
"""
import socks
import socket

# Configure global SOCKS proxy BEFORE any other imports
socks.set_default_proxy(socks.SOCKS5, '127.0.0.1', 9050)
socket.socket = socks.socksocket

# Now import and run the paper trading bot
import sys
sys.argv = ['run_paper_trading.py', '--capital', '1000', '--interval', '60']
exec(open('run_paper_trading.py').read())
