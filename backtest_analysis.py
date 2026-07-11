"""
Corrected backtest harness for cross-symbol edge validation.

WHY THIS EXISTS (read me):
--------------------------
The shipped `backtest.py::SignalStrategy` has TWO bugs that make it produce
ZERO trades for every symbol:

  Bug A (data access): `next()` does `getattr(self.data, "buy_score", ...)`
    but backtrader's `PandasData` does NOT expose arbitrary dataframe columns
    as attributes. So `hasattr(self.data, "buy_score")` is always False and the
    buy/sell scores always read as 0 -> no order is ever placed.

  Bug B (signal scarcity + thin history): `get_bars(limit=500)` is silently
    capped at ~100 bars (Alpha Vantage `outputsize=compact`). With
    `buy_threshold=3` (3-of-5 indicators concurring) over ~100 daily bars, the
    entire 11-symbol watchlist yields only ~5 buy entries -> most symbols get
    0 trades, so the strategy cannot be ranked or parameter-swept at default.

This harness:
  * Fixes Bug A by using a custom PandasData feed (`SignalData`) that exposes
    `buy_score`/`sell_score` as proper backtrader lines, and a corrected
    `SignalStrategyFixed` that reads them via `self.data.buy_score[0]`.
  * Reuses the SAME data layer (alpaca_client.get_bars) and SAME signals
    (indicators.generate_signals) as the original module -> no fabrication.
  * Reports SignalStrategy at the DEFAULT threshold=3 (proves near-zero trades)
    AND at threshold=2 (the nearest backtestable config, clearly labeled) so a
    real parameter sweep can still be produced.
  * Runs SMACrossover (unaffected by Bug A/B) for a genuine edge ranking.

Original `backtest.py` is left UNMODIFIED.
"""

import backtrader as bt
import pandas as pd

import alpaca_client
import indicators
from backtest import SMACrossover  # the SMA strategy works as-is


# ---------------------------------------------------------------------------
# Corrected signal-aware data feed (fixes Bug A)
# ---------------------------------------------------------------------------
class SignalData(bt.feeds.PandasData):
    """PandasData that also exposes precomputed buy_score/sell_score lines."""
    lines = ("buy_score", "sell_score")
    params = (
        ("buy_score", -1),   # -1 = autodetect column by name
        ("sell_score", -1),
    )


# ---------------------------------------------------------------------------
# Corrected signal strategy (fixes Bug A)
# ---------------------------------------------------------------------------
class SignalStrategyFixed(bt.Strategy):
    params = (
        ("buy_threshold", 3),
        ("sell_threshold", 3),
        ("stop_loss_pct", 0.05),
        ("take_profit_pct", 0.10),
    )

    def __init__(self):
        self.order = None

    def next(self):
        if self.order:
            return
        price = self.data.close[0]
        if self.position:
            if self.data.close[0] <= self.stop_price:
                self.order = self.close(); return
            if self.data.close[0] >= self.take_profit:
                self.order = self.close(); return
            if self.data.sell_score[0] >= self.params.sell_threshold:
                self.order = self.close(); return
        else:
            if self.data.buy_score[0] >= self.params.buy_threshold:
                self.stop_price = price * (1 - self.params.stop_loss_pct)
                self.take_profit = price * (1 + self.params.take_profit_pct)
                self.order = self.buy()
                return


# ---------------------------------------------------------------------------
# Unified runner (mirrors backtest.run_backtest metrics keys)
# ---------------------------------------------------------------------------
def run(symbol, strategy, cash=100_000, **params):
    df = alpaca_client.get_bars(symbol, timeframe="1Day", limit=500)
    if df.empty:
        return {"symbol": symbol, "strategy": strategy.__name__, "error": "no data"}
    if "symbol" in df.columns:
        df = df.drop(columns=["symbol"])

    use_signals = strategy is SignalStrategyFixed
    if use_signals:
        df = indicators.generate_signals(df)

    df = df.rename(columns={"open": "Open", "high": "High", "low": "Low",
                            "close": "Close", "volume": "Volume"})
    df = df.set_index("timestamp")

    data_cls = SignalData if use_signals else bt.feeds.PandasData
    feed = data_cls(dataname=df)

    cerebro = bt.Cerebro()
    cerebro.adddata(feed)
    cerebro.addstrategy(strategy, **params)
    cerebro.broker.setcash(cash)
    cerebro.broker.setcommission(commission=0.001)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", riskfreerate=0.04)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="dd")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="ret")

    strat = cerebro.run()[0]
    final = cerebro.broker.getvalue()

    ta = strat.analyzers.trades.get_analysis()
    sharpe = strat.analyzers.sharpe.get_analysis()
    dd = strat.analyzers.dd.get_analysis()
    ret = strat.analyzers.ret.get_analysis()

    total_trades = ta.get("total", {}).get("total", 0)
    won = ta.get("won", {})
    won_n = won.get("total", 0) if won else 0
    win_rate = (won_n / total_trades * 100) if total_trades > 0 else 0.0

    return {
        "symbol": symbol,
        "strategy": strategy.__name__,
        "total_return_pct": round((final - cash) / cash * 100, 2),
        "annual_return_pct": round(float(ret.get("rnorm", 0) or 0) * 100, 2),
        "sharpe_ratio": round(float(sharpe.get("sharperatio", 0) or 0), 3),
        "max_drawdown_pct": round(float(dd.get("max", {}).get("drawdown", 0)), 2),
        "win_rate": round(win_rate, 1),
        "total_trades": int(total_trades),
    }
