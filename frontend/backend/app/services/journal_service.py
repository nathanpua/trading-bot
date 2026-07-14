"""Journal service — queries the bot's trade_journal.db."""
from __future__ import annotations

import json
import sqlite3
import logging
from pathlib import Path
from ..config import JOURNAL_DB, CYCLE_DIR, REPORTS_DIR

logger = logging.getLogger("dashboard")


def _get_db():
    if not JOURNAL_DB.exists():
        return None
    # In Docker, the reports dir may be read-only. Copy to /tmp for read access.
    db_path = JOURNAL_DB
    import tempfile, shutil
    tmp_db = Path(tempfile.gettempdir()) / "trade_journal_readonly.db"
    try:
        shutil.copy2(str(db_path), str(tmp_db))
        db_path = tmp_db
    except Exception:
        pass
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_journal():
    """Ensure tables exist (matches bot schema)."""
    # In Docker, create schema in /tmp to avoid write failures on read-only mounts
    import tempfile, shutil
    tmp_db = Path(tempfile.gettempdir()) / "trade_journal_readonly.db"
    if JOURNAL_DB.exists():
        try:
            shutil.copy2(str(JOURNAL_DB), str(tmp_db))
        except Exception:
            pass
    conn = sqlite3.connect(str(tmp_db))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL,
            qty REAL, entry_price REAL, exit_price REAL, stop_price REAL,
            target_price REAL, pnl_dollars REAL, pnl_pct REAL,
            position_pct REAL, risk_pct REAL, thesis TEXT, outcome TEXT,
            strategy TEXT, regime TEXT, tags TEXT, status TEXT DEFAULT 'open'
        );
        CREATE TABLE IF NOT EXISTS lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL, category TEXT NOT NULL, lesson TEXT NOT NULL,
            evidence TEXT, confidence TEXT DEFAULT 'medium'
        );
        CREATE TABLE IF NOT EXISTS cycles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL, session TEXT, regime TEXT, equity REAL,
            cash_pct REAL, deployed_pct REAL, position_count INTEGER,
            actions TEXT, report TEXT
        );
    """)
    conn.commit()
    conn.close()


def get_trades(limit=50, symbol=None, strategy=None, status=None, outcome=None):
    conn = _get_db()
    if not conn:
        return []
    query = "SELECT * FROM trades WHERE 1=1"
    params = []
    if symbol:
        query += " AND UPPER(symbol) = UPPER(?)"
        params.append(symbol)
    if strategy:
        query += " AND strategy = ?"
        params.append(strategy)
    if status:
        query += " AND status = ?"
        params.append(status)
    if outcome:
        query += " AND outcome = ?"
        params.append(outcome)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stats():
    conn = _get_db()
    if not conn:
        return {"overall": None, "by_strategy": [], "by_symbol": [], "recent_lessons": []}
    stats = {}
    row = conn.execute("""
        SELECT COUNT(*) as total,
            SUM(CASE WHEN pnl_dollars > 0 THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN pnl_dollars < 0 THEN 1 ELSE 0 END) as losses,
            SUM(pnl_dollars) as total_pnl, AVG(pnl_pct) as avg_pnl_pct
        FROM trades WHERE status='closed' AND pnl_dollars IS NOT NULL
    """).fetchone()
    if row and row["total"]:
        stats["overall"] = {
            "trades": row["total"], "wins": row["wins"], "losses": row["losses"],
            "win_rate": round(row["wins"] / row["total"] * 100, 1),
            "total_pnl": round(row["total_pnl"] or 0, 2),
            "avg_pnl_pct": round(row["avg_pnl_pct"] or 0, 2),
        }
    else:
        stats["overall"] = None
    rows = conn.execute("""
        SELECT strategy, COUNT(*) as total,
            SUM(CASE WHEN pnl_dollars > 0 THEN 1 ELSE 0 END) as wins,
            SUM(pnl_dollars) as total_pnl
        FROM trades WHERE status='closed' AND pnl_dollars IS NOT NULL AND strategy != ''
        GROUP BY strategy
    """).fetchall()
    stats["by_strategy"] = [{
        "strategy": r["strategy"], "trades": r["total"],
        "wins": r["wins"], "win_rate": round(r["wins"] / r["total"] * 100, 1),
        "total_pnl": round(r["total_pnl"] or 0, 2),
    } for r in rows]
    rows = conn.execute("""
        SELECT symbol, COUNT(*) as total,
            SUM(CASE WHEN pnl_dollars > 0 THEN 1 ELSE 0 END) as wins,
            SUM(pnl_dollars) as total_pnl
        FROM trades WHERE status='closed' AND pnl_dollars IS NOT NULL
        GROUP BY symbol ORDER BY total_pnl DESC
    """).fetchall()
    stats["by_symbol"] = [{
        "symbol": r["symbol"], "trades": r["total"],
        "wins": r["wins"], "win_rate": round(r["wins"] / r["total"] * 100, 1),
        "total_pnl": round(r["total_pnl"] or 0, 2),
    } for r in rows]
    rows = conn.execute(
        "SELECT category, lesson, evidence, confidence FROM lessons ORDER BY id DESC LIMIT 20"
    ).fetchall()
    stats["recent_lessons"] = [dict(r) for r in rows]
    conn.close()
    return stats


def get_cycles(limit=20):
    """Read cycle reports from JSON files."""
    if not CYCLE_DIR.exists():
        return []
    files = sorted(CYCLE_DIR.glob("cycle_*.json"), reverse=True)[:limit]
    cycles = []
    for f in files:
        try:
            data = json.loads(f.read_text())
            cycles.append({
                "ts": data.get("ts", ""),
                "phase": data.get("phase", ""),
                "execute": data.get("execute", False),
                "regime": data.get("regime", {}),
                "halt": data.get("halt", False),
                "halt_reason": data.get("halt_reason", ""),
                "exits": data.get("exits", []),
                "entries": data.get("entries", []),
                "equity": data.get("equity", 0),
                "report": data.get("report", ""),
            })
        except Exception:
            continue
    return cycles


def get_equity_history():
    """Build equity history from cycle reports (both deterministic + AI)."""
    history = []

    # Deterministic cycles
    if CYCLE_DIR.exists():
        for f in sorted(CYCLE_DIR.glob("cycle_*.json")):
            try:
                data = json.loads(f.read_text())
                if data.get("equity"):
                    history.append({
                        "ts": data.get("ts", ""),
                        "equity": data["equity"],
                        "source": "cycle",
                    })
            except Exception:
                continue

    # AI trading floor cycles
    tf_dir = REPORTS_DIR / "trading_floor"
    if tf_dir.exists():
        for f in sorted(tf_dir.glob("cycle_*.json")):
            try:
                data = json.loads(f.read_text())
                eq = data.get("context_summary", {}).get("equity")
                if eq:
                    history.append({
                        "ts": data.get("ts", ""),
                        "equity": eq,
                        "source": "ai_cycle",
                    })
            except Exception:
                continue

    # Single-agent AI cycles
    ai_dir = REPORTS_DIR / "ai_cycles"
    if ai_dir.exists():
        for f in sorted(ai_dir.glob("cycle_*.json")):
            try:
                data = json.loads(f.read_text())
                eq = data.get("context_summary", {}).get("equity")
                if eq:
                    history.append({
                        "ts": data.get("ts", ""),
                        "equity": eq,
                        "source": "ai_cycle",
                    })
            except Exception:
                continue

    # Deduplicate by timestamp
    seen = set()
    deduped = []
    for h in history:
        key = h["ts"][:16]  # truncate to minute
        if key not in seen:
            seen.add(key)
            deduped.append(h)
    return deduped
