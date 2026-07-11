#!/usr/bin/env python3
"""
Whole-market technical scanner.

Pulls daily OHLCV from Alpaca (primary, ~890 bars history) for a broad universe
(semis / memory / volatile / mega-cap / ETFs), computes the full indicator suite,
and ranks by buy/sell confluence. Optionally overlays Finnhub real-time quotes.

Usage:
    python scripts/scan_universe.py            # full universe, ranked
    python scripts/scan_universe.py --top 6    # + detail table for top 6
"""
import os, sys, time, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import alpaca_client
import indicators

UNIVERSE = {
    "Memory/Storage":   ["MU", "WDC", "STX"],
    "Semi Equipment":   ["AMAT", "LRCX", "KLAC", "ASML", "TER", "ONTO"],
    "Semis (chips)":    ["NVDA", "AVGO", "QCOM", "TXN", "AMD", "INTC", "NXPI",
                         "MCHP", "ON", "ARM", "SMCI", "MRVL", "MPWR"],
    "AI / High-beta":   ["COIN", "MSTR", "RKLB", "HOOD", "PLTR", "RDDT",
                         "AFRM", "SOFI", "DASH", "NU", "SNOW", "DDOG"],
    "Mega-cap":         ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA"],
    "ETFs":             ["SMH", "SOXX", "XSD", "XLE", "XBI", "ARKK", "SPY", "QQQ"],
}

DETAIL_COLS = ["close", "rsi", "macd_diff", "sma_20", "sma_50",
               "bb_high", "bb_low", "atr", "adx", "stoch_k", "stoch_d"]


def fetch_with_signals(symbol, limit=200):
    df = alpaca_client.get_bars(symbol, "1Day", limit)
    if df is None or df.empty:
        return None
    df = indicators.add_all_indicators(df)
    df = indicators.generate_signals(df)
    return df


def scan():
    rows = []
    dfs = {}
    for bucket, syms in UNIVERSE.items():
        for sym in syms:
            try:
                df = fetch_with_signals(sym)
                if df is None or df.empty:
                    rows.append({"symbol": sym, "bucket": bucket, "error": "no data"})
                    continue
                dfs[sym] = df
                r = df.iloc[-1]
                def g(col):
                    v = r[col]
                    return None if pd.isna(v) else float(v)
                above_sma50 = g("sma_50") is not None and r["close"] > g("sma_50")
                bb_pos = "upper" if r["close"] > g("bb_high") else \
                         "lower" if g("bb_low") is not None and r["close"] < g("bb_low") else "mid"
                rows.append({
                    "symbol": sym, "bucket": bucket, "close": round(r["close"], 2),
                    "rsi": g("rsi"), "macd_diff": g("macd_diff"),
                    "sma20": g("sma_20"), "sma50": g("sma_50"),
                    "above_sma50": above_sma50, "bb_pos": bb_pos,
                    "atr": g("atr"), "adx": g("adx"),
                    "stoch_k": g("stoch_k"), "stoch_d": g("stoch_d"),
                    "buy_score": int(r["buy_score"]), "sell_score": int(r["sell_score"]),
                    "signal": int(r["signal"]),
                })
            except Exception as e:
                rows.append({"symbol": sym, "bucket": bucket, "error": str(e)[:40]})
            time.sleep(0.15)
    return rows, dfs


def fmt_ranked(rows):
    ok = [r for r in rows if "error" not in r]
    bad = [r for r in rows if "error" in r]
    ok.sort(key=lambda x: (x["buy_score"], x["rsi"] if x["rsi"] else 99), reverse=True)
    out = []
    out.append("Sym    Bucket         Close     RSI   MACDd   SMA20>50  BB    ADX   StochK  Buy/Sell  Sig")
    out.append("────── ────────────── ───────── ────  ─────── ────────  ────  ──── ──────  ────────  ───")
    for r in ok:
        sig = "BUY" if r["signal"] == 1 else "SELL" if r["signal"] == -1 else "hold"
        trend = "uptrend" if r["above_sma50"] else "downtrend"
        out.append(
            f"{r['symbol']:<6} {r['bucket']:<13} {r['close']:>8.2f}  "
            f"{r['rsi']:>4.0f}  {r['macd_diff']:>+7.3f}  {trend:<8}  {r['bb_pos']:<5}  "
            f"{r['adx']:>4.0f}  {r['stoch_k']:>5.1f}   {r['buy_score']}B/{r['sell_score']}S     {sig}"
        )
    if bad:
        out.append("")
        out.append("Errors: " + ", ".join(f"{r['symbol']}({r['error']})" for r in bad))
    return "\n".join(out)


def fmt_detail(dfs, symbols, n):
    out = []
    for sym in symbols[:n]:
        df = dfs.get(sym)
        if df is None:
            continue
        out.append(f"\n── {sym} (last {min(len(df), 5)} bars) " + "─" * max(2, 40 - len(sym)))
        sub = df[DETAIL_COLS].tail(5).copy()
        for c in sub.columns:
            sub[c] = sub[c].map(lambda v: "" if pd.isna(v) else (f"{v:.2f}"))
        out.append(sub.to_string(index=False))
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=0, help="also print detail for top N")
    args = ap.parse_args()
    rows, dfs = scan()
    print(fmt_ranked(rows))
    # Flag confirmed signals
    confirmed = [r for r in rows if "error" not in r and (r["buy_score"] >= 3 or r["sell_score"] >= 3)]
    if confirmed:
        print("\n⚑ CONFIRMED SIGNALS (score >= 3):")
        for r in confirmed:
            print(f"  {r['symbol']:<5} {r['buy_score']}B/{r['sell_score']}S  RSI {r['rsi']:.0f}  "
                  f"{'BUY' if r['signal']==1 else 'SELL' if r['signal']==-1 else '—'}")
    else:
        print("\n(no confirmed signals — score >= 3)")
    if args.top:
        ok = [r for r in rows if "error" not in r]
        ok.sort(key=lambda x: (x["buy_score"], x["rsi"] if x["rsi"] else 99), reverse=True)
        print(fmt_detail(dfs, [r["symbol"] for r in ok], args.top))


if __name__ == "__main__":
    main()
