import yfinance as yf
import warnings
warnings.filterwarnings('ignore')

tickers = {
    'SPY':  'S&P 500 ETF',
    'QQQ':  'Nasdaq 100',
    'VIXY': 'Short VIX futures',
    'TLT':  '20+yr Treasuries',
    'HYG':  'High Yield Corp Bonds',
    'DXY=F':'US Dollar Index',
    'CL=F': 'WTI Crude Oil',
    'GLD':  'Gold',
    'NVDA': 'Nvidia',
    'AVGO': 'Broadcom',
    'MU':   'Micron',
    'SMH':  'Semis ETF',
    'XLF':  'Financials',
    'XLK':  'Tech',
    'XLE':  'Energy',
    'IWM':  'Russell 2000',
    '^VIX': 'VIX Index',
    '^TNX': '10Y Yield',
}

print(f"{'Ticker':<8}{'Price':>10}{'Day%':>8}{'5d%':>8}{'20d%':>8}{'SMA20':>10}{'vsSMA20':>10}")
print('-'*64)
for t,name in tickers.items():
    try:
        df = yf.download(t, period='3mo', interval='1d', progress=False, auto_adjust=False)
        if df.empty or len(df)<25:
            print(f"{t:<8} NO DATA")
            continue
        px = df['Close']
        last = float(px.iloc[-1])
        sma20 = float(px.iloc[-20:].mean())
        day = float(((px.iloc[-1]/px.iloc[-2])-1)*100)
        d5  = float(((px.iloc[-1]/px.iloc[-6])-1)*100)
        d20 = float(((px.iloc[-1]/px.iloc[-21])-1)*100)
        vs = (last/sma20-1)*100
        print(f"{t:<8}{last:>10.2f}{day:>8.2f}{d5:>8.2f}{d20:>8.2f}{sma20:>10.2f}{vs:>9.2f}%")
    except Exception as e:
        print(f"{t:<8} ERR {repr(e)[:50]}")
