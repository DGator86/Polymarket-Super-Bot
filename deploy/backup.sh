#!/bin/bash
# Kalshi Prediction Bot - Backup Script
# Creates backups of database and configuration

set -e

# Configuration
BOT_DIR="${BOT_DIR:-/opt/kalshi-prediction-bot}"
DATA_DIR="${DATA_DIR:-/var/lib/kalshi-bot}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/kalshi-bot}"
RETENTION_DAYS=30

# Get date for backup filename
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="kalshi_backup_$DATE"

echo "=============================================="
echo "Kalshi Prediction Bot - Backup"
echo "=============================================="
echo "Date: $(date)"
echo ""

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Create temporary directory for backup
TMP_DIR=$(mktemp -d)
mkdir -p "$TMP_DIR/$BACKUP_NAME"

# Backup database
if [ -f "$DATA_DIR/trades.db" ]; then
    echo "Backing up database..."
    cp "$DATA_DIR/trades.db" "$TMP_DIR/$BACKUP_NAME/"
else
    echo "No database found at $DATA_DIR/trades.db"
fi

# Backup configuration (without sensitive data)
if [ -f "$BOT_DIR/.env" ]; then
    echo "Backing up configuration..."
    # Create sanitized version of .env (remove actual values)
    grep -E "^[A-Z_]+=" "$BOT_DIR/.env" | sed 's/=.*/=REDACTED/' > "$TMP_DIR/$BACKUP_NAME/env.template"
fi

# Backup RSA public key (not private!)
if [ -f "$BOT_DIR/kalshi_public_key.pem" ]; then
    echo "Backing up public key..."
    cp "$BOT_DIR/kalshi_public_key.pem" "$TMP_DIR/$BACKUP_NAME/"
fi

# Export trade history if database exists
if [ -f "$DATA_DIR/trades.db" ]; then
    echo "Exporting trade history..."
    sqlite3 "$DATA_DIR/trades.db" ".mode csv" ".headers on" ".output $TMP_DIR/$BACKUP_NAME/trades.csv" "SELECT * FROM trades ORDER BY entry_time DESC;"
    sqlite3 "$DATA_DIR/trades.db" ".mode csv" ".headers on" ".output $TMP_DIR/$BACKUP_NAME/signals.csv" "SELECT * FROM signals ORDER BY timestamp DESC;"
    sqlite3 "$DATA_DIR/trades.db" ".mode csv" ".headers on" ".output $TMP_DIR/$BACKUP_NAME/daily_stats.csv" "SELECT * FROM daily_stats ORDER BY date DESC;"
fi

# Create backup info
cat > "$TMP_DIR/$BACKUP_NAME/backup_info.txt" << EOF
Kalshi Prediction Bot Backup
============================
Date: $(date)
Host: $(hostname)
Bot Version: $(cd $BOT_DIR && git rev-parse --short HEAD 2>/dev/null || echo "unknown")
Database Size: $(du -h "$DATA_DIR/trades.db" 2>/dev/null | cut -f1 || echo "N/A")
EOF

# Create compressed archive
echo "Creating archive..."
cd "$TMP_DIR"
tar -czf "$BACKUP_DIR/$BACKUP_NAME.tar.gz" "$BACKUP_NAME"

# Cleanup temp directory
rm -rf "$TMP_DIR"

# Calculate backup size
BACKUP_SIZE=$(du -h "$BACKUP_DIR/$BACKUP_NAME.tar.gz" | cut -f1)

echo ""
echo "Backup created: $BACKUP_DIR/$BACKUP_NAME.tar.gz ($BACKUP_SIZE)"

# Delete old backups
echo ""
echo "Cleaning up old backups (older than $RETENTION_DAYS days)..."
find "$BACKUP_DIR" -name "kalshi_backup_*.tar.gz" -type f -mtime +$RETENTION_DAYS -delete -print

# List existing backups
echo ""
echo "Existing backups:"
ls -lh "$BACKUP_DIR"/kalshi_backup_*.tar.gz 2>/dev/null | tail -10

echo ""
echo "Backup complete!"
