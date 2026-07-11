"""Compare SharpeRatio analyzer configs to find a sane one."""
import warnings
warnings.filterwarnings("ignore")
import backtrader as bt
import pandas as pd
import alpaca_client
import indicators
from backtest import SignalStrategy, SignalData, SMACrossover


def run(symbol, strategy, limit=750, **sharpe_cfg):
    df = alpaca_client.get_bars(symbol, timeframe="1Day", limit=limit)
    if "symbol" in df.columns:
        df = df.drop(columns=["symbol"])
    use_sig = strategy is SignalStrategy
    if use_sig:
        df = indicators.generate_signals(df)
    df = df.rename(columns={"open": "Open", "high": "High", "low": "Low",
                            "close": "Close", "volume": "Volume"})
    df = df.set_index("timestamp")
    feed = (SignalData if use_sig else bt.feeds.PandasData)(dataname=df)
    c = bt.Cerebro()
    c.adddata(feed)
    c.addstrategy(strategy)
    c.broker.setcash(100000)
    c.broker.setcommission(commission=0.001)
    c.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    c.addanalyzer(bt.analyzers.SharpeRatio, _name="sh", **sharpe_cfg)
    c.addanalyzer(bt.analyzers.TimeReturn, _name="tr", timeframe=bt.TimeFrame.Days)
    s = c.run()[0]
    ta = s.analyzers.trades.get_analysis()
    ntrades = ta.get("total", {}).get("total", 0)
    sh = s.analyzers.sh.get_analysis().get("sharperatio")
    # Manual annualized Sharpe from daily TimeReturn
    rets = pd.Series(s.analyzers.tr.get_analysis())
    manual = (rets.mean() / rets.std()) * (252 ** 0.5) if rets.std() > 0 else 0.0
    return ntrades, sh, manual


for strat in (SignalStrategy, SMACrossover):
    print(f"\n--- {strat.__name__} ---")
    for cfg in (
        {"riskfreerate": 0.04},
        {"riskfreerate": 0.04, "annualize": True},
        {"riskfreerate": 0.04, "annualize": True, "timeframe": bt.TimeFrame.Years},
    ):
        n, sh, man = run("AAPL", strat, **cfg)
        print(f"  cfg={cfg}")
        print(f"     trades={n}  analyzer_sharpe={sh}  manual_annual_sharpe={man:.3f}")
