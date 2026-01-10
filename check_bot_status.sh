#!/bin/bash

# Polymarket Bot Status Checker
# Usage: ./check_bot_status.sh [--remote VPS_IP]

set -e

REMOTE_IP="${2:-161.35.148.153}"
REMOTE_USER="${REMOTE_USER:-root}"

echo "========================================"
echo "  POLYMARKET BOT STATUS CHECKER"
echo "========================================"
echo ""

# Function to check local status
check_local() {
    echo "Checking LOCAL bot status..."
    echo ""

    # Check if Docker is running
    echo "[1/5] Checking Docker containers..."
    if command -v docker &> /dev/null; then
        CONTAINER=$(docker ps -a --filter "name=polymarket" --format "table {{.Names}}\t{{.Status}}\t{{.Image}}" 2>/dev/null || echo "")
        if [ -n "$CONTAINER" ]; then
            echo "$CONTAINER"
        else
            echo "   ❌ No Docker containers found"
        fi
    else
        echo "   ⚠️  Docker not installed or not accessible"
    fi
    echo ""

    # Check if Python process is running
    echo "[2/5] Checking Python processes..."
    PYTHON_PROCS=$(ps aux | grep -E "(run.py|src.app)" | grep -v grep || echo "")
    if [ -n "$PYTHON_PROCS" ]; then
        echo "   ✅ Bot processes found:"
        echo "$PYTHON_PROCS" | awk '{print "      PID " $2 ": " $11 " " $12 " " $13}'
    else
        echo "   ❌ No bot Python processes found"
    fi
    echo ""

    # Check database
    echo "[3/5] Checking database..."
    if [ -f "bot/bot_state_smart.db" ]; then
        DB_SIZE=$(du -h bot/bot_state_smart.db | cut -f1)
        DB_MODIFIED=$(stat -c %y bot/bot_state_smart.db 2>/dev/null || stat -f "%Sm" bot/bot_state_smart.db 2>/dev/null || echo "Unknown")
        echo "   ✅ Database found: bot_state_smart.db ($DB_SIZE)"
        echo "      Last modified: $DB_MODIFIED"

        # Check recent activity
        if command -v sqlite3 &> /dev/null; then
            RECENT_FILLS=$(sqlite3 bot/bot_state_smart.db "SELECT COUNT(*) FROM fills WHERE ts > (strftime('%s', 'now') - 3600) * 1000" 2>/dev/null || echo "0")
            echo "      Recent fills (last hour): $RECENT_FILLS"
        fi
    else
        echo "   ❌ Database not found at bot/bot_state_smart.db"
    fi
    echo ""

    # Check logs
    echo "[4/5] Checking logs..."
    if [ -f "bot/bot.log" ]; then
        LOG_SIZE=$(du -h bot/bot.log | cut -f1)
        echo "   ✅ Log file found: bot.log ($LOG_SIZE)"
        echo "      Last 3 lines:"
        tail -n 3 bot/bot.log | sed 's/^/      /'
    else
        echo "   ⚠️  No bot.log file found"
    fi
    echo ""

    # Check configuration
    echo "[5/5] Checking configuration..."
    if [ -f "bot/.env" ]; then
        echo "   ✅ Configuration file found: .env"

        # Check key settings (without revealing sensitive data)
        DRY_RUN=$(grep "^DRY_RUN=" bot/.env | cut -d'=' -f2 || echo "not set")
        KILL_SWITCH=$(grep "^KILL_SWITCH=" bot/.env | cut -d'=' -f2 || echo "not set")

        echo "      DRY_RUN: $DRY_RUN"
        echo "      KILL_SWITCH: $KILL_SWITCH"

        if [ "$DRY_RUN" = "1" ]; then
            echo "      ⚠️  Bot is in DRY RUN mode (not trading real money)"
        fi

        if [ "$KILL_SWITCH" = "1" ]; then
            echo "      ⚠️  KILL SWITCH is ACTIVE (bot is disabled)"
        fi
    else
        echo "   ❌ No .env configuration file found"
    fi
}

