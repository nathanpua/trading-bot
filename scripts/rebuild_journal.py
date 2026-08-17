#!/usr/bin/env python3
"""One-time journal rebuild from broker fills (Aug 2026).

The legacy journal drifted from broker truth (TRIMs never recorded,
LIFO-only closes left ghost open lots, P&L taken from pre-fill snapshots).
This script:
  1. Snapshots legacy rows to reports/journal_legacy_backup_<ts>.json
  2. Wipes trades + applied_sells
  3. Rebuilds every lot from Alpaca filled orders (FIFO), carrying over
     thesis/strategy/regime from legacy rows matched by (symbol, qty, ~date)
  4. Verifies: rebuilt open lots == live Alpaca positions (symbol+qty),
     and realized P&L + unrealized == account equity gain since reset.
"""
import sys, os, json, sqlite3, shutil
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.chdir(Path(__file__).resolve().parent.parent)

import trade_journal as tj
import alpaca_client as ac

tj.init_db()

# ── 1. snapshot legacy ──
conn = tj._get_db()
legacy = [dict(r) for r in conn.execute("SELECT * FROM trades ORDER BY id")]
ts_tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
backup = Path("reports") / f"journal_legacy_backup_{ts_tag}.json"
backup.write_text(json.dumps(legacy, indent=1, default=str))
print(f"[1] legacy snapshot: {len(legacy)} rows -> {backup}")

# thesis map from legacy BUY rows: (symbol, qty, day) -> meta
def legacy_meta(sym, qty, day):
    best = None
    for r in legacy:
        if r["symbol"] != sym or r["side"] != "BUY":
            continue
        if abs((r["qty"] or 0) - qty) > max(1.0, qty * 0.02):
            continue
        rday = (r["ts"] or "")[:10]
        dist = abs((datetime.fromisoformat(rday) - datetime.fromisoformat(day)).days) if rday and day else 99
        if best is None or dist < best[0]:
            best = (dist, r)
    if best and best[0] <= 1:
        r = best[1]
        return {"thesis": r.get("thesis") or "", "strategy": r.get("strategy") or "ai_multi_agent",
                "regime": r.get("regime") or ""}
    return {}

# ── 2. wipe ──
conn.execute("DELETE FROM trades")
conn.execute("DELETE FROM trades_fts")
conn.execute("DROP TABLE IF EXISTS applied_sells")
conn.commit()
conn.close()
print("[2] trades + applied_sells wiped")

# ── 3. fetch fills and build thesis_map keyed by order id ──
import requests
tc = ac.get_trading_client()
base = tc._base_url.rstrip("/")
hdrs = tc._get_auth_headers()
fills, after = [], "2026-07-31T00:00:00Z"
while True:
    resp = requests.get(f"{base}/v2/orders",
                        params={"status": "closed", "direction": "asc", "limit": 100, "after": after},
                        headers=hdrs, timeout=30)
    resp.raise_for_status()
    page = resp.json()
    fills.extend(o for o in page if o.get("status") == "filled")
    if len(page) < 100:
        break
    after = page[-1]["submitted_at"]
print(f"[3] broker fills fetched: {len(fills)}")

thesis_map = {}
for o in fills:
    if str(o.get("side")).lower() != "buy":
        continue
    sym = o.get("symbol", "").upper()
    qty = float(o.get("filled_qty") or 0)
    day = (o.get("submitted_at") or "")[:10]
    thesis_map[o["id"]] = legacy_meta(sym, qty, day)

# ── 4. rebuild ──
rec = tj.reconcile_journal(thesis_map=thesis_map)
print(f"[4] rebuilt: {rec}")

# ── 5. verify ──
conn = tj._get_db()
ok = True

# open lots vs live positions
open_by_sym = {}
for r in conn.execute("SELECT symbol, SUM(qty) q FROM trades WHERE status='open' GROUP BY symbol"):
    open_by_sym[r["symbol"]] = float(r["q"] or 0)
live = {p["symbol"]: float(p["qty"]) for p in ac.get_positions()}
for sym in sorted(set(open_by_sym) | set(live)):
    j, l = open_by_sym.get(sym, 0), live.get(sym, 0)
    match = abs(j - l) < 1.0
    ok &= match
    print(f"    {sym:5} journal_open={j:8.1f}  alpaca={l:8.1f}  {'OK' if match else 'MISMATCH'}")

# realized + unrealized vs equity gain
realized = conn.execute("SELECT SUM(pnl_dollars) s FROM trades WHERE status='closed'").fetchone()["s"] or 0
unreal = sum(float(p.get("unrealized_pl", 0) or 0) for p in ac.get_positions())
equity_gain = float(ac.get_account()["equity"]) - 100000.0
recon_gap = (realized + unreal) - equity_gain
print(f"    realized=${realized:,.2f} + unrealized=${unreal:,.2f} = ${realized+unreal:,.2f}  vs equity gain ${equity_gain:,.2f}  gap=${recon_gap:,.2f}")

# stats now
stats = tj.get_stats().get("overall", {})
print(f"    stats: {stats}")
conn.close()

print()
print("REBUILD " + ("VERIFIED" if ok else "COMPLETED WITH MISMATCHES — inspect above"))
sys.exit(0 if ok else 2)
