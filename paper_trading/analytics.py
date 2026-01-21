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
    
    def summarize_trade_execution(self, days: int = 30) -> Dict[str, Any]:
        """Aggregate execution/EV audit metrics for the last N days."""
        if not self._db:
            self.connect()
        if not self._db:
            return {}
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)
        cur = self._db.execute(
            """
            SELECT side, quantity, entry_price, model_probability, 
                   yes_bid_entry, yes_ask_entry, no_bid_entry, no_ask_entry,
                   spread_entry, slippage_applied, fee_paid
            FROM trades
            WHERE exit_time >= ?
            ORDER BY exit_time
            """,
            (start_date.isoformat(),)
        )
        rows = [dict(r) for r in cur.fetchall()]
        if not rows:
            return {}
        import statistics as stats
        n = len(rows)
        # Helper accessors with None handling
        def f(x):
            try:
                return float(x)
            except Exception:
                return None
        p_cals = []
        q_entries = []
        p_minus_q_net = []
        pnl_like = []
        yes_asks = []
        yes_bids = []
        no_asks = []
        no_bids = []
        spreads = []
        slip_applied = []
        spread_gt_slip = 0
        for r in rows:
            side = r["side"].lower()
            qty = int(r.get("quantity") or 0) or 1
            entry = f(r.get("entry_price")) or 0.0
            model_p_yes = f(r.get("model_probability")) or 0.0
            if side == "yes":
                p_cal = model_p_yes
                ask = f(r.get("yes_ask_entry"))
                bid = f(r.get("yes_bid_entry"))
                if ask is not None: yes_asks.append(ask)
                if bid is not None: yes_bids.append(bid)
            else:
                p_cal = 1.0 - model_p_yes
                ask = f(r.get("no_ask_entry"))
                bid = f(r.get("no_bid_entry"))
                if ask is not None: no_asks.append(ask)
                if bid is not None: no_bids.append(bid)
            p_cals.append(p_cal)
            q_entries.append(entry)
            fee = f(r.get("fee_paid")) or 0.0
            fee_per_contract = fee / qty if qty > 0 else 0.0
            p_minus_q_net.append(p_cal - entry - fee_per_contract)
            sp = f(r.get("spread_entry"))
            da = f(r.get("slippage_applied"))
            if sp is not None: spreads.append(sp)
            if da is not None: slip_applied.append(da)
            if sp is not None and da is not None and sp > da:
                spread_gt_slip += 1
        def safe_avg(arr):
            return (sum(arr) / len(arr)) if arr else 0.0
        def safe_med(arr):
            return stats.median(arr) if arr else 0.0
        return {
            "n_trades": n,
            "avg_p_cal": safe_avg(p_cals),
            "avg_yes_ask": safe_avg(yes_asks),
            "avg_yes_bid": safe_avg(yes_bids),
            "avg_no_ask": safe_avg(no_asks),
            "avg_no_bid": safe_avg(no_bids),
            "avg_q_entry": safe_avg(q_entries),
            "avg_p_minus_q_net": safe_avg(p_minus_q_net),
            "p_minus_q_net_min": min(p_minus_q_net) if p_minus_q_net else 0.0,
            "p_minus_q_net_med": safe_med(p_minus_q_net),
            "p_minus_q_net_max": max(p_minus_q_net) if p_minus_q_net else 0.0,
            "spread_gt_slip_frac": (spread_gt_slip / len(rows)) if rows else 0.0,
        }
    
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
