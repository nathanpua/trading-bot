#!/usr/bin/env python3
"""Seed supermemory with analyst findings from week of 2026-06-22."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trade_memory import TradeMemory

tm = TradeMemory()
print(f"Connected: {tm.connected}")
if not tm.connected:
    print("Cannot seed — supermemory not connected")
    sys.exit(1)

findings = [
    ("Fed Chair Warsh held rates at 3.50-3.75% on 6/17. Dot plot hawkish: 9/18 officials project 2026 rates above current. Median forecast 3.8% implies a potential HIKE. Market pricing 60.7% chance of October hike. Structural headwind for growth/tech stocks.",
     {"type": "macro", "category": "fed_policy"}),
    ("Inflation ACCELERATING: PCE went from 2.9% Jan to 3.8% Apr 2026. CPI May 4.2% YoY. May PCE drops Thu 6/25 — biggest macro risk of the week. Hot print (>4.0%) = 1-2% QQQ selloff expected.",
     {"type": "macro", "category": "inflation"}),
    ("Iran ceasefire signed ~6/17. Oil crashed to 3-month lows. Strait of Hormuz reopened. Phase 2 negotiations underway but described as more difficult. De-risking tailwind for equities.",
     {"type": "macro", "category": "geopolitics"}),
    ("Memory supercycle: DRAM prices up 60% in 2025, expected +30-40% more in 2026. HBM taking 23-25% of wafer production, squeezing conventional DRAM. HBM demand +70% YoY from AI workloads. This is structural, not cyclical.",
     {"type": "sector", "category": "memory"}),
    ("MRVL surged 32.5% on June 2 after Nvidia CEO highlighted MRVL AI infrastructure role. Custom silicon revenue doubling. Announced 102.4 Tbps Teralynx T100 switch for AI data centers. Multiple analyst PT increases.",
     {"type": "sector", "symbol": "MRVL", "category": "ai_infra"}),
    ("MU earnings Wed 6/24 AMC: Consensus EPS $19.72, most-accurate estimate $20.87 (ESP +5.81%). Revenue est $34.8B (+274% YoY). Company guide: rev $35.5B, EPS $19.15. Trailing 4Q avg beat 21.7%. Forward P/E 11.75x vs industry 18.34x. Q4 guidance is the key re-rating variable.",
     {"type": "catalyst", "symbol": "MU", "category": "earnings"}),
    ("Wed 6/24 MU earnings AMC then Thu 6/25 PCE = DANGER ZONE. If MU beats but PCE is hot, gains wiped out. Keep 10-15% cash dry powder for Thursday dip-buying.",
     {"type": "risk", "category": "calendar"}),
    ("MRVL: ADX 41.6 = strongest trending stock in 45-symbol universe. MACD +0.635, RSI 64.6, clean uptrend above SMA50. Highest-conviction long.",
     {"type": "technical", "symbol": "MRVL"}),
    ("MU: uptrend, MACD +0.745, ADX 29.7, but StochK 94.8 (stretched). Strong thesis but extended short-term. Half size pre-earnings.",
     {"type": "technical", "symbol": "MU"}),
    ("WDC: confirmed SELL signal (3/5) — RSI 78, overbought. Avoid longs.",
     {"type": "technical", "symbol": "WDC"}),
    ("Market regime as of 6/21: VIXY 21.91 (falling, low fear), SPY bullish above SMA50, QQQ MACD negative (divergence), tape stretched (~15 names RSI 70+). Regime = NEUTRAL. Position sizing at 50% multiplier.",
     {"type": "regime", "date": "2026-06-21"}),
]

stored = 0
for content, meta in findings:
    r = tm.store_finding(content, meta)
    if r.get("stored"):
        stored += 1
        print(f"  + {meta.get('type','?'):12} {content[:60]}...")
    else:
        print(f"  x {meta.get('type','?'):12} FAILED: {r}")

print(f"\nStored {stored}/{len(findings)} findings to supermemory")
