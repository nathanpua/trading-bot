"""
Backtesting engine using Backtrader.

Tests trading strategies on historical data and produces performance metrics:
- Total return, CAGR, Sharpe ratio, max drawdown
- Win rate, average win/loss, profit factor
- Equity curve

Usage from agent: load a strategy class, run against Alpaca historical bars.
"""

import sys
import json
from datetime import datetime

import backtrader as bt
import pandas as pd

import alpaca_client


class SignalData(bt.feeds.PandasData):
    """
    PandasData feed that also exposes precomputed `buy_score` / `sell_score`
    columns as backtrader lines.

    backtrader's stock `PandasData` does NOT expose arbitrary dataframe columns,
    which is why the original `SignalStrategy` always read buy_score/sell_score as
    0 (zero trades). Subclassing and declaring the extra lines fixes that. Pass a
    DataFrame (DatetimeIndex) with OHLCV plus `buy_score` and `sell_score`.
    """
    lines = ("buy_score", "sell_score")
    params = (
        ("buy_score", -1),   # -1 = autodetect column by line name
        ("sell_score", -1),
    )


class SignalStrategy(bt.Strategy):
    """
    Generic strategy that uses the indicator confluence from indicators.py.
    Buy when buy_score >= buy_threshold, sell when sell_score >= sell_threshold.
    Also exits on the stop-loss / take-profit bands set at entry time.
    """
    params = (
        ("buy_threshold", 3),
        ("sell_threshold", 3),
        ("stop_loss_pct", 0.05),
        ("take_profit_pct", 0.10),
    )

    def __init__(self):
        self.order = None
        self.buy_price = None
        self.stop_price = None
        self.take_profit = None
        self.trades = []

    def notify_order(self, order):
        # Clear the in-flight order ref once it is no longer pending so the
        # strategy can place the next entry/exit (standard backtrader pattern).
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.order = None

    def next(self):
        if self.order:
            return

        # Check stop / take profit for open position
        if self.position:
            if self.data.close[0] <= self.stop_price:
                self.order = self.close()
                return
            if self.data.close[0] >= self.take_profit:
                self.order = self.close()
                return

        # Read precomputed confluence scores exposed as data lines via SignalData.
        buy_score = self.data.buy_score[0]
        sell_score = self.data.sell_score[0]

        if not self.position and buy_score >= self.params.buy_threshold:
            self.buy_price = self.data.close[0]
            self.stop_price = self.buy_price * (1 - self.params.stop_loss_pct)
            self.take_profit = self.buy_price * (1 + self.params.take_profit_pct)
            self.order = self.buy()
        elif self.position and sell_score >= self.params.sell_threshold:
            self.order = self.close()


class SMACrossover(bt.Strategy):
    """Simple SMA crossover strategy for baseline testing."""
    params = (("fast", 20), ("slow", 50))

    def __init__(self):
        self.sma_fast = bt.indicators.SMA(self.data.close, period=self.params.fast)
        self.sma_slow = bt.indicators.SMA(self.data.close, period=self.params.slow)
        self.crossover = bt.indicators.CrossOver(self.sma_fast, self.sma_slow)
        self.order = None

    def next(self):
        if self.order:
            return
        if not self.position:
            if self.crossover > 0:
                self.order = self.buy()
        elif self.crossover < 0:
            self.order = self.close()


