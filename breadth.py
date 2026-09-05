"""
Sector breadth — % of S&P sector SPDRs trading above their 20-day SMA.

Market-internals gate for the regime assessment. The VIX-only regime logic
read RISK-ON on 177 of the first 178 cycles because a low VIX says nothing
about internals. Breadth net (above − below) overrides:

    net <= -5   → force RISK-OFF (broad deterioration across sectors)
    net < 0     → cap at NEUTRAL (narrow leadership; VIX alone can't say RISK-ON)
    net >= 0    → no override (VIX/SPY trend logic decides)

Also persists the current regime to reports/regime_now.json so downstream
writers (journal reconciliation of backfilled buys) can stamp the regime
they traded under even when the cycle that placed the order is gone.

CLI:
    python breadth.py              # print per-sector breadth table
    python breadth.py --json       # machine-readable summary
"""
import os, sys, json, logging, argparse
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

REGIME_NOW = HERE / "reports" / "regime_now.json"

SECTORS = {
    "XLK": "Tech", "XLY": "Discr", "XLP": "Staples", "XLE": "Energy",
    "XLF": "Fin", "XLV": "Health", "XLI": "Indust", "XLB": "Mat",
    "XLU": "Util", "XLRE": "REIT", "XLC": "Comm",
}


def compute_breadth(lookback=20, symbols=None):
    """Compute breadth across sector SPDRs.

    Returns dict with above/below/total/net counts and per-sector detail.
    Symbols with no data are skipped (not counted as below).
    """
    import alpaca_client as ac

    symbols = symbols or list(SECTORS)
    details = []
    for sym in symbols:
        try:
            df = ac.get_bars(sym, "1Day", lookback + 30)
            if df is None or len(df) < lookback + 1:
                continue
            close = df["close"].astype(float)
            sma = close.iloc[-lookback:].mean()
            last = float(close.iloc[-1])
            pct = (last / sma - 1) * 100
            details.append({"symbol": sym, "name": SECTORS.get(sym, sym),
                            "close": round(last, 2), "pct_vs_sma": round(pct, 2),
                            "above": pct >= 0})
        except Exception as e:
            logger.debug("breadth: %s failed: %s", sym, e)
            continue

    above = sum(1 for d in details if d["above"])
    below = len(details) - above
    return {"total": len(details), "above": above, "below": below,
            "net": above - below, "lookback": lookback, "details": details}


def apply_breadth_gate(regime_label, breadth):
    """Override the VIX-based regime label using breadth internals.

    Returns (label, reason_or_None).
    """
    net = breadth.get("net")
    if net is None:
        return regime_label, None
    if net <= -5:
        return "RISK-OFF", f"breadth net {net:+d} <= -5 (broad sector deterioration)"
    if net < 0 and regime_label == "RISK-ON":
        return "NEUTRAL", f"breadth net {net:+d} < 0 — narrow leadership, capping RISK-ON"
    return regime_label, None


def save_regime_now(regime):
    """Persist the current regime snapshot for downstream consumers
    (journal reconciliation stamps backfilled buys with this regime)."""
    try:
        REGIME_NOW.parent.mkdir(parents=True, exist_ok=True)
        snapshot = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "regime": regime.get("regime"),
            "vix_proxy": regime.get("vix_proxy"),
            "spy_trend": regime.get("spy_trend"),
            "breadth_net": regime.get("breadth_net"),
        }
        REGIME_NOW.write_text(json.dumps(snapshot, indent=2))
    except Exception as e:
        logger.debug("save_regime_now failed: %s", e)


def load_regime_now():
    """Read the last persisted regime snapshot (or None)."""
    try:
        return json.loads(REGIME_NOW.read_text())
    except Exception:
        return None


def main():
    logging.basicConfig(level=logging.WARNING)
    ap = argparse.ArgumentParser(description="S&P sector breadth vs 20-SMA")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    b = compute_breadth()
    if args.json:
        print(json.dumps({k: v for k, v in b.items() if k != "details"}, indent=2))
        return

    print("=== S&P SECTOR BREADTH vs 20-SMA ===")
    for d in sorted(b["details"], key=lambda x: -x["pct_vs_sma"]):
        print(f"{d['name']:<8}{d['close']:>9.2f}{d['pct_vs_sma']:>+8.2f}%  "
              f"{'ABOVE' if d['above'] else 'BELOW'}")
    print(f"\nABOVE 20-SMA: {b['above']}  |  BELOW: {b['below']}  |  "
          f"net breadth: {b['net']:+d}  (broad: >+5, narrow risk-off: <0)")


if __name__ == "__main__":
    main()
