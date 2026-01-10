#!/bin/bash

# Polymarket Bot VPS Deployment Script
# This script will set up and deploy the Polymarket bot on a fresh Ubuntu VPS
# Usage: Run this script on your VPS after SSHing in

set -e

echo "========================================"
echo "  POLYMARKET BOT VPS DEPLOYMENT"
echo "========================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    print_error "Please run as root (use: sudo su)"
    exit 1
fi

print_status "Starting deployment process..."
echo ""

# Step 1: Update system
echo "[1/8] Updating system packages..."
apt-get update -qq > /dev/null 2>&1
apt-get upgrade -y -qq > /dev/null 2>&1
print_status "System updated"
echo ""

# Step 2: Install Docker
echo "[2/8] Installing Docker..."
if command -v docker &> /dev/null; then
    print_warning "Docker already installed, skipping..."
else
    curl -fsSL https://get.docker.com -o get-docker.sh
    sh get-docker.sh > /dev/null 2>&1
    rm get-docker.sh
    systemctl start docker
    systemctl enable docker
    print_status "Docker installed and started"
fi
echo ""

# Step 3: Install Docker Compose
echo "[3/8] Installing Docker Compose..."
if command -v docker-compose &> /dev/null; then
    print_warning "Docker Compose already installed, skipping..."
else
    apt-get install -y docker-compose -qq > /dev/null 2>&1
    print_status "Docker Compose installed"
fi
echo ""

# Step 4: Install Git (if needed)
echo "[4/8] Checking Git installation..."
if ! command -v git &> /dev/null; then
    apt-get install -y git -qq > /dev/null 2>&1
    print_status "Git installed"
else
    print_warning "Git already installed"
fi
echo ""

# Step 5: Clone repository
echo "[5/8] Cloning Polymarket Bot repository..."
cd /root
if [ -d "Polymarket-Super-Bot" ]; then
    print_warning "Repository already exists, pulling latest changes..."
    cd Polymarket-Super-Bot
    git pull origin main
else
    git clone https://github.com/DGator86/Polymarket-Super-Bot.git
    cd Polymarket-Super-Bot
    print_status "Repository cloned"
fi
echo ""

# Step 6: Setup configuration
echo "[6/8] Setting up configuration..."
cd bot

if [ -f ".env" ]; then
    print_warning ".env file already exists"
    echo "   Current configuration will be preserved"
    echo "   Backup created at .env.backup.$(date +%s)"
    cp .env .env.backup.$(date +%s)
else
    print_warning "Creating .env from template..."
    cp .env.example .env
    echo ""
    print_error "IMPORTANT: You must configure your .env file with:"
    echo "   1. Your Polymarket API credentials"
    echo "   2. Private key / wallet information"
    echo "   3. Trading parameters"
    echo ""
    echo "   Edit the file with: nano /root/Polymarket-Super-Bot/bot/.env"
    echo ""
    print_warning "Bot will NOT start until .env is properly configured!"
    echo ""
fi

# Check if critical env vars are set
if grep -q "YOUR_PRIVATE_KEY_HERE" .env 2>/dev/null || grep -q "your_key_here" .env 2>/dev/null; then
    print_error "⚠️  WARNING: .env contains placeholder values!"
    echo "   You must edit .env before starting the bot"
    echo ""
fi
echo ""

# Step 7: Build Docker image
echo "[7/8] Building Docker image..."
print_warning "This may take a few minutes on first run..."

cd /root/Polymarket-Super-Bot/bot

if [ -f "docker-compose.yml" ]; then
    docker-compose build
    print_status "Docker image built successfully"
else
    # If no docker-compose.yml, build using Dockerfile
    docker build -t polymarket-bot -f docker/Dockerfile .
    print_status "Docker image built successfully"
fi
echo ""

# Step 8: Start the bot
echo "[8/8] Starting the bot..."

# Check if we should auto-start or wait for user
if grep -q "YOUR_PRIVATE_KEY_HERE" .env 2>/dev/null || grep -q "your_key_here" .env 2>/dev/null; then
    print_warning "Not starting bot - configuration needed first"
    echo ""
    echo "========================================"
    echo "  DEPLOYMENT COMPLETE (Configuration Required)"
    echo "========================================"
    echo ""
    echo "Next steps:"
    echo "  1. Edit configuration: nano /root/Polymarket-Super-Bot/bot/.env"
    echo "  2. Add your Polymarket API credentials"
    echo "  3. Set your private key and trading parameters"
    echo "  4. Start the bot: cd /root/Polymarket-Super-Bot/bot && docker-compose up -d"
    echo "  5. Check logs: docker logs -f polymarket-bot"
    echo ""
else
    if [ -f "docker-compose.yml" ]; then
        docker-compose down 2>/dev/null || true
        docker-compose up -d
    else
        docker stop polymarket-bot 2>/dev/null || true
        docker rm polymarket-bot 2>/dev/null || true
        docker run -d --name polymarket-bot \
            -v /root/Polymarket-Super-Bot/bot:/app \
            --restart unless-stopped \
            polymarket-bot
    fi

    sleep 3

    # Check if container is running
    if docker ps | grep -q polymarket; then
        print_status "Bot started successfully!"
        echo ""
        echo "========================================"
        echo "  DEPLOYMENT COMPLETE"
        echo "========================================"
        echo ""
        echo "Bot Status:"
        docker ps | grep polymarket | awk '{print "   Container: " $NF "\n   Status: " $(NF-1)}'
        echo ""
        echo "Useful commands:"
        echo "   View logs:     docker logs -f polymarket-bot"
        echo "   Stop bot:      docker-compose down"
        echo "   Restart bot:   docker-compose restart"
        echo "   Check status:  docker ps -a | grep polymarket"
        echo ""
        echo "Monitor your bot:"
        echo "   Dashboard:     http://161.35.148.153:8501 (if web dashboard is enabled)"
        echo "   Database:      /root/Polymarket-Super-Bot/bot/bot_state_smart.db"
        echo ""
    else
        print_error "Container failed to start!"
        echo "Check logs with: docker logs polymarket-bot"
        exit 1
    fi
fi

echo "Installation location: /root/Polymarket-Super-Bot"
echo ""
print_status "Deployment script completed!"
