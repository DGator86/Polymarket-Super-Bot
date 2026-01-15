"""
Telegram & Discord Alert System

Real-time trade notifications via:
- Telegram Bot API
- Discord Webhooks

Sends alerts for:
- Trade executions
- Signals generated
- Circuit breaker events
- Daily P&L summaries
- Error conditions
"""

import asyncio
import aiohttp
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from enum import Enum
import json

from config import config
from core.models import TradingSignal, OrderResponse, Side, OrderStatus

logger = logging.getLogger(__name__)


class AlertLevel(Enum):
    """Alert severity levels"""
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AlertType(Enum):
    """Types of alerts"""
    SIGNAL = "signal"
    TRADE = "trade"
    FILL = "fill"
    CANCEL = "cancel"
    CIRCUIT_BREAKER = "circuit_breaker"
    DAILY_SUMMARY = "daily_summary"
    ERROR = "error"
    SYSTEM = "system"


@dataclass
class Alert:
    """Alert message structure"""
    alert_type: AlertType
    level: AlertLevel
    title: str
    message: str
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> Dict:
        return {
            "type": self.alert_type.value,
            "level": self.level.value,
            "title": self.title,
            "message": self.message,
            "data": self.data,
            "timestamp": self.timestamp.isoformat()
        }


# =============================================================================
# TELEGRAM ALERTER
# =============================================================================

class TelegramAlerter:
    """
    Send alerts via Telegram Bot API.
    
    Setup:
    1. Create bot via @BotFather
    2. Get bot token
    3. Get your chat_id (message the bot, check updates)
    4. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env
    
    Usage:
        alerter = TelegramAlerter(token, chat_id)
        await alerter.send_alert(alert)
    """
    
    API_BASE = "https://api.telegram.org/bot"
    
    def __init__(
        self,
        bot_token: str = None,
        chat_id: str = None,
        parse_mode: str = "HTML"
    ):
        self.bot_token = bot_token or config.alerts.telegram_bot_token
        self.chat_id = chat_id or config.alerts.telegram_chat_id
        self.parse_mode = parse_mode
        self.session: Optional[aiohttp.ClientSession] = None
        self._enabled = bool(self.bot_token and self.chat_id)
    
    @property
    def enabled(self) -> bool:
        return self._enabled
    
    async def connect(self):
        """Initialize HTTP session"""
        if not self._enabled:
            logger.warning("Telegram alerter not configured - alerts disabled")
            return
        
        self.session = aiohttp.ClientSession()
        
        # Verify bot token
        try:
            result = await self._request("getMe")
            bot_name = result.get("username", "Unknown")
            logger.info(f"Telegram alerter connected as @{bot_name}")
        except Exception as e:
            logger.error(f"Telegram connection failed: {e}")
            self._enabled = False
    
    async def close(self):
        """Close HTTP session"""
        if self.session:
            await self.session.close()
    
    async def _request(self, method: str, data: Dict = None) -> Dict:
        """Make Telegram API request"""
        if not self.session:
            await self.connect()
        
        url = f"{self.API_BASE}{self.bot_token}/{method}"
        
        async with self.session.post(url, json=data) as resp:
            result = await resp.json()
            
            if not result.get("ok"):
                raise Exception(f"Telegram API error: {result.get('description', 'Unknown')}")
            
            return result.get("result", {})
    
    async def send_message(self, text: str, disable_notification: bool = False) -> bool:
        """Send raw text message"""
        if not self._enabled:
            return False
        
        try:
            await self._request("sendMessage", {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": self.parse_mode,
                "disable_notification": disable_notification
            })
            return True
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False
    
    async def send_alert(self, alert: Alert) -> bool:
        """Send formatted alert"""
        if not self._enabled:
            return False
        
        # Format message based on type
        message = self._format_alert(alert)
        
        # Only notify for important alerts
        silent = alert.level in [AlertLevel.INFO]
        
        return await self.send_message(message, disable_notification=silent)
    
    def _format_alert(self, alert: Alert) -> str:
        """Format alert for Telegram (HTML)"""
        # Level emoji
        level_emoji = {
            AlertLevel.INFO: "ℹ️",
            AlertLevel.SUCCESS: "✅",
            AlertLevel.WARNING: "⚠️",
            AlertLevel.ERROR: "❌",
            AlertLevel.CRITICAL: "🚨"
        }.get(alert.level, "📢")
        
        # Type emoji
        type_emoji = {
            AlertType.SIGNAL: "📊",
            AlertType.TRADE: "💰",
            AlertType.FILL: "🎯",
            AlertType.CANCEL: "🚫",
            AlertType.CIRCUIT_BREAKER: "🛑",
            AlertType.DAILY_SUMMARY: "📈",
            AlertType.ERROR: "💥",
            AlertType.SYSTEM: "⚙️"
        }.get(alert.alert_type, "📋")
        
        # Build message
        lines = [
            f"{level_emoji} {type_emoji} <b>{alert.title}</b>",
            "",
            alert.message
        ]
        
        # Add data fields
        if alert.data:
            lines.append("")
            for key, value in alert.data.items():
                if isinstance(value, float):
                    value = f"{value:.4f}"
                elif isinstance(value, Decimal):
                    value = f"{float(value):.4f}"
                lines.append(f"<b>{key}:</b> {value}")
        
        # Timestamp
        lines.append("")
        lines.append(f"<i>{alert.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}</i>")
        
        return "\n".join(lines)


