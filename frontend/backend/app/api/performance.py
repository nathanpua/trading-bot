"""Performance metrics API — portfolio analytics."""
from __future__ import annotations

import logging
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Query

from ..services import journal_service, alpaca_service
from ..config import REPORTS_DIR, BOT_ROOT

router = APIRouter(prefix="/api/performance", tags=["performance"])
logger = logging.getLogger("dashboard")


@router.get("")
def get_performance():
    """Full performance dashboard: returns + trades + metrics + equity curve."""
    try:
        stats = journal_service.get_stats()
        trades = journal_service.get_trades(limit=500)
        equity_history = journal_service.get_equity_history()

        # Calculate returns from equity curve
        returns_data = _calculate_returns(equity_history)

        # Closed trades for win/loss analysis
        closed = [t for t in trades if t.get("status") == "closed" and t.get("pnl_dollars") is not None]

        # Trade-level metrics
        trade_metrics = _trade_metrics(closed)

        # Portfolio-level metrics from equity curve
        portfolio_metrics = _portfolio_metrics(returns_data)

        # Monthly breakdown
        monthly = _monthly_breakdown(closed)

        # Cumulative P&L over time
        cumulative = _cumulative_pnl(closed)

        # Equity curve formatted for chart
        equity_curve = [
            {"ts": point["ts"][:10], "equity": point["equity"]}
            for point in equity_history
        ]

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trade_metrics": trade_metrics,
            "portfolio_metrics": portfolio_metrics,
            "overall": stats.get("overall"),
            "by_strategy": stats.get("by_strategy", []),
            "by_symbol": stats.get("by_symbol", []),
            "monthly": monthly,
            "cumulative_pnl": cumulative,
            "equity_curve": equity_curve,
            "closed_trade_count": len(closed),
            "total_trade_count": len(trades),
        }
    except Exception as e:
        logger.warning("Performance calculation failed: %s", e)
        return {"error": str(e)[:200]}


def _calculate_returns(equity_history):
    """Compute period returns from equity curve points."""
    if len(equity_history) < 2:
        return []

    sorted_hist = sorted(equity_history, key=lambda x: x["ts"])
    returns = []
    for i in range(1, len(sorted_hist)):
        prev_eq = sorted_hist[i - 1]["equity"]
        curr_eq = sorted_hist[i]["equity"]
        if prev_eq > 0:
            ret = (curr_eq - prev_eq) / prev_eq
            returns.append({
                "ts": sorted_hist[i]["ts"],
                "return": ret,
                "equity": curr_eq,
            })
    return returns


def _trade_metrics(closed_trades):
    """Win rate, avg win/loss, profit factor, expectancy, streaks."""
    if not closed_trades:
        return {
            "total": 0, "wins": 0, "losses": 0, "win_rate": 0,
            "avg_win": 0, "avg_loss": 0, "profit_factor": 0,
            "expectancy": 0, "avg_hold_days": 0,
            "max_win_streak": 0, "max_loss_streak": 0,
            "total_pnl": 0, "largest_win": 0, "largest_loss": 0,
        }

    pnls = [t["pnl_dollars"] for t in closed_trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    total = len(closed_trades)
    n_wins = len(wins)
    n_losses = len(losses)
    win_rate = (n_wins / total * 100) if total else 0
    avg_win = (sum(wins) / n_wins) if wins else 0
    avg_loss = (sum(losses) / n_losses) if losses else 0
    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf") if gross_profit > 0 else 0
    expectancy = (win_rate / 100 * avg_win) - ((100 - win_rate) / 100 * abs(avg_loss)) if total else 0

    # Streaks
    max_win_streak = cur_win = 0
    max_loss_streak = cur_loss = 0
    for p in pnls:
        if p > 0:
            cur_win += 1; cur_loss = 0
            max_win_streak = max(max_win_streak, cur_win)
        else:
            cur_loss += 1; cur_win = 0
            max_loss_streak = max(max_loss_streak, cur_loss)

    return {
        "total": total,
        "wins": n_wins,
        "losses": n_losses,
        "win_rate": round(win_rate, 1),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else None,
        "expectancy": round(expectancy, 2),
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
        "total_pnl": round(sum(pnls), 2),
        "largest_win": round(max(wins), 2) if wins else 0,
        "largest_loss": round(min(losses), 2) if losses else 0,
    }


def _portfolio_metrics(returns_data):
    """Sharpe, Sortino, max drawdown, volatility from equity curve returns."""
    if len(returns_data) < 2:
        return {"sharpe": None, "sortino": None, "max_drawdown": None,
                "volatility": None, "total_return": None, "avg_return": None}

    rets = [r["return"] for r in returns_data]
    n = len(rets)

    avg_ret = sum(rets) / n
    var = sum((r - avg_ret) ** 2 for r in rets) / max(n - 1, 1)
    std = math.sqrt(var) if var > 0 else 0

    # Annualization factor (daily bars → 252 trading days)
    ann_factor = math.sqrt(252)
    rf = 0.04 / 252  # risk-free rate per day (4% annual)

    sharpe = ((avg_ret - rf) / std * ann_factor) if std > 0 else None

    # Sortino: only downside deviation
    downside = [r for r in rets if r < 0]
    if downside:
        ds_var = sum(r ** 2 for r in downside) / len(downside)
        ds_std = math.sqrt(ds_var)
        sortino = ((avg_ret - rf) / ds_std * ann_factor) if ds_std > 0 else None
    else:
        sortino = None

    # Max drawdown
    peak = returns_data[0]["equity"]
    max_dd = 0
    for r in returns_data:
        eq = r["equity"]
        if eq > peak:
            peak = eq
        dd = (eq - peak) / peak
        if dd < max_dd:
            max_dd = dd

    # Total return
    first_eq = returns_data[0]["equity"]
    last_eq = returns_data[-1]["equity"]
    total_return = ((last_eq - first_eq) / first_eq * 100) if first_eq > 0 else 0

    return {
        "sharpe": round(sharpe, 2) if sharpe is not None else None,
        "sortino": round(sortino, 2) if sortino is not None else None,
        "max_drawdown": round(max_dd * 100, 2),
        "volatility": round(std * ann_factor * 100, 2),
        "total_return": round(total_return, 2),
        "avg_daily_return": round(avg_ret * 100, 3),
    }


def _monthly_breakdown(closed_trades):
    """P&L grouped by month."""
    monthly = defaultdict(lambda: {"pnl": 0, "trades": 0, "wins": 0})
    for t in closed_trades:
        ts = t.get("ts", "")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            key = dt.strftime("%Y-%m")
            monthly[key]["pnl"] += t["pnl_dollars"]
            monthly[key]["trades"] += 1
            if t["pnl_dollars"] > 0:
                monthly[key]["wins"] += 1
        except Exception:
            continue

    result = []
    for month in sorted(monthly.keys()):
        d = monthly[month]
        result.append({
            "month": month,
            "pnl": round(d["pnl"], 2),
            "trades": d["trades"],
            "wins": d["wins"],
            "win_rate": round(d["wins"] / d["trades"] * 100, 1) if d["trades"] else 0,
        })
    return result


def _cumulative_pnl(closed_trades):
    """Running cumulative P&L over time for charting."""
    sorted_trades = sorted(closed_trades, key=lambda x: x.get("ts", ""))
    cum = 0
    points = []
    for t in sorted_trades:
        pnl = t.get("pnl_dollars", 0)
        cum += pnl
        points.append({
            "ts": t.get("ts", "")[:10],
            "cumulative_pnl": round(cum, 2),
            "symbol": t.get("symbol", ""),
            "pnl": round(pnl, 2),
        })
    return points
