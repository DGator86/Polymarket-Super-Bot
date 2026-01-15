"""
Analytics and Reporting Module

Generates detailed reports from paper trading results.
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from pathlib import Path
from dataclasses import dataclass, asdict
import sqlite3

logger = logging.getLogger(__name__)


@dataclass
class PerformanceReport:
    """Comprehensive performance analysis"""
    period_start: str
    period_end: str
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    total_pnl: float
    max_drawdown: float
    sharpe_ratio: float
    profit_factor: float
    avg_win: float
    avg_loss: float
    by_category: Dict[str, Dict]
    by_edge_bucket: Dict[str, Dict]
    edge_calibration: Dict[str, float]


class AnalyticsEngine:
    """Analyzes paper trading results"""
    
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self._db: Optional[sqlite3.Connection] = None
    
    def connect(self):
        if self.db_path.exists():
            self._db = sqlite3.connect(str(self.db_path))
            self._db.row_factory = sqlite3.Row
    
    def close(self):
        if self._db:
            self._db.close()
    
    def generate_report(self, days: int = 30) -> PerformanceReport:
        """Generate performance report for last N days"""
        if not self._db:
            self.connect()
        
        if not self._db:
            return self._empty_report()
        
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)
        
        cursor = self._db.execute("""
            SELECT * FROM trades 
            WHERE exit_time >= ? 
            ORDER BY exit_time
        """, (start_date.isoformat(),))
        
        trades = [dict(row) for row in cursor.fetchall()]
        
        if not trades:
            return self._empty_report()
        
        wins = [t for t in trades if t["outcome"] == "win"]
        losses = [t for t in trades if t["outcome"] == "loss"]
        
        total_pnl = sum(float(t["pnl"]) for t in trades)
        
        # Profit factor
        gross_profit = sum(float(t["pnl"]) for t in wins) if wins else 0
        gross_loss = abs(sum(float(t["pnl"]) for t in losses)) if losses else 1
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
        
        # By category
        by_category = {}
        for trade in trades:
            cat = trade.get("category", "unknown")
            if cat not in by_category:
                by_category[cat] = {"trades": 0, "wins": 0, "pnl": 0}
            by_category[cat]["trades"] += 1
            by_category[cat]["pnl"] += float(trade["pnl"])
            if trade["outcome"] == "win":
                by_category[cat]["wins"] += 1
        
        for cat in by_category:
            by_category[cat]["win_rate"] = by_category[cat]["wins"] / by_category[cat]["trades"]
        
        # By edge bucket
        by_edge = {"0-5%": [], "5-10%": [], "10-20%": [], "20%+": []}
        for trade in trades:
            edge = float(trade.get("signal_edge", 0)) * 100
            if edge < 5:
                by_edge["0-5%"].append(trade)
            elif edge < 10:
                by_edge["5-10%"].append(trade)
            elif edge < 20:
                by_edge["10-20%"].append(trade)
            else:
                by_edge["20%+"].append(trade)
        
        edge_stats = {}
        for bucket, bucket_trades in by_edge.items():
            if bucket_trades:
                wins_count = sum(1 for t in bucket_trades if t["outcome"] == "win")
                edge_stats[bucket] = {
                    "trades": len(bucket_trades),
                    "win_rate": wins_count / len(bucket_trades),
                    "avg_pnl": sum(float(t["pnl"]) for t in bucket_trades) / len(bucket_trades)
                }
        
        # Edge calibration
        calibration = {}
        for bucket, bucket_trades in by_edge.items():
            if len(bucket_trades) >= 5:
                avg_edge = sum(float(t["signal_edge"]) for t in bucket_trades) / len(bucket_trades)
                actual_win_rate = sum(1 for t in bucket_trades if t["outcome"] == "win") / len(bucket_trades)
                expected = 0.5 + avg_edge
                calibration[bucket] = actual_win_rate / expected if expected > 0 else 1.0
        
        return PerformanceReport(
            period_start=start_date.isoformat(),
            period_end=end_date.isoformat(),
            total_trades=len(trades),
            wins=len(wins),
            losses=len(losses),
            win_rate=len(wins) / len(trades),
            total_pnl=total_pnl,
            max_drawdown=self._calc_max_drawdown(trades),
            sharpe_ratio=self._calc_sharpe(trades),
            profit_factor=profit_factor,
            avg_win=sum(float(t["pnl"]) for t in wins) / len(wins) if wins else 0,
            avg_loss=sum(float(t["pnl"]) for t in losses) / len(losses) if losses else 0,
            by_category=by_category,
            by_edge_bucket=edge_stats,
            edge_calibration=calibration,
        )
    
    def _empty_report(self) -> PerformanceReport:
        now = datetime.now(timezone.utc).isoformat()
        return PerformanceReport(
            period_start=now, period_end=now,
            total_trades=0, wins=0, losses=0, win_rate=0,
            total_pnl=0, max_drawdown=0, sharpe_ratio=0,
            profit_factor=0, avg_win=0, avg_loss=0,
            by_category={}, by_edge_bucket={}, edge_calibration={}
        )
    
    def _calc_max_drawdown(self, trades: List[Dict]) -> float:
        equity = 1000
        peak = equity
        max_dd = 0
        for trade in trades:
            equity += float(trade["pnl"])
            peak = max(peak, equity)
            dd = (peak - equity) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)
        return max_dd
    
    def _calc_sharpe(self, trades: List[Dict]) -> float:
        if len(trades) < 2:
            return 0
        returns = [float(t["pnl_pct"]) for t in trades]
        mean_ret = sum(returns) / len(returns)
        variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
        std_ret = variance ** 0.5
        return mean_ret / std_ret if std_ret > 0 else 0
    
    def export_json(self, output_path: str):
        """Export report to JSON"""
        report = self.generate_report()
        with open(output_path, "w") as f:
            json.dump(asdict(report), f, indent=2)
    
    def export_trades_csv(self, output_path: str):
        """Export trades to CSV"""
        if not self._db:
            self.connect()
        if not self._db:
            return
        
        cursor = self._db.execute("SELECT * FROM trades ORDER BY exit_time")
        trades = cursor.fetchall()
        
        if not trades:
            return
        
        columns = [d[0] for d in cursor.description]
        
        with open(output_path, "w") as f:
            f.write(",".join(columns) + "\n")
            for trade in trades:
                f.write(",".join(str(v) if v is not None else "" for v in trade) + "\n")
        
        logger.info(f"Exported {len(trades)} trades to {output_path}")
