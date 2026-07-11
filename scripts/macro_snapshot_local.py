import pandas as pd, pathlib
D = pathlib.Path('data')
# Use close col fallback
def load(t):
    f = D/f'{t}.csv'
    if not f.exists(): return None
    df = pd.read_csv(f)
    # find close-like col
    for c in ['Close','close','adjClose','Adj Close']:
        if c in df.columns:
            px = df[c]; break
    else:
        px = df.iloc[:,4] if df.shape[1]>=5 else df.iloc[:,-1]
    # timestamp
    tcol = df.columns[0]
    try:
        df['_d'] = pd.to_datetime(df[tcol])
    except: 
        df['_d'] = df[tcol]
    s = pd.Series(px.values, index=df['_d'])
    return s.astype(float)

tlist = ['SPY','QQQ','IWM','DIA','VIXY','VXX','UVXY','TLT','IEF','HYG','LQD','AGG',
         'UUP','USO','GLD','XLK','XLF','XLE','XLI','XLY','XLP','XLV','XLU','XLB','XLRE','XLC','VNQ',
         'SMH','SOXX','NVDA','AVGO','MU','AMD','META','MSFT','AAPL','TSLA','AMZN','KWEB','XBI','ARKK']
print(f"{'Tk':<7}{'Price':>9}{'1d%':>8}{'5d%':>8}{'20d%':>8}{'50d%':>8}{'SMA20':>9}{'vsSMA20':>9}{'LastDate':>12}")
print('-'*78)
for t in tlist:
    try:
        s = load(t)
        if s is None or len(s)<50:
            print(f"{t:<7} (no data)"); continue
        s = s.dropna()
        last = float(s.iloc[-1])
        sma20 = float(s.iloc[-20:].mean())
        d1 = (last/float(s.iloc[-2])-1)*100 if len(s)>=2 else float('nan')
        d5 = (last/float(s.iloc[-6])-1)*100 if len(s)>=6 else float('nan')
        d20= (last/float(s.iloc[-21])-1)*100 if len(s)>=21 else float('nan')
        d50= (last/float(s.iloc[-51])-1)*100 if len(s)>=51 else float('nan')
        vs = (last/sma20-1)*100
        dt = str(s.index[-1])[:10]
        print(f"{t:<7}{last:>9.2f}{d1:>8.2f}{d5:>8.2f}{d20:>8.2f}{d50:>8.2f}{sma20:>9.2f}{vs:>8.2f}%{dt:>12}")
    except Exception as e:
        print(f"{t:<7} ERR {repr(e)[:40]}")
