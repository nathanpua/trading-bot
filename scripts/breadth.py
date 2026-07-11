import pandas as pd, pathlib
D = pathlib.Path('data')
sectors = {'XLK':'Tech','XLY':'Discr','XLP':'Staples','XLE':'Energy','XLF':'Fin','XLV':'Health','XLI':'Indust','XLB':'Mat','XLU':'Util','XLRE':'REIT','XLC':'Comm'}
above=below=[]
res=[]
for t,n in sectors.items():
    f=D/f'{t}.csv'
    if not f.exists(): continue
    df=pd.read_csv(f)
    for c in ['Close','close','Adj Close']:
        if c in df.columns: px=df[c]; break
    last=float(px.iloc[-1]); sma20=float(px.iloc[-20:].mean())
    vs=(last/sma20-1)*100
    res.append((n,last,vs,'ABOVE' if vs>=0 else 'BELOW'))
a=sum(1 for r in res if r[3]=='ABOVE'); b=sum(1 for r in res if r[3]=='BELOW')
print("=== S&P SECTOR BREADTH vs 20-SMA ===")
for n,last,vs,st in sorted(res,key=lambda x:x[2]):
    print(f"{n:<8}{last:>8.2f}{vs:>8.2f}%  {st}")
print(f"\nABOVE 20-SMA: {a}  |  BELOW: {b}  |  net breadth: {a-b:+d}  (broad: >+5, narrow risk-off: <0)")
# leadership check
print("\n=== MARKET LEADERSHIP vs 20-SMA ===")
for t in ['SMH','SOXX','NVDA','AVGO','MU','MSFT','META','AMZN','TSLA','XBI']:
    f=D/f'{t}.csv'
    if not f.exists(): continue
    df=pd.read_csv(f)
    for c in ['Close','close','Adj Close']:
        if c in df.columns: px=df[c]; break
    last=float(px.iloc[-1]); sma20=float(px.iloc[-20:].mean())
    vs=(last/sma20-1)*100
    print(f"{t:<6}{last:>9.2f}{vs:>8.2f}%  {'ABOVE' if vs>=0 else 'BELOW'}")