# Function to check remote status
check_remote() {
    echo "Checking REMOTE bot status on $REMOTE_IP..."
    echo ""

    # Test SSH connection
    echo "Testing SSH connection to $REMOTE_USER@$REMOTE_IP..."
    if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "$REMOTE_USER@$REMOTE_IP" "echo 'SSH connection successful'" 2>/dev/null; then
        echo "❌ Cannot connect to VPS via SSH"
        echo ""
        echo "To enable SSH access:"
        echo "  1. Make sure you have SSH access to your VPS"
        echo "  2. Run: ssh-copy-id $REMOTE_USER@$REMOTE_IP"
        echo "  3. Or run this script on the VPS directly"
        echo ""
        exit 1
    fi

    echo "✅ SSH connection successful"
    echo ""

    # Run checks on remote
    ssh "$REMOTE_USER@$REMOTE_IP" << 'ENDSSH'
        echo "[1/5] Checking Docker containers..."
        if command -v docker &> /dev/null; then
            CONTAINER=$(docker ps -a --filter "name=polymarket" --format "table {{.Names}}\t{{.Status}}\t{{.Image}}" 2>/dev/null || echo "")
            if [ -n "$CONTAINER" ]; then
                echo "$CONTAINER"

                # Check container logs
                echo ""
                echo "   Recent container logs (last 5 lines):"
                docker logs polymarket-bot --tail 5 2>/dev/null | sed 's/^/      /' || echo "      Cannot access logs"
            else
                echo "   ❌ No Docker containers found"
            fi
        else
            echo "   ⚠️  Docker not installed"
        fi
        echo ""

        echo "[2/5] Checking Python processes..."
        PYTHON_PROCS=$(ps aux | grep -E "(run.py|src.app)" | grep -v grep || echo "")
        if [ -n "$PYTHON_PROCS" ]; then
            echo "   ✅ Bot processes found:"
            echo "$PYTHON_PROCS" | awk '{print "      PID " $2 ": " $11 " " $12 " " $13}'
        else
            echo "   ❌ No bot Python processes found"
        fi
        echo ""

        echo "[3/5] Checking for bot directory..."
        if [ -d "/root/Polymarket-Super-Bot" ] || [ -d "~/Polymarket-Super-Bot" ] || [ -d "/app" ]; then
            if [ -d "/root/Polymarket-Super-Bot" ]; then
                BOT_DIR="/root/Polymarket-Super-Bot/bot"
            elif [ -d "~/Polymarket-Super-Bot" ]; then
                BOT_DIR="~/Polymarket-Super-Bot/bot"
            else
                BOT_DIR="/app"
            fi

            echo "   ✅ Bot directory found at: $BOT_DIR"

            # Check database
            if [ -f "$BOT_DIR/bot_state_smart.db" ]; then
                DB_SIZE=$(du -h "$BOT_DIR/bot_state_smart.db" | cut -f1)
                echo "   ✅ Database found ($DB_SIZE)"
            else
                echo "   ⚠️  Database not found"
            fi
        else
            echo "   ❌ Bot directory not found"
        fi
        echo ""

        echo "[4/5] Checking system resources..."
        echo "   CPU Usage:"
        top -bn1 | grep "Cpu(s)" | sed 's/^/      /'
        echo "   Memory Usage:"
        free -h | grep Mem | sed 's/^/      /'
        echo "   Disk Usage:"
        df -h / | tail -1 | sed 's/^/      /'
        echo ""

        echo "[5/5] Checking network connectivity..."
        if ping -c 1 clob.polymarket.com &> /dev/null; then
            echo "   ✅ Can reach Polymarket API"
        else
            echo "   ❌ Cannot reach Polymarket API"
        fi
ENDSSH
}

# Main logic
echo ""
if [ "$1" = "--remote" ]; then
    check_remote
else
    echo "Mode: LOCAL CHECK"
    echo ""
    check_local
    echo ""
    echo "========================================"
    echo "To check your VPS remotely, run:"
    echo "  ./check_bot_status.sh --remote $REMOTE_IP"
    echo ""
    echo "Or copy this script to your VPS and run it there:"
    echo "  scp check_bot_status.sh $REMOTE_USER@$REMOTE_IP:~/"
    echo "  ssh $REMOTE_USER@$REMOTE_IP './check_bot_status.sh'"
    echo "========================================"
fi

echo ""
