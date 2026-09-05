#!/usr/bin/env python3
"""
Discord message formatter — produces compact, scannable trade notifications.

Reads the latest trading floor cycle JSON and outputs a tight message
optimized for Discord mobile reading.

Usage:
    python discord_format.py                    # reads latest, prints compact
    python discord_format.py --json cycle.json  # reads specific file
"""
import os, sys, json, argparse
from pathlib import Path
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent
LATEST = HERE / "reports" / "trading_floor" / "latest.json"


def format_discord(data):
    """Format a trading floor cycle JSON into a compact Discord message."""
    plan = data.get("desk_chief_plan") or data.get("plan") or {}
    ctx = data.get("context_summary", {})
    execution = data.get("execution", {})
    briefings = data.get("briefings", {})

    lines = []

    # ── Header ──
    ts_raw = data.get("ts", "")
    try:
        dt = datetime.fromisoformat(ts_raw)
        stamp = dt.strftime("%H:%M UTC")
    except Exception:
        stamp = ts_raw[:16] if ts_raw else "??"

    regime = ctx.get("regime", "?")
    lines.append(f"```elm")
    lines.append(f"┌─ TRADING FLOOR ─ {stamp}")

    # ── Portfolio snapshot ──
    equity = ctx.get("equity", 0)
    positions_count = ctx.get("positions", 0)
    lines.append(f"│ Equity ${equity:,.0f} │ Regime {regime}")

    # ── Positions (from account state in report, or context) ──
    # Try to extract positions from the raw report text
    report = data.get("report", "")
    pos_lines = []
    in_positions = False
    for rl in report.split("\n"):
        if "HOLDINGS:" in rl:
            # HOLDINGS: META(-1.1%), XLF(+0.3%)
            holdings = rl.split("HOLDINGS:")[1].strip() if "HOLDINGS:" in rl else ""
            if holdings and holdings != "none":
                lines.append(f"│ Holdings: {holdings}")
                in_positions = False
                break
        elif "Positions:" in rl and "position_count" not in rl.lower():
            in_positions = True
            continue
        elif in_positions and rl.strip().startswith("Sym"):
            continue
        elif in_positions and rl.strip().startswith("─"):
            continue
        elif in_positions and rl.strip() and not rl.strip().startswith("="):
            pos_lines.append(rl.strip())
        elif in_positions and (rl.strip().startswith("=") or not rl.strip()):
            in_positions = False

    # ── AI Decisions ──
    actions = plan.get("actions", [])
    lines.append(f"├─ AI DECISIONS ({len(actions)})")

    if not actions:
        lines.append("│  ○ No actions this cycle")
    else:
        for a in actions:
            act = a.get("action", "?").upper()
            sym = a.get("symbol", "")
            conviction = a.get("conviction", "?")
            thesis = a.get("thesis", "")

            # Action icon
            if act == "BUY":
                icon = "▲"
            elif act in ("SELL", "CLOSE"):
                icon = "▼"
            else:
                icon = "○"

            # Truncate thesis to fit Discord
            thesis_short = thesis[:120] + "…" if len(thesis) > 120 else thesis
            if sym:
                lines.append(f"│  {icon} {act} {sym} [{conviction}]")
                if thesis_short:
                    lines.append(f"│    {thesis_short}")
            else:
                lines.append(f"│  {icon} {act} [{conviction}] {thesis_short}")

    # ── Execution results ──
    results = execution.get("results", [])
    executed = execution.get("executed", False)
    exec_summary = []

    for r in results:
        status = r.get("status", "?")
        act = r.get("action", "?")
        sym = r.get("symbol", "")
        if status in ("submitted", "executed"):
            qty = r.get("qty", "")
            entry = r.get("entry", "")
            exec_summary.append(f"✓ {act} {sym} {qty}sh")
        elif status == "skipped":
            reason = r.get("reason", "")[:40]
            exec_summary.append(f"⊘ {sym}: {reason}")
        elif status == "error":
            err = r.get("error", "")[:40]
            exec_summary.append(f"✗ {sym}: {err}")
        elif status == "ok":
            pass  # HOLD is fine, no need to report

    if exec_summary:
        mode = "LIVE" if executed else "DRY"
        lines.append(f"├─ EXECUTION ({mode})")
        for e in exec_summary:
            lines.append(f"│  {e}")

    # ── Key strategy signals (if available) ──
    strat_lines = []
    for rl in report.split("\n"):
        if "MULTI-STRATEGY ALPHA" in rl:
            # Next few lines have strategy data
            strat_lines.append(rl)
        elif strat_lines and ("│" in rl or "bull" in rl.lower() or "bear" in rl.lower()):
            if len(strat_lines) < 4:
                strat_lines.append(rl.strip())
            else:
                break

    # ── Summary ──
    summary = plan.get("summary", "")
    confidence = plan.get("confidence", "?")
    if summary:
        summary_short = summary[:150] + "…" if len(summary) > 150 else summary
        lines.append(f"├─ STRATEGY [{confidence}]")
        lines.append(f"│  {summary_short}")

    model_label = (data.get("model") or "glm").replace("glm-", "GLM ").replace("-", " ").upper()
    lines.append(f"└─ {model_label} │ {len(briefings)} analysts")
    lines.append("```")

    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Format trading floor cycle for Discord")
    ap.add_argument("--json", help="Specific cycle JSON file (default: latest)")
    args = ap.parse_args()

    path = Path(args.json) if args.json else LATEST
    if not path.exists():
        print("[no trading floor cycle found]")
        return

    data = json.loads(path.read_text())
    print(format_discord(data))


if __name__ == "__main__":
    main()
