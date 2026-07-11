#!/usr/bin/env python3
"""
Trade Journal — structured persistent record of every trade and its outcome.

SQLite database with three tables:
  - trades: every executed trade (entry, exit, P&L, thesis, outcome)
  - lessons: distilled insights (what worked, what failed, best practices)
  - strategies: per-strategy performance stats (win rate, avg R/R)

This is the HARD DATA layer that complements trade_memory.py's semantic layer.
SQL-queryable: "what's my win rate on momentum trades into earnings?"
"""
import os, sqlite3, json, logging
from datetime import datetime, timezone, date
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "reports" / "trade_journal.db"


def _get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,           -- BUY, SELL, CLOSE, TRIM
    qty REAL,
    entry_price REAL,
    exit_price REAL,
    stop_price REAL,
    target_price REAL,
    pnl_dollars REAL,
    pnl_pct REAL,
    position_pct REAL,
    risk_pct REAL,
    thesis TEXT,
    outcome TEXT,                 -- open, win, loss, breakeven, stopped, target_hit
    strategy TEXT,                -- momentum, confluence, mean_reversion, breakout
    regime TEXT,                  -- risk_on, neutral, risk_off, defensive
    tags TEXT,                    -- JSON array of custom tags
    status TEXT DEFAULT 'open'   -- open, closed
);

CREATE TABLE IF NOT EXISTS lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    category TEXT NOT NULL,       -- strategy, execution, risk, regime, symbol
    lesson TEXT NOT NULL,
    evidence TEXT,                -- what trade/data supports this
    confidence TEXT DEFAULT 'medium'  -- high, medium, low
);

CREATE TABLE IF NOT EXISTS cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    session TEXT,                 -- am, pm
    regime TEXT,
    equity REAL,
    cash_pct REAL,
    deployed_pct REAL,
    position_count INTEGER,
    actions TEXT,                 -- JSON of actions taken
    report TEXT                   -- the desk chief briefing text
);

-- FTS5 for full-text search on trades and lessons
CREATE VIRTUAL TABLE IF NOT EXISTS trades_fts USING fts5(
    symbol, thesis, strategy, tags,
    content='trades', content_rowid='id'
);

CREATE VIRTUAL TABLE IF NOT EXISTS lessons_fts USING fts5(
    category, lesson, evidence,
    content='lessons', content_rowid='id'
);
"""


def init_db():
    conn = _get_db()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def record_trade(symbol, side, qty=None, entry_price=None, exit_price=None,
                 stop_price=None, target_price=None, pnl_dollars=None, pnl_pct=None,
                 position_pct=None, risk_pct=None, thesis="", outcome="open",
                 strategy="", regime="", tags=None, status="open"):
    """Record a trade action."""
    init_db()
    conn = _get_db()
    ts = datetime.now(timezone.utc).isoformat()
    tags_json = json.dumps(tags or [])
    conn.execute("""
        INSERT INTO trades (ts, symbol, side, qty, entry_price, exit_price,
            stop_price, target_price, pnl_dollars, pnl_pct, position_pct,
            risk_pct, thesis, outcome, strategy, regime, tags, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (ts, symbol.upper(), side.upper(), qty, entry_price, exit_price,
          stop_price, target_price, pnl_dollars, pnl_pct, position_pct,
          risk_pct, thesis, outcome, strategy, regime, tags_json, status))
    conn.execute("""
        INSERT INTO trades_fts (rowid, symbol, thesis, strategy, tags)
        VALUES (last_insert_rowid(), ?, ?, ?, ?)
    """, (symbol.upper(), thesis, strategy, tags_json))
    conn.commit()
    conn.close()
    logger.info("Recorded trade: %s %s %s", side, symbol, qty)


def close_trade(symbol, exit_price, pnl_dollars, pnl_pct, outcome="closed", thesis=""):
    """Close the most recent open trade for a symbol."""
    init_db()
    conn = _get_db()
    # SQLite UPDATE doesn't support ORDER BY/LIMIT — use subquery to find row id
    row = conn.execute(
        "SELECT id FROM trades WHERE symbol=? AND status='open' ORDER BY id DESC LIMIT 1",
        (symbol.upper(),)
    ).fetchone()
    if not row:
        conn.close()
        return
    conn.execute("""
        UPDATE trades SET exit_price=?, pnl_dollars=?, pnl_pct=?, outcome=?,
            thesis=thesis || ' | ' || ?, status='closed'
        WHERE id=?
    """, (exit_price, pnl_dollars, pnl_pct, outcome, thesis, row["id"]))
    conn.commit()
    conn.close()