# =============================================================================
# DISCORD ALERTER
# =============================================================================

class DiscordAlerter:
    """
    Send alerts via Discord Webhooks.
    
    Setup:
    1. In Discord server, go to Channel Settings > Integrations > Webhooks
    2. Create webhook, copy URL
    3. Set DISCORD_WEBHOOK_URL in .env
    
    Usage:
        alerter = DiscordAlerter(webhook_url)
        await alerter.send_alert(alert)
    """
    
    def __init__(self, webhook_url: str = None, username: str = "Kalshi Bot"):
        self.webhook_url = webhook_url or config.alerts.discord_webhook_url
        self.username = username
        self.session: Optional[aiohttp.ClientSession] = None
        self._enabled = bool(self.webhook_url)
    
    @property
    def enabled(self) -> bool:
        return self._enabled
    
    async def connect(self):
        """Initialize HTTP session"""
        if not self._enabled:
            logger.warning("Discord alerter not configured - alerts disabled")
            return
        
        self.session = aiohttp.ClientSession()
        logger.info("Discord alerter connected")
    
    async def close(self):
        """Close HTTP session"""
        if self.session:
            await self.session.close()
    
    async def send_message(self, content: str = None, embed: Dict = None) -> bool:
        """Send message to Discord webhook"""
        if not self._enabled:
            return False
        
        if not self.session:
            await self.connect()
        
        payload = {"username": self.username}
        
        if content:
            payload["content"] = content
        if embed:
            payload["embeds"] = [embed]
        
        try:
            async with self.session.post(self.webhook_url, json=payload) as resp:
                if resp.status not in [200, 204]:
                    text = await resp.text()
                    raise Exception(f"Discord webhook error: {resp.status} - {text}")
                return True
        except Exception as e:
            logger.error(f"Failed to send Discord message: {e}")
            return False
    
    async def send_alert(self, alert: Alert) -> bool:
        """Send formatted alert as Discord embed"""
        if not self._enabled:
            return False
        
        embed = self._format_embed(alert)
        return await self.send_message(embed=embed)
    
    def _format_embed(self, alert: Alert) -> Dict:
        """Format alert as Discord embed"""
        # Color based on level
        colors = {
            AlertLevel.INFO: 0x3498db,      # Blue
            AlertLevel.SUCCESS: 0x2ecc71,   # Green
            AlertLevel.WARNING: 0xf39c12,   # Orange
            AlertLevel.ERROR: 0xe74c3c,     # Red
            AlertLevel.CRITICAL: 0x9b59b6   # Purple
        }
        
        embed = {
            "title": alert.title,
            "description": alert.message,
            "color": colors.get(alert.level, 0x95a5a6),
            "timestamp": alert.timestamp.isoformat(),
            "footer": {
                "text": f"{alert.alert_type.value.upper()} | {alert.level.value.upper()}"
            }
        }
        
        # Add fields for data
        if alert.data:
            fields = []
            for key, value in alert.data.items():
                if isinstance(value, (float, Decimal)):
                    value = f"{float(value):.4f}"
                fields.append({
                    "name": key.replace("_", " ").title(),
                    "value": str(value),
                    "inline": True
                })
            embed["fields"] = fields[:25]  # Discord limit
        
        return embed


# =============================================================================
# UNIFIED ALERT MANAGER
# =============================================================================

