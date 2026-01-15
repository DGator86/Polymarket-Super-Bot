#!/usr/bin/env python3
"""
Kalshi Latency Bot - Live Monitoring Dashboard

Real-time performance monitoring and alerting.
"""

import asyncio
import json
import time
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Deque
from collections import deque
import statistics

@dataclass
class PerformanceMetrics:
    """Real-time performance tracking"""

    # Trade metrics
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0

    # P&L
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    high_water_mark: float = 0.0
    max_drawdown: float = 0.0

    # Latency
    avg_signal_latency_ms: float = 0.0
    avg_execution_latency_ms: float = 0.0

    # Edge
    avg_edge_captured: float = 0.0
    edge_decay_rate: float = 0.0  # How fast edge erodes

    # Win rate by time window
    win_rate_5min: float = 0.0
    win_rate_1hr: float = 0.0
    win_rate_24hr: float = 0.0

@dataclass
class Alert:
    """Monitoring alert"""
    timestamp: datetime
    level: str  # INFO, WARNING, CRITICAL
    message: str
    metric: str
    value: float
    threshold: float

class LiveMonitor:
    """
    Real-time monitoring for the trading bot.

    Tracks:
    - P&L and drawdown
    - Win rates over rolling windows
    - Latency metrics
    - Edge capture rates
    - System health
    """

    def __init__(
        self,
        alert_callback=None,
        max_drawdown_threshold: float = 0.10,  # 10% max DD alert
        min_win_rate_threshold: float = 0.45,  # Alert if win rate drops
        max_latency_threshold_ms: float = 200,  # Alert if latency spikes
    ):
        self.alert_callback = alert_callback
        self.max_dd_threshold = max_drawdown_threshold
        self.min_wr_threshold = min_win_rate_threshold
        self.max_latency_ms = max_latency_threshold_ms

        # Rolling windows
        self.trades_5min: Deque = deque(maxlen=100)
        self.trades_1hr: Deque = deque(maxlen=500)
        self.trades_24hr: Deque = deque(maxlen=2000)

        self.latencies: Deque = deque(maxlen=100)
        self.edges: Deque = deque(maxlen=100)

        # Current state
        self.metrics = PerformanceMetrics()
        self.alerts: List[Alert] = []
        self.start_time = datetime.now(timezone.utc)

        # Price feed health
        self.last_price_update: Dict[str, datetime] = {}
        self.price_update_count = 0

    def record_trade(
        self,
        pnl: float,
        edge_at_entry: float,
        signal_latency_ms: float,
        execution_latency_ms: float,
    ):
        """Record a completed trade"""
        now = datetime.now(timezone.utc)

        trade_record = {
            "timestamp": now,
            "pnl": pnl,
            "edge": edge_at_entry,
            "win": pnl > 0,
        }

        # Add to rolling windows
        self.trades_5min.append(trade_record)
        self.trades_1hr.append(trade_record)
        self.trades_24hr.append(trade_record)

        # Update metrics
        self.metrics.total_trades += 1
        if pnl > 0:
            self.metrics.winning_trades += 1
        else:
            self.metrics.losing_trades += 1

        self.metrics.realized_pnl += pnl

        # Track high water mark and drawdown
        if self.metrics.realized_pnl > self.metrics.high_water_mark:
            self.metrics.high_water_mark = self.metrics.realized_pnl

        current_dd = (self.metrics.high_water_mark - self.metrics.realized_pnl) / \
                     max(self.metrics.high_water_mark, 1)
        self.metrics.max_drawdown = max(self.metrics.max_drawdown, current_dd)

        # Track latency
        self.latencies.append(signal_latency_ms + execution_latency_ms)
        self.metrics.avg_signal_latency_ms = signal_latency_ms
        self.metrics.avg_execution_latency_ms = execution_latency_ms

        # Track edge
        self.edges.append(edge_at_entry)
        if len(self.edges) > 1:
            self.metrics.avg_edge_captured = statistics.mean(self.edges)

        # Update rolling win rates
        self._update_win_rates(now)

        # Check alerts
        self._check_alerts(now)

    def record_price_update(self, source: str):
        """Record price feed activity"""
        self.last_price_update[source] = datetime.now(timezone.utc)
        self.price_update_count += 1

    def _update_win_rates(self, now: datetime):
        """Update rolling window win rates"""

        # 5-minute window
        cutoff_5min = now - timedelta(minutes=5)
        recent_5min = [t for t in self.trades_5min if t["timestamp"] > cutoff_5min]
        if recent_5min:
            self.metrics.win_rate_5min = sum(1 for t in recent_5min if t["win"]) / len(recent_5min)

        # 1-hour window
        cutoff_1hr = now - timedelta(hours=1)
        recent_1hr = [t for t in self.trades_1hr if t["timestamp"] > cutoff_1hr]
        if recent_1hr:
            self.metrics.win_rate_1hr = sum(1 for t in recent_1hr if t["win"]) / len(recent_1hr)

        # 24-hour window
        cutoff_24hr = now - timedelta(hours=24)
        recent_24hr = [t for t in self.trades_24hr if t["timestamp"] > cutoff_24hr]
        if recent_24hr:
            self.metrics.win_rate_24hr = sum(1 for t in recent_24hr if t["win"]) / len(recent_24hr)

    def _check_alerts(self, now: datetime):
        """Check for alert conditions"""

        # Drawdown alert
        current_dd = (self.metrics.high_water_mark - self.metrics.realized_pnl) / \
                     max(self.metrics.high_water_mark, 1)
        if current_dd > self.max_dd_threshold:
            self._fire_alert(
                level="CRITICAL",
                message=f"Drawdown exceeded threshold",
                metric="drawdown",
                value=current_dd,
                threshold=self.max_dd_threshold,
            )

        # Win rate alert
        if self.metrics.total_trades > 20 and self.metrics.win_rate_1hr < self.min_wr_threshold:
            self._fire_alert(
                level="WARNING",
                message=f"Win rate below threshold",
                metric="win_rate_1hr",
                value=self.metrics.win_rate_1hr,
                threshold=self.min_wr_threshold,
            )

        # Latency alert
        if self.latencies:
            avg_latency = statistics.mean(self.latencies)
            if avg_latency > self.max_latency_ms:
                self._fire_alert(
                    level="WARNING",
                    message=f"Latency spike detected",
                    metric="avg_latency_ms",
                    value=avg_latency,
                    threshold=self.max_latency_ms,
                )

        # Price feed health
        for source, last_update in self.last_price_update.items():
            if (now - last_update).total_seconds() > 5:
                self._fire_alert(
                    level="WARNING",
                    message=f"Price feed stale: {source}",
                    metric="feed_staleness",
                    value=(now - last_update).total_seconds(),
                    threshold=5.0,
                )

    def _fire_alert(
        self,
        level: str,
        message: str,
        metric: str,
        value: float,
        threshold: float,
    ):
        """Fire an alert"""
        alert = Alert(
            timestamp=datetime.now(timezone.utc),
            level=level,
            message=message,
            metric=metric,
            value=value,
            threshold=threshold,
        )
        self.alerts.append(alert)

        # Keep only last 100 alerts
        if len(self.alerts) > 100:
            self.alerts = self.alerts[-100:]

        if self.alert_callback:
            self.alert_callback(alert)

    def get_dashboard_data(self) -> Dict:
        """Get data for dashboard display"""
        now = datetime.now(timezone.utc)
        uptime = (now - self.start_time).total_seconds()

        return {
            "timestamp": now.isoformat(),
            "uptime_seconds": uptime,
            "metrics": {
                "total_trades": self.metrics.total_trades,
                "winning_trades": self.metrics.winning_trades,
                "losing_trades": self.metrics.losing_trades,
                "win_rate_overall": self.metrics.winning_trades / max(self.metrics.total_trades, 1),
                "win_rate_5min": self.metrics.win_rate_5min,
                "win_rate_1hr": self.metrics.win_rate_1hr,
                "win_rate_24hr": self.metrics.win_rate_24hr,
                "realized_pnl": self.metrics.realized_pnl,
                "unrealized_pnl": self.metrics.unrealized_pnl,
                "total_pnl": self.metrics.realized_pnl + self.metrics.unrealized_pnl,
                "high_water_mark": self.metrics.high_water_mark,
                "max_drawdown": self.metrics.max_drawdown,
                "current_drawdown": (self.metrics.high_water_mark - self.metrics.realized_pnl) / \
                                   max(self.metrics.high_water_mark, 1),
                "avg_edge": self.metrics.avg_edge_captured,
                "avg_latency_ms": statistics.mean(self.latencies) if self.latencies else 0,
            },
            "feeds": {
                source: (now - last).total_seconds()
                for source, last in self.last_price_update.items()
            },
            "recent_alerts": [
                {
                    "timestamp": a.timestamp.isoformat(),
                    "level": a.level,
                    "message": a.message,
                }
                for a in self.alerts[-10:]
            ],
        }

    def print_dashboard(self):
        """Print ASCII dashboard to console"""
        data = self.get_dashboard_data()
        m = data["metrics"]

        print("\033[2J\033[H")  # Clear screen
        print("╔══════════════════════════════════════════════════════════════════╗")
        print("║           KALSHI LATENCY BOT - LIVE DASHBOARD                    ║")
        print("╠══════════════════════════════════════════════════════════════════╣")
        print(f"║  Uptime: {data['uptime_seconds']/3600:.1f}h | "
              f"Trades: {m['total_trades']} | "
              f"Win Rate: {m['win_rate_overall']:.1%}                    ║")
        print("╠══════════════════════════════════════════════════════════════════╣")
        print(f"║  P&L                                                             ║")
        print(f"║    Realized:    ${m['realized_pnl']:>10.2f}                               ║")
        print(f"║    Unrealized:  ${m['unrealized_pnl']:>10.2f}                               ║")
        print(f"║    Total:       ${m['total_pnl']:>10.2f}                               ║")
        print("╠══════════════════════════════════════════════════════════════════╣")
        print(f"║  Risk                                                            ║")
        print(f"║    Max DD:      {m['max_drawdown']:>6.1%}                                       ║")
        print(f"║    Current DD:  {m['current_drawdown']:>6.1%}                                       ║")
        print("╠══════════════════════════════════════════════════════════════════╣")
        print(f"║  Win Rates                                                       ║")
        print(f"║    5 min:  {m['win_rate_5min']:>5.1%}  |  1 hr: {m['win_rate_1hr']:>5.1%}  |  24 hr: {m['win_rate_24hr']:>5.1%}      ║")
        print("╠══════════════════════════════════════════════════════════════════╣")
        print(f"║  Performance                                                     ║")
        print(f"║    Avg Edge:    {m['avg_edge']:>6.2%}                                       ║")
        print(f"║    Avg Latency: {m['avg_latency_ms']:>6.1f} ms                                    ║")
        print("╠══════════════════════════════════════════════════════════════════╣")
        print(f"║  Price Feeds                                                     ║")
        for source, staleness in data["feeds"].items():
            status = "✓" if staleness < 2 else "⚠" if staleness < 5 else "✗"
            print(f"║    {source:12} {status} ({staleness:.1f}s ago)                              ║")
        print("╠══════════════════════════════════════════════════════════════════╣")
        print(f"║  Recent Alerts                                                   ║")
        for alert in data["recent_alerts"][-3:]:
            level_icon = "🔴" if alert["level"] == "CRITICAL" else "🟡" if alert["level"] == "WARNING" else "🟢"
            print(f"║    {level_icon} {alert['message'][:50]:50}   ║")
        print("╚══════════════════════════════════════════════════════════════════╝")

async def demo_dashboard():
    """Demo the monitoring dashboard"""
    import random

    monitor = LiveMonitor(
        alert_callback=lambda a: print(f"ALERT: {a.level} - {a.message}")
    )

    print("Starting dashboard demo...")

    for i in range(100):
        # Simulate trades
        if random.random() < 0.3:  # 30% chance of trade each tick
            pnl = random.gauss(2, 10)  # Average $2 profit, $10 std dev
            edge = random.uniform(0.03, 0.08)
            signal_latency = random.uniform(5, 50)
            exec_latency = random.uniform(10, 100)

            monitor.record_trade(pnl, edge, signal_latency, exec_latency)

        # Simulate price updates
        for source in ["binance", "coinbase", "kraken"]:
            if random.random() < 0.8:  # 80% chance of update
                monitor.record_price_update(source)

        # Update dashboard
        monitor.print_dashboard()

        await asyncio.sleep(0.5)

if __name__ == "__main__":
    asyncio.run(demo_dashboard())
