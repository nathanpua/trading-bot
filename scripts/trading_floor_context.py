#!/usr/bin/env python3
"""
Pre-cycle context — everything the desk chief needs in one shot.

Combines:
1. Portfolio state (positions, P&L, exposure)
2. Supermemory recall (relevant findings, lessons, patterns)
3. Trade journal stats (win rates, recent lessons)

Usage: python scripts/trading_floor_context.py
The output IS the context block the desk chief reads before deciding.
"""
import os, sys, json
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import alpaca_client as ac
from trade_memory import TradeMemory
import trade_journal as tj


def get_context():
    lines = []

    # 1. Portfolio state
    state_script = Path(__file__).parent / "trading_floor_state.py"
    import subprocess
    result = subprocess.run(
        [sys.executable, str(state_script)],
        capture_output=True, text=True, cwd=os.path.dirname(state_script.parent)
    )
    state = json.loads(result.stdout) if result.stdout.strip() else {}

    lines.append("=" * 60)
    lines.append("PORTFOLIO STATE")
    lines.append("=" * 60)
    acct = state.get("account", {})
    lines.append(f"Equity: ${acct.get('equity', 0):,.0f} | Cash: ${acct.get('cash', 0):,.0f} ({state.get('exposure', {}).get('cash_pct', 100):.0f}%)")
    lines.append(f"Market open: {state.get('market_open', False)} | Positions: {state.get('exposure', {}).get('position_count', 0)}")
    lines.append(f"Deployed: ${state.get('exposure', {}).get('total', 0):,.0f} ({state.get('exposure', {}).get('pct_of_portfolio', 0):.1f}%)")

    positions = state.get("positions", [])
    if positions:
        lines.append("\nHOLDINGS:")
        lines.append(f"  {'Sym':5} {'Qty':>6} {'P&L%':>7} {'RSI':>5} {'MACD':>7} {'Signal':>8}")
        lines.append(f"  {'---':5} {'---':>6} {'---':>7} {'---':>5} {'---':>7} {'---':>8}")
        for p in positions:
            tech = p.get("technicals", {})
            pnl = p.get("unrealized_plpc", 0)
            rsi = tech.get("rsi", 0)
            macd = tech.get("macd_diff", 0)
            bs = f"{tech.get('buy_score',0)}/{tech.get('sell_score',0)}"
            lines.append(f"  {p['symbol']:5} {p['qty']:>6.0f} {pnl:>+6.1f}% {rsi:>5.1f} {macd:>+7.3f} {bs:>8}")

    lines.append("\nREGIME PROXIES:")
    for sym, q in state.get("regime_proxies", {}).items():
        lines.append(f"  {sym:5} ${q['price']:8.2f} ({q['change_pct']:+.2f}%)")

    # 2. Memory recall
    lines.append("\n" + "=" * 60)
    lines.append("MEMORY RECALL (from supermemory)")
    lines.append("=" * 60)

    tm = TradeMemory()
    if tm.connected:
        held_symbols = [p["symbol"] for p in positions]
        context_block = tm.recall_for_cycle(held_symbols)
        lines.append(context_block)
    else:
        lines.append("[supermemory unavailable — using journal only]")

    # 3. Journal stats
    lines.append("\n" + "=" * 60)
    lines.append("TRADE JOURNAL")
    lines.append("=" * 60)

    stats = tj.get_stats()
    overall = stats.get("overall")
    if overall:
        lines.append(f"Record: {overall['trades']} trades | Win rate: {overall['win_rate']}% | Total P&L: ${overall['total_pnl']:,.2f}")
    else:
        lines.append("Record: No closed trades yet")

    by_strat = stats.get("by_strategy", [])
    if by_strat:
        lines.append("\nBy strategy:")
        for s in by_strat:
            lines.append(f"  {s['strategy']:15} {s['trades']} trades | {s['win_rate']}% win | ${s['total_pnl']:,.2f}")

    lessons = stats.get("recent_lessons", [])
    if lessons:
        lines.append("\nRecent lessons:")
        for l in lessons[:5]:
            lines.append(f"  [{l['category']}|{l['confidence']}] {l['lesson'][:100]}")

    # Open positions from journal
    lines.append("\n" + "=" * 60)
    lines.append("CONTEXT COMPLETE — make your decisions, Desk Chief")
    lines.append("=" * 60)

    return "\n".join(lines)


if __name__ == "__main__":
    print(get_context())