def run_backtest(symbol, strategy_cls=SignalStrategy, timeframe="1Day",
                 limit=500, cash=100000, **strategy_params):
    """
    Run a backtest for a single symbol.
    
    Args:
        symbol: ticker symbol
        strategy_cls: backtrader Strategy class
        timeframe: Alpaca timeframe string
        limit: number of historical bars
        cash: starting capital
        **strategy_params: passed to the strategy
    
    Returns dict with performance metrics.
    """
    # Fetch data
    df = alpaca_client.get_bars(symbol, timeframe=timeframe, limit=limit)
    if df.empty:
        return {"error": f"No data for {symbol}"}
    
    # Drop symbol column if present (from cached data)
    if "symbol" in df.columns:
        df = df.drop(columns=["symbol"])
    
    # Compute indicators BEFORE renaming columns (indicators expect lowercase)
    if strategy_cls == SignalStrategy:
        import indicators
        df = indicators.generate_signals(df)
    
    # Rename columns for backtrader (after indicators are computed)
    df = df.rename(columns={
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "volume": "Volume",
    })
    df = df.set_index("timestamp")

    # Create backtrader feed. SignalStrategy needs the custom SignalData feed so
    # that buy_score/sell_score are exposed as data lines; other strategies use
    # the stock PandasData feed.
    if strategy_cls == SignalStrategy:
        data = SignalData(dataname=df)
    else:
        data = bt.feeds.PandasData(dataname=df)
    
    # Set up engine
    cerebro = bt.Cerebro()
    cerebro.adddata(data)
    cerebro.addstrategy(strategy_cls, **strategy_params)
    cerebro.broker.setcash(cash)
    cerebro.broker.setcommission(commission=0.001)  # 0.1% per trade

    # Position sizer: invest a fixed fraction of portfolio per trade. Without this
    # backtrader defaults to buying ONE share, which makes returns ~0% and Sharpe
    # meaningless. 95% keeps a small cash buffer for commission/slippage.
    cerebro.addsizer(bt.sizers.PercentSizer, percents=95)
    
    # Analyzers
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    # NOTE: backtrader's SharpeRatio analyzer is unreliable across versions (it
    # returns nonsensical values with these pandas/backtrader builds). We capture
    # daily equity returns via TimeReturn and annualize the Sharpe ourselves.
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name="timereturn", timeframe=bt.TimeFrame.Days)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    
    # Run
    results = cerebro.run()
    strat = results[0]
    final_value = cerebro.broker.getvalue()
    
    # Extract metrics
    trade_analysis = strat.analyzers.trades.get_analysis()
    drawdown = strat.analyzers.drawdown.get_analysis()
    returns = strat.analyzers.returns.get_analysis()

    # Annualized Sharpe computed from daily equity returns (rf = 4%/yr).
    # Guard against near-flat equity curves (e.g. a strategy that rarely trades):
    # a sub-threshold return std produces absurd Sharpe values (hundreds), which
    # are noise, not edge. Report 0.0 in that case rather than a meaningless number.
    daily_rets = pd.Series(strat.analyzers.timereturn.get_analysis())
    sharpe_ratio = 0.0
    if len(daily_rets) > 1:
        std = daily_rets.std()
        if std and std > 1e-5:
            rf_daily = 0.04 / 252
            sharpe_ratio = float(
                (daily_rets - rf_daily).mean() / std * (252 ** 0.5)
            )

    total_return = ((final_value - cash) / cash) * 100
    
    won = trade_analysis.get("won", {})
    lost = trade_analysis.get("lost", {})
    total_trades = trade_analysis.get("total", {}).get("total", 0)
    won_count = won.get("total", 0) if won else 0
    lost_count = lost.get("total", 0) if lost else 0
    win_rate = (won_count / total_trades * 100) if total_trades > 0 else 0
    
    return {
        "symbol": symbol,
        "strategy": strategy_cls.__name__,
        "start_cash": cash,
        "final_value": round(final_value, 2),
        "total_return_pct": round(total_return, 2),
        "total_trades": total_trades,
        "win_rate": round(win_rate, 1),
        "avg_win": round(float(won.get("pnl", {}).get("average", 0)), 2) if won else 0,
        "avg_loss": round(float(lost.get("pnl", {}).get("average", 0)), 2) if lost else 0,
        "sharpe_ratio": round(sharpe_ratio, 3),
        "max_drawdown_pct": round(float(drawdown.get("max", {}).get("drawdown", 0)), 2),
        "annual_return_pct": round(float(returns.get("rnorm", 0) or 0) * 100, 2),
    }


def format_backtest_report(metrics):
    """Format backtest results as a monospace report."""
    if "error" in metrics:
        return f"Backtest Error: {metrics['error']}"
    
    lines = [
        f"━━━ Backtest: {metrics['symbol']} ━━━",
        f"Strategy:     {metrics['strategy']}",
        f"Start Cash:   ${metrics['start_cash']:,.0f}",
        f"Final Value:  ${metrics['final_value']:,.2f}",
        f"Return:       {metrics['total_return_pct']:+.2f}%",
        f"Annual:       {metrics['annual_return_pct']:+.2f}%",
        f"─────────────────────────",
        f"Trades:       {metrics['total_trades']}",
        f"Win Rate:     {metrics['win_rate']:.1f}%",
        f"Avg Win:      ${metrics['avg_win']:+.2f}",
        f"Avg Loss:     ${metrics['avg_loss']:+.2f}",
        f"─────────────────────────",
        f"Sharpe:       {metrics['sharpe_ratio']:.3f}",
        f"Max Drawdown: {metrics['max_drawdown_pct']:.2f}%",
    ]
    return "\n".join(lines)
