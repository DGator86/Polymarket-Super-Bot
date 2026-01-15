#!/bin/bash
# Kalshi Prediction Bot - Run Script
# Simple script to run the bot locally

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

echo "=============================================="
echo "Kalshi Prediction Bot"
echo "=============================================="

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required"
    exit 1
fi

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install/update dependencies
echo "Checking dependencies..."
pip install -q -r requirements.txt

# Check for .env file
if [ ! -f ".env" ]; then
    echo "Error: .env file not found!"
    echo "Please copy .env.example to .env and configure your API credentials."
    exit 1
fi

# Check for RSA keys
if [ ! -f "kalshi_private_key.pem" ]; then
    echo ""
    echo "RSA keys not found. Generating..."
    openssl genrsa -out kalshi_private_key.pem 4096
    openssl rsa -in kalshi_private_key.pem -pubout -out kalshi_public_key.pem
    chmod 600 kalshi_private_key.pem
    echo ""
    echo "========================================="
    echo "IMPORTANT: Upload this public key to Kalshi!"
    echo "========================================="
    cat kalshi_public_key.pem
    echo ""
    echo "Press Enter to continue after uploading..."
    read
fi

# Parse arguments
DRY_RUN=""
LOG_LEVEL=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN="--dry-run"
            shift
            ;;
        --log-level)
            LOG_LEVEL="$2"
            shift 2
            ;;
        --live)
            echo "WARNING: Running in LIVE TRADING mode!"
            echo "Press Enter to confirm or Ctrl+C to cancel..."
            read
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Set log level if provided
if [ -n "$LOG_LEVEL" ]; then
    export LOG_LEVEL
fi

echo ""
echo "Starting bot..."
echo "Press Ctrl+C to stop"
echo ""

# Run the bot
python main.py $DRY_RUN