def record_cycle(session="", regime="", equity=0, cash_pct=0, deployed_pct=0,
                 position_count=0, actions=None, report=""):
    """Record a cycle execution."""
    init_db()
    conn = _get_db()
    ts = datetime.now(timezone.utc).isoformat()
    actions_json = json.dumps(actions or [])
    conn.execute("""
        INSERT INTO cycles (ts, session, regime, equity, cash_pct, deployed_pct,
            position_count, actions, report)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (ts, session, regime, equity, cash_pct, deployed_pct,
          position_count, actions_json, report))
    conn.commit()
    conn.close()


def add_lesson(category, lesson, evidence="", confidence="medium"):
    """Record a distilled lesson."""
    init_db()
    conn = _get_db()
    ts = datetime.now(timezone.utc).isoformat()
    conn.execute("""
        INSERT INTO lessons (ts, category, lesson, evidence, confidence)
        VALUES (?, ?, ?, ?, ?)
    """, (ts, category, lesson, evidence, confidence))
    conn.execute("""
        INSERT INTO lessons_fts (rowid, category, lesson, evidence)
        VALUES (last_insert_rowid(), ?, ?, ?)
    """, (category, lesson, evidence))
    conn.commit()
    conn.close()
    logger.info("Recorded lesson: [%s] %s", category, lesson[:60])


def get_stats():
    """Aggregate performance stats."""
    init_db()
    conn = _get_db()
    stats = {}

    # Overall
    row = conn.execute("""
        SELECT COUNT(*) as total,
            SUM(CASE WHEN pnl_dollars > 0 THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN pnl_dollars < 0 THEN 1 ELSE 0 END) as losses,
            SUM(pnl_dollars) as total_pnl,
            AVG(pnl_pct) as avg_pnl_pct
        FROM trades WHERE status='closed' AND pnl_dollars IS NOT NULL
    """).fetchone()
    if row and row["total"]:
        stats["overall"] = {
            "trades": row["total"], "wins": row["wins"], "losses": row["losses"],
            "win_rate": round(row["wins"] / row["total"] * 100, 1) if row["total"] else 0,
            "total_pnl": round(row["total_pnl"] or 0, 2),
            "avg_pnl_pct": round(row["avg_pnl_pct"] or 0, 2),
        }

    # By strategy
    rows = conn.execute("""
        SELECT strategy,
            COUNT(*) as total,
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

    # By symbol
    rows = conn.execute("""
        SELECT symbol,
            COUNT(*) as total,
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

    # Recent lessons
    rows = conn.execute("""
        SELECT category, lesson, confidence FROM lessons ORDER BY id DESC LIMIT 10
    """).fetchall()
    stats["recent_lessons"] = [dict(r) for r in rows]

    conn.close()
    return stats


def search_lessons(query, limit=5):
    """Full-text search across lessons."""
    init_db()
    conn = _get_db()
    rows = conn.execute("""
        SELECT l.category, l.lesson, l.evidence, l.confidence
        FROM lessons_fts f JOIN lessons l ON f.rowid = l.id
        WHERE lessons_fts MATCH ?
        ORDER BY rank LIMIT ?
    """, (query, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def search_trades(query, limit=5):
    """Full-text search across trade theses."""
    init_db()
    conn = _get_db()
    rows = conn.execute("""
        SELECT t.symbol, t.side, t.thesis, t.outcome, t.pnl_dollars, t.pnl_pct
        FROM trades_fts f JOIN trades t ON f.rowid = t.id
        WHERE trades_fts MATCH ?
        ORDER BY rank LIMIT ?
    """, (query, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Trade journal CLI")
    sub = ap.add_subparsers(dest="command")

    sub.add_parser("stats", help="Show performance stats")
    sub.add_parser("lessons", help="Show recent lessons")
    sp = sub.add_parser("search", help="Search trades/lessons")
    sp.add_argument("query")

    sp = sub.add_parser("lesson", help="Add a lesson")
    sp.add_argument("category", choices=["strategy", "execution", "risk", "regime", "symbol"])
    sp.add_argument("lesson")
    sp.add_argument("--evidence", default="")
    sp.add_argument("--confidence", default="medium", choices=["high", "medium", "low"])

    args = ap.parse_args()

    if args.command == "stats":
        print(json.dumps(get_stats(), indent=2))
    elif args.command == "lessons":
        init_db()
        conn = _get_db()
        rows = conn.execute("SELECT * FROM lessons ORDER BY id DESC LIMIT 20").fetchall()
        for r in rows:
            print(f"[{r['category']}|{r['confidence']}] {r['lesson']}")
            if r["evidence"]:
                print(f"  evidence: {r['evidence']}")
        conn.close()
    elif args.command == "search":
        print("TRADES:")
        for t in search_trades(args.query):
            print(f"  {t['symbol']} {t['side']} [{t['outcome']}] P&L=${t.get('pnl_dollars',0)} | {t['thesis'][:80]}")
        print("\nLESSONS:")
        for l in search_lessons(args.query):
            print(f"  [{l['category']}|{l['confidence']}] {l['lesson']}")
    elif args.command == "lesson":
        add_lesson(args.category, args.lesson, args.evidence, args.confidence)
        print("Lesson recorded.")
    else:
        ap.print_help()
