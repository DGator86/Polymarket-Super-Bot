# Polymarket Bot VPS Deployment Guide

## Quick Start (One Command)

SSH into your VPS and run this single command:

```bash
curl -fsSL https://raw.githubusercontent.com/DGator86/Polymarket-Super-Bot/main/deploy_to_vps.sh | bash
```

Or if you prefer to review the script first:

```bash
wget https://raw.githubusercontent.com/DGator86/Polymarket-Super-Bot/main/deploy_to_vps.sh
chmod +x deploy_to_vps.sh
./deploy_to_vps.sh
```

---

## Manual Step-by-Step Deployment

### 1. Connect to Your VPS

```bash
ssh root@161.35.148.153
```

### 2. Run the Deployment Script

```bash
# Download and run
curl -fsSL https://raw.githubusercontent.com/DGator86/Polymarket-Super-Bot/main/deploy_to_vps.sh -o deploy.sh
chmod +x deploy.sh
sudo ./deploy.sh
```

The script will:
- ✅ Update system packages
- ✅ Install Docker & Docker Compose
- ✅ Clone the bot repository
- ✅ Set up configuration files
- ✅ Build Docker image
- ⚠️ Wait for you to configure API keys

### 3. Configure Your Bot

Edit the configuration file:

```bash
nano /root/Polymarket-Super-Bot/bot/.env
```

**Required settings:**
- `POLYMARKET_API_KEY` - Your Polymarket API key
- `POLYMARKET_API_SECRET` - Your API secret
- `POLYMARKET_PRIVATE_KEY` - Your wallet private key
- `POLYMARKET_PASSPHRASE` - Your API passphrase

**Important trading settings:**
- `DRY_RUN=0` - Set to 1 for testing without real money
- `KILL_SWITCH=0` - Emergency stop (set to 1 to disable trading)
- `MAX_POSITION_SIZE` - Maximum $ per position
- `DAILY_LOSS_LIMIT` - Stop trading after this much loss

### 4. Start the Bot

```bash
cd /root/Polymarket-Super-Bot/bot
docker-compose up -d
```

### 5. Verify It's Running

```bash
# Check container status
docker ps -a | grep polymarket

# View live logs
docker logs -f polymarket-bot

# Check recent activity (last 50 lines)
docker logs --tail 50 polymarket-bot
```

---

## Useful Commands

### Monitoring

```bash
# View real-time logs
docker logs -f polymarket-bot

# Check if bot is running
docker ps | grep polymarket

# Check bot status with included script
cd /root/Polymarket-Super-Bot
./check_bot_status.sh
```

### Control

```bash
# Stop the bot
docker-compose down

# Restart the bot
docker-compose restart

# Start the bot
docker-compose up -d

# Rebuild after code changes
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

### Maintenance

```bash
# View database
sqlite3 /root/Polymarket-Super-Bot/bot/bot_state_smart.db

# Check recent trades
sqlite3 /root/Polymarket-Super-Bot/bot/bot_state_smart.db "SELECT * FROM fills ORDER BY ts DESC LIMIT 10;"

# Backup configuration
cp /root/Polymarket-Super-Bot/bot/.env /root/.env.backup

# Update bot to latest version
cd /root/Polymarket-Super-Bot
git pull origin main
cd bot
docker-compose down
docker-compose build
docker-compose up -d
```

---

## Troubleshooting

### Bot Won't Start

1. **Check configuration:**
   ```bash
   cat /root/Polymarket-Super-Bot/bot/.env | grep -E "(API_KEY|PRIVATE_KEY|PASSPHRASE)"
   ```
   Make sure no placeholder values remain.

2. **Check logs for errors:**
   ```bash
   docker logs polymarket-bot --tail 100
   ```

3. **Verify Docker is running:**
   ```bash
   systemctl status docker
   ```

### Bot Keeps Restarting

```bash
# Check what's causing the crash
docker logs polymarket-bot --tail 200

# Common issues:
# - Invalid API credentials
# - Network connectivity problems
# - Insufficient funds in wallet
```

### Can't Connect to VPS

1. Verify VPS is running in DigitalOcean dashboard
2. Check your local SSH config
3. Try connecting with password: `ssh root@161.35.148.153`

### Performance Issues

```bash
# Check system resources
htop

# Check disk space
df -h

# Check memory usage
free -h

# View Docker stats
docker stats
```

---

## Security Best Practices

1. **Change default SSH port** (optional but recommended):
   ```bash
   nano /etc/ssh/sshd_config
   # Change Port 22 to something else
   systemctl restart sshd
   ```

2. **Set up firewall:**
   ```bash
   ufw allow 22/tcp  # SSH
   ufw allow 8501/tcp  # Dashboard (optional)
   ufw enable
   ```

3. **Regular backups:**
   ```bash
   # Backup database and config daily
   crontab -e
   # Add: 0 2 * * * cp /root/Polymarket-Super-Bot/bot/bot_state_smart.db /root/backups/bot_$(date +\%Y\%m\%d).db
   ```

4. **Monitor bot activity:**
   - Set up alerts for unusual trading patterns
   - Check logs daily
   - Monitor wallet balance

---

## Quick Reference

| Task | Command |
|------|---------|
| Start bot | `docker-compose up -d` |
| Stop bot | `docker-compose down` |
| View logs | `docker logs -f polymarket-bot` |
| Restart | `docker-compose restart` |
| Update bot | `git pull && docker-compose build && docker-compose up -d` |
| Check status | `docker ps \| grep polymarket` |
| Edit config | `nano /root/Polymarket-Super-Bot/bot/.env` |

---

## Support

- GitHub Issues: https://github.com/DGator86/Polymarket-Super-Bot/issues
- Check bot status: `./check_bot_status.sh`
- Polymarket API docs: https://docs.polymarket.com/
