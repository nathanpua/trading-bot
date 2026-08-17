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
    status TEXT DEFAULT 'open',   -- open, closed
    broker_order_id TEXT,         -- Alpaca order id (dedupe key for reconciliation)
    exit_ts TEXT                  -- fill time of the closing sell (for closed rows)
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
    # Migration: older DBs lack broker_order_id (dedupe key for reconciliation)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(trades)")]
    if "broker_order_id" not in cols:
        conn.execute("ALTER TABLE trades ADD COLUMN broker_order_id TEXT")
    if "exit_ts" not in cols:
        conn.execute("ALTER TABLE trades ADD COLUMN exit_ts TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_boid ON trades(broker_order_id)")
    conn.commit()
    conn.close()


def record_trade(symbol, side, qty=None, entry_price=None, exit_price=None,
                 stop_price=None, target_price=None, pnl_dollars=None, pnl_pct=None,
                 position_pct=None, risk_pct=None, thesis="", outcome="open",
                 strategy="", regime="", tags=None, status="open", broker_order_id=None,
                 ts=None):
    """Record a trade action. broker_order_id is the Alpaca order id — used as
    dedupe key by reconcile_journal() so backfills never double-count.
    ts overrides the row timestamp (e.g. the broker fill time on rebuild)."""
    init_db()
    conn = _get_db()
    if broker_order_id is not None:
        dup = conn.execute(
            "SELECT id FROM trades WHERE broker_order_id=? AND status!='closed' LIMIT 1",
            (str(broker_order_id),)).fetchone()
        if dup:
            conn.close()
            logger.info("Skipping duplicate trade record for order %s (row %s)", broker_order_id, dup["id"])
            return
    ts = ts or datetime.now(timezone.utc).isoformat()
    tags_json = json.dumps(tags or [])
    conn.execute("""
        INSERT INTO trades (ts, symbol, side, qty, entry_price, exit_price,
            stop_price, target_price, pnl_dollars, pnl_pct, position_pct,
            risk_pct, thesis, outcome, strategy, regime, tags, status, broker_order_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (ts, symbol.upper(), side.upper(), qty, entry_price, exit_price,
          stop_price, target_price, pnl_dollars, pnl_pct, position_pct,
          risk_pct, thesis, outcome, strategy, regime, tags_json, status, str(broker_order_id) if broker_order_id else None))
    conn.execute("""
        INSERT INTO trades_fts (rowid, symbol, thesis, strategy, tags)
        VALUES (last_insert_rowid(), ?, ?, ?, ?)
    """, (symbol.upper(), thesis, strategy, tags_json))
    conn.commit()
    conn.close()
    logger.info("Recorded trade: %s %s %s", side, symbol, qty)


def close_trade(symbol, exit_price, pnl_dollars, pnl_pct, outcome="closed", thesis="", qty=None, exit_ts=None):
    """Close a position (or part of it) FIFO across open lots.

    With qty=None this closes the entire open position for the symbol, consuming
    ALL open lots oldest-first. With qty set, it consumes that many shares from
    the oldest lots, splitting the last lot if needed (partial-close of a lot
    creates a continuation row so totals always reconcile).

    Realized P&L passed in by the caller is attributed pro-rata by shares;
    per-lot exit price is the fill price given. Rows become status='closed' with
    outcome win/loss/breakeven derived from per-lot pnl.
    """
    init_db()
    conn = _get_db()
    sym = symbol.upper()
    lots = conn.execute(
        "SELECT id, qty, entry_price FROM trades WHERE symbol=? AND status='open' ORDER BY id",
        (sym,)
    ).fetchall()
    if not lots:
        conn.close()
        return

    total_open = sum(float(l["qty"] or 0) for l in lots)
    if total_open <= 0:
        conn.close()
        return
    close_qty = total_open if qty is None else min(float(qty), total_open)
    if close_qty <= 0:
        conn.close()
        return

    remaining = close_qty
    for lot in lots:
        if remaining <= 0:
            break
        lot_qty = float(lot["qty"] or 0)
        if lot_qty <= 0:
            continue
        take = min(remaining, lot_qty)
        share = take / close_qty
        lot_pnl = float(pnl_dollars or 0) * share
        lot_exit = float(exit_price) if exit_price is not None else None
        lot_entry = float(lot["entry_price"] or 0)
        lot_pnl_pct = (lot_pnl / (lot_entry * take) * 100) if lot_entry and take else None
        lot_outcome = "win" if lot_pnl > 0 else ("loss" if lot_pnl < 0 else "breakeven")
        if take >= lot_qty - 1e-9:
            # consume whole lot
            conn.execute("""
                UPDATE trades SET exit_price=?, pnl_dollars=?, pnl_pct=?, outcome=?,
                    thesis=CASE WHEN thesis IS NULL OR thesis='' THEN ? ELSE thesis || ' | ' || ? END,
                    status='closed', exit_ts=COALESCE(?, exit_ts)
                WHERE id=?
            """, (lot_exit, round(lot_pnl, 2), round(lot_pnl_pct, 4) if lot_pnl_pct is not None else None,
                  lot_outcome, thesis, thesis, exit_ts, lot["id"]))
        else:
            # partial: close the consumed part, keep remainder as new open row
            conn.execute("UPDATE trades SET qty=? WHERE id=?", (lot_qty - take, lot["id"]))
            conn.execute("""
                INSERT INTO trades (ts, symbol, side, qty, entry_price, exit_price,
                    stop_price, target_price, pnl_dollars, pnl_pct, position_pct,
                    risk_pct, thesis, outcome, strategy, regime, tags, status, broker_order_id, exit_ts)
                SELECT ts, symbol, side, ?, entry_price, ?, stop_price, target_price, ?, ?,
                    position_pct, risk_pct, thesis, ?, strategy, regime, tags, 'closed', broker_order_id, ?
                FROM trades WHERE id=?
            """, (take, lot_exit, round(lot_pnl, 2),
                  round(lot_pnl_pct, 4) if lot_pnl_pct is not None else None,
                  lot_outcome, exit_ts, lot["id"]))
            conn.execute("""
                INSERT INTO trades_fts (rowid, symbol, thesis, strategy, tags)
                SELECT last_insert_rowid(), symbol, thesis, strategy, tags
                FROM trades WHERE id=last_insert_rowid()
            """)
        remaining -= take

    conn.commit()
    conn.close()


def record_pending(order_id, kind, meta=None):
    """Register an order for later reconciliation with its AI context.

    kind: 'buy' | 'sell'. meta: dict with thesis/strategy/regime/
    position_pct/risk_pct/stop_price/target_price (buys) or thesis (sells).
    reconcile_journal() consumes these when the matching fill arrives,
    recording the trade with REAL fill prices plus this context, then
    deletes the pending row. Survives crashes (SQLite-backed).
    """
    init_db()
    conn = _get_db()
    conn.execute("""CREATE TABLE IF NOT EXISTS pending_orders (
        order_id TEXT PRIMARY KEY, kind TEXT NOT NULL, meta TEXT,
        created_at TEXT NOT NULL)""")
    conn.execute("INSERT OR REPLACE INTO pending_orders VALUES (?, ?, ?, datetime('now'))",
                 (str(order_id), kind, json.dumps(meta or {})))
    conn.commit()
    conn.close()


def reconcile_journal(thesis_map=None):
    """Rebuild the journal's open/closed ledger from broker (Alpaca) fills.

    This is the reconciliation pass that makes the journal a projection of
    broker truth instead of a parallel ledger that drifts:
      - Fetches ALL filled orders (chronological) via REST.
      - For every BUY fill not already in the journal (by broker_order_id),
        records it as an open lot.
      - For every SELL fill not already processed, closes FIFO lots with the
        real fill price and per-lot P&L (entry price from the lot row).
      - Preserves thesis/strategy/regime metadata from original lots.

    thesis_map: optional {order_id: {"thesis": str, "strategy": str,
    "regime": str}} — used by the one-time rebuild script to carry AI context
    from legacy rows onto the rebuilt lots.

    Idempotent: broker_order_id is the dedupe key on both sides. Safe to run
    every cycle; typically fast (no GLM calls, just REST + SQLite).

    Returns a dict with counts for logging/display.
    """
    import requests
    import alpaca_client as ac

    init_db()
    tc = ac.get_trading_client()
    base = tc._base_url.rstrip("/")
    hdrs = tc._get_auth_headers()

    # paginate closed orders (filled/canceled/expired), chronological
    fills = []
    after = "2026-07-31T00:00:00Z"  # account reset date — ignore anything older
    while True:
        resp = requests.get(f"{base}/v2/orders",
                            params={"status": "closed", "direction": "asc",
                                    "limit": 100, "after": after},
                            headers=hdrs, timeout=30)
        resp.raise_for_status()
        page = resp.json()
        fills.extend(o for o in page if o.get("status") == "filled")
        if len(page) < 100:
            break
        after = page[-1]["submitted_at"]

    # bracket legs that filled as part of a parent get order ids of their own,
    # but parent BUY rows already exist — dedupe on broker_order_id handles it.

    conn = _get_db()
    conn.execute("""CREATE TABLE IF NOT EXISTS applied_sells (
        order_id TEXT PRIMARY KEY, applied_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS pending_orders (
        order_id TEXT PRIMARY KEY, kind TEXT NOT NULL, meta TEXT,
        created_at TEXT NOT NULL)""")
    known_ids = {r["broker_order_id"] for r in
                 conn.execute("SELECT broker_order_id FROM trades WHERE broker_order_id IS NOT NULL")}
    known_ids |= {r["order_id"] for r in conn.execute("SELECT order_id FROM applied_sells")}
    # load pending AI context keyed by order id (consumed when fill arrives)
    pendings = {r["order_id"]: json.loads(r["meta"] or "{}") for r in
                conn.execute("SELECT order_id, meta FROM pending_orders")}
    conn.close()

    n_buys_added, n_sells_applied = 0, 0
    seen_in_run = set()
    for o in fills:
        oid = o.get("id")
        if not oid or oid in known_ids or oid in seen_in_run:
            continue
        seen_in_run.add(oid)
        sym = o.get("symbol", "").upper()
        qty = float(o.get("filled_qty") or 0)
        price = float(o.get("filled_avg_price") or 0)
        if qty <= 0 or price <= 0:
            continue
        if str(o.get("side")).lower() == "buy":
            meta = pendings.pop(oid, None) or (thesis_map or {}).get(oid, {})
            conn = _get_db()
            conn.execute("DELETE FROM pending_orders WHERE order_id=?", (oid,))
            conn.commit()
            conn.close()
            record_trade(symbol=sym, side="BUY", qty=qty, entry_price=price,
                         stop_price=meta.get("stop_price"),
                         target_price=meta.get("target_price"),
                         position_pct=meta.get("position_pct"),
                         risk_pct=meta.get("risk_pct"),
                         thesis=meta.get("thesis", "reconciled from broker fill"),
                         strategy=meta.get("strategy", "ai_multi_agent"),
                         regime=meta.get("regime", ""),
                         status="open",
                         broker_order_id=oid,
                         ts=o.get("submitted_at") or o.get("created_at"))
            n_buys_added += 1
        else:
            # SELL fill: FIFO-close this many shares at this price.
            # pnl per share = exit - entry(lot). Compute per lot inside close.
            conn = _get_db()
            lots = conn.execute(
                "SELECT id, qty, entry_price FROM trades WHERE symbol=? AND status='open' ORDER BY id",
                (sym,)).fetchall()
            conn.close()
            remaining = qty
            total_pnl = 0.0
            for lot in lots:
                if remaining <= 0:
                    break
                lot_qty = float(lot["qty"] or 0)
                if lot_qty <= 0:
                    continue
                take = min(remaining, lot_qty)
                pnl = (price - float(lot["entry_price"] or 0)) * take
                total_pnl += pnl
                remaining -= take
            if remaining > 0.5:
                # selling shares the journal has no lots for (shouldn't happen post-rebuild)
                logger.warning("reconcile: %s sell %s shares unmatched (no open lots)", sym, remaining)
            close_trade(symbol=sym, exit_price=price, pnl_dollars=total_pnl,
                        pnl_pct=None, outcome="closed",
                        thesis=(pendings.pop(oid, None) or {}).get(
                            "thesis", f"reconciled sell {qty} @ {price:.2f} (broker fill)"),
                        qty=qty,
                        exit_ts=o.get("submitted_at") or o.get("created_at"))
            conn = _get_db()
            conn.execute("DELETE FROM pending_orders WHERE order_id=?", (oid,))
            conn.commit()
            conn.close()
            # mark the sell order as processed so it's never applied twice
            conn = _get_db()
            conn.execute("""CREATE TABLE IF NOT EXISTS applied_sells (
                order_id TEXT PRIMARY KEY, applied_at TEXT NOT NULL)""")
            conn.execute("INSERT OR IGNORE INTO applied_sells VALUES (?, datetime('now'))",
                         (str(oid),))
            conn.commit()
            conn.close()
            n_sells_applied += 1

    return {"fills_scanned": len(fills), "buys_added": n_buys_added,
            "sells_applied": n_sells_applied}


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
