"""Smoke test: verify data depth + that SignalStrategy now produces trades."""
import warnings
warnings.filterwarnings("ignore")
import alpaca_client
import backtest

print("=== Data depth via get_bars (limit=500) ===")
for sym in ("AAPL", "SMH"):
    df = alpaca_client.get_bars(sym, timeframe="1Day", limit=500)
    if "symbol" in df.columns:
        df = df[df["symbol"] == sym]
    rng = f"{df['timestamp'].min().date()} -> {df['timestamp'].max().date()}" if not df.empty else "EMPTY"
    print(f"  {sym}: {len(df)} bars  {rng}")

print("\n=== Single backtests (limit=750) ===")
for strat in (backtest.SignalStrategy, backtest.SMACrossover):
    m = backtest.run_backtest("AAPL", strategy_cls=strat, limit=750)
    print(f"  {m['strategy']:16s} trades={m['total_trades']:3d}  "
          f"ret={m['total_return_pct']:+.2f}%  sharpe={m['sharpe_ratio']:.3f}  "
          f"maxdd={m['max_drawdown_pct']:.2f}%  winrate={m['win_rate']:.1f}%")