class AlertManager:
    """
    Unified alert manager that sends to all configured channels.
    
    Usage:
        manager = AlertManager()
        await manager.connect()
        await manager.send_trade_alert(signal, order)
    """
    
    def __init__(self):
        self.telegram = TelegramAlerter()
        self.discord = DiscordAlerter()
        self._queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._worker_task: Optional[asyncio.Task] = None
    
    async def connect(self):
        """Connect all alerters"""
        await self.telegram.connect()
        await self.discord.connect()
        
        # Start background worker
        self._running = True
        self._worker_task = asyncio.create_task(self._process_queue())
        
        logger.info(f"Alert manager connected (Telegram: {self.telegram.enabled}, Discord: {self.discord.enabled})")
    
    async def close(self):
        """Close all alerters"""
        self._running = False
        
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        
        await self.telegram.close()
        await self.discord.close()
    
    async def _process_queue(self):
        """Background worker to process alert queue"""
        while self._running:
            try:
                alert = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                await self._send_to_all(alert)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Error processing alert: {e}")
    
    async def _send_to_all(self, alert: Alert):
        """Send alert to all enabled channels"""
        tasks = []
        
        if self.telegram.enabled:
            tasks.append(self.telegram.send_alert(alert))
        
        if self.discord.enabled:
            tasks.append(self.discord.send_alert(alert))
        
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"Alert send failed: {result}")
    
    async def send_alert(self, alert: Alert):
        """Queue an alert for sending"""
        await self._queue.put(alert)
    
    # =========================================================================
    # CONVENIENCE METHODS
    # =========================================================================
    
    async def send_signal_alert(self, signal: TradingSignal):
        """Send alert for new trading signal"""
        alert = Alert(
            alert_type=AlertType.SIGNAL,
            level=AlertLevel.INFO,
            title=f"New Signal: {signal.ticker}",
            message=f"{'BUY' if signal.side == Side.YES else 'SELL'} {signal.side.value.upper()} - Edge: {float(signal.edge)*100:.2f}%",
            data={
                "ticker": signal.ticker,
                "side": signal.side.value,
                "model_prob": signal.model_probability,
                "market_prob": signal.market_probability,
                "edge": signal.edge,
                "confidence": signal.confidence,
                "reason": signal.reason
            }
        )
        await self.send_alert(alert)
    
    async def send_trade_alert(self, signal: TradingSignal, order: OrderResponse):
        """Send alert for trade execution"""
        level = AlertLevel.SUCCESS if order.status == OrderStatus.FILLED else AlertLevel.WARNING
        
        alert = Alert(
            alert_type=AlertType.TRADE,
            level=level,
            title=f"Trade Executed: {order.ticker}",
            message=f"{order.side.value.upper()} x{order.filled_count} @ {order.price}¢",
            data={
                "order_id": order.order_id,
                "ticker": order.ticker,
                "side": order.side.value,
                "status": order.status.value,
                "filled": order.filled_count,
                "remaining": order.remaining_count,
                "price": order.price,
                "avg_fill": order.avg_fill_price
            }
        )
        await self.send_alert(alert)
    
    async def send_fill_alert(self, order: OrderResponse):
        """Send alert for order fill"""
        alert = Alert(
            alert_type=AlertType.FILL,
            level=AlertLevel.SUCCESS,
            title=f"Order Filled: {order.ticker}",
            message=f"Filled {order.filled_count} contracts at avg {order.avg_fill_price}",
            data={
                "order_id": order.order_id,
                "ticker": order.ticker,
                "filled": order.filled_count,
                "avg_price": order.avg_fill_price
            }
        )
        await self.send_alert(alert)
    
    async def send_circuit_breaker_alert(self, reason: str, daily_pnl: float, threshold: float):
        """Send alert for circuit breaker trigger"""
        alert = Alert(
            alert_type=AlertType.CIRCUIT_BREAKER,
            level=AlertLevel.CRITICAL,
            title="🛑 CIRCUIT BREAKER TRIGGERED",
            message=reason,
            data={
                "daily_pnl": f"{daily_pnl:.2%}",
                "threshold": f"{threshold:.2%}"
            }
        )
        await self.send_alert(alert)
    
    async def send_daily_summary(
        self,
        total_pnl: float,
        trades_count: int,
        win_rate: float,
        best_trade: str,
        worst_trade: str
    ):
        """Send daily trading summary"""
        level = AlertLevel.SUCCESS if total_pnl > 0 else AlertLevel.WARNING
        
        alert = Alert(
            alert_type=AlertType.DAILY_SUMMARY,
            level=level,
            title="📊 Daily Trading Summary",
            message=f"{'Profitable' if total_pnl > 0 else 'Losing'} day with {trades_count} trades",
            data={
                "total_pnl": f"${total_pnl:.2f}",
                "trades": trades_count,
                "win_rate": f"{win_rate:.1%}",
                "best_trade": best_trade,
                "worst_trade": worst_trade
            }
        )
        await self.send_alert(alert)
    
    async def send_error_alert(self, error_type: str, error_message: str, context: Dict = None):
        """Send alert for errors"""
        alert = Alert(
            alert_type=AlertType.ERROR,
            level=AlertLevel.ERROR,
            title=f"Error: {error_type}",
            message=error_message,
            data=context or {}
        )
        await self.send_alert(alert)
    
    async def send_system_alert(self, title: str, message: str, level: AlertLevel = AlertLevel.INFO):
        """Send system status alert"""
        alert = Alert(
            alert_type=AlertType.SYSTEM,
            level=level,
            title=title,
            message=message
        )
        await self.send_alert(alert)


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_alert_manager: Optional[AlertManager] = None

async def get_alert_manager() -> AlertManager:
    """Get or create global alert manager"""
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = AlertManager()
        await _alert_manager.connect()
    return _alert_manager


# =============================================================================
# SIMPLE NOTIFICATION FUNCTIONS
# =============================================================================

async def notify_signal(signal: TradingSignal):
    """Quick helper to notify about a signal"""
    manager = await get_alert_manager()
    await manager.send_signal_alert(signal)


async def notify_trade(signal: TradingSignal, order: OrderResponse):
    """Quick helper to notify about a trade"""
    manager = await get_alert_manager()
    await manager.send_trade_alert(signal, order)


async def notify_error(error_type: str, message: str):
    """Quick helper to notify about an error"""
    manager = await get_alert_manager()
    await manager.send_error_alert(error_type, message)
