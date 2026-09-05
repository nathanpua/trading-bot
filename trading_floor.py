#!/usr/bin/env python3
"""
Multi-Agent Trading Floor — collaborative AI decision system.

ARCHITECTURE
============
Five specialized analyst agents run in PARALLEL, each examining a different
facet of the market. A Desk Chief (also GLM-5.3-Flash) reads all briefings
and produces the final trade plan.

    ┌─────────────────────────────────────────────────────────┐
    │                  SHARED CONTEXT POOL                     │
    │  (portfolio, technicals, news, macro, memory, journal)   │
    └──────┬───────┬───────┬───────┬───────┬──────────────────┘
           │       │       │       │       │
      ┌────▼──┐ ┌─▼───┐ ┌─▼───┐ ┌─▼───┐ ┌─▼─────┐
      │MACRO  │ │NEWS │ │TECH │ │RISK │ │MEMORY │   ← 5 parallel
      │ANALYST│ │ANAL │ │ANAL │ │ANAL │ │ANALYST│     GLM calls
      └────┬──┘ └─┬───┘ └─┬───┘ └─┬───┘ └─┬─────┘
           │       │       │       │       │
           └───────┴───┬───┴───────┴───────┘
                       │
                 ┌─────▼─────┐
                 │ DESK CHIEF│  ← synthesizes → trade plan
                 └─────┬─────┘
                       │
                 ┌─────▼─────┐
                 │RISK GOV   │  ← kill-switch, sizing, limits
                 └─────┬─────┘
                       │
                 ┌─────▼─────┐
                 │  EXECUTE  │  → Alpaca orders
                 └───────────┘

USAGE
=====
    from trading_floor import TradingFloor
    floor = TradingFloor()
    result = floor.run_cycle(dry_run=True)    # full multi-agent cycle
    result = floor.run_cycle(dry_run=False)   # live execution

    # CLI:
    python trading_floor.py                       # dry run
    python trading_floor.py --execute             # live
    python trading_floor.py --briefings-only      # show analyst briefings only
"""
import os
import sys
import json
import time
import logging
import traceback
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import yaml
from ai_agent import glm_chat, build_market_context, _safe_call, GLM_MODEL
import alpaca_client as ac
import risk_manager as rm
import finnhub_client as fc
import lse_client as lse

# ═══════════════════════════════════════════════════════════════
#  ANALYST AGENT BASE
# ═══════════════════════════════════════════════════════════════

class AnalystAgent:
    """Base class for a specialized analyst agent.

    Each agent:
    1. Receives the shared market context
    2. Asks GLM-5.3-Flash to analyze its specific domain
    3. Returns a structured briefing (dict with assessment + signals)
    """

    def __init__(self, name, role, system_prompt, model=GLM_MODEL, temperature=0.2):
        self.name = name
        self.role = role
        self.system_prompt = system_prompt
        self.model = model
        self.temperature = temperature

    def analyze(self, context):
        """Run this agent's analysis. Returns briefing dict."""
        prompt = self._build_prompt(context)
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": prompt},
        ]
        try:
            raw = glm_chat(messages, model=self.model, temperature=self.temperature,
                          max_tokens=None, timeout=180)
            return self._parse(raw, context)
        except Exception as e:
            logger.warning("Agent %s failed: %s", self.name, e)
            return {
                "agent": self.name,
                "status": "error",
                "error": str(e)[:100],
                "assessment": f"[{self.name} unavailable: {str(e)[:60]}]",
                "signals": [],
                "confidence": "low",
            }

    def _build_prompt(self, context):
        """Build the agent-specific prompt from context. Override in subclass."""
        raise NotImplementedError

    def _parse(self, raw, context):
        """Parse LLM response into structured briefing."""
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        try:
            briefing = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1:
                try:
                    briefing = json.loads(text[start:end+1])
                except json.JSONDecodeError:
                    briefing = {"assessment": text[:500], "signals": [], "confidence": "low"}
            else:
                briefing = {"assessment": text[:500], "signals": [], "confidence": "low"}

        briefing["agent"] = self.name
        briefing["role"] = self.role
        briefing["status"] = "ok"
        return briefing


# ═══════════════════════════════════════════════════════════════
#  SPECIALIZED ANALYST AGENTS
# ═══════════════════════════════════════════════════════════════

MACRO_SYSTEM = """You are a Macro Analyst on a trading desk. Your job: assess the overall market environment.

Focus on:
- VIX/volatility regime (RISK-ON / NEUTRAL / RISK-OFF)
- SPY/QQQ trend health and broad market breadth
- Sector rotation signals (which sectors are leading/lagging)
- Interest rate environment (TLT/bonds), Dollar (DXY), Commodities (Gold/Oil)
- Geopolitical macro risks from news headlines

Output STRICT JSON only:
{
  "regime": "RISK-ON | NEUTRAL | RISK-OFF",
  "risk_multiplier": 0.0-1.0,
  "assessment": "2-3 sentence macro read",
  "sector_bias": ["sectors to favor"],
  "sector_avoid": ["sectors to avoid"],
  "key_risks": ["specific macro risks"],
  "confidence": "high | medium | low"
}"""

NEWS_SYSTEM = """You are a News Analyst on a trading desk. Your job: identify market-moving headlines.

Focus on:
- Earnings reports, guidance changes, analyst upgrades/downgrades
- M&A, product launches, regulatory actions
- Geopolitical events affecting specific stocks or sectors
- Fed policy signals, economic data surprises

For each actionable item, provide a signal (bullish/bearish/neutral) and which symbols it affects.

Output STRICT JSON only:
{
  "market_sentiment": "bullish | bearish | neutral",
  "assessment": "2-3 sentence news read",
  "actionable": [
    {
      "headline": "headline text",
      "symbols": ["AAPL", "MSFT"],
      "signal": "bullish | bearish | neutral",
      "impact": "high | medium | low",
      "thesis": "why this matters"
    }
  ],
  "earnings_catalysts": ["symbols with earnings within 1 week"],
  "confidence": "high | medium | low"
}"""

TECHNICAL_SYSTEM = """You are a Technical Analyst on a trading desk. Your job: read the charts.

Focus on:
- Trend structure: is price above/below key SMAs (20, 50)?
- Momentum: RSI overbought/oversold, MACD bullish/bearish, ADX trend strength
- Volatility: Bollinger Band position, ATR levels
- Volume confirmation: OBV trend
- For positions: are trailing stops or signal-flip exits at risk?

For each symbol, give a clear technical verdict and signal.

Output STRICT JSON only:
{
  "assessment": "2-3 sentence overall technical read",
  "positions": [
    {
      "symbol": "MU",
      "verdict": "bullish | bearish | neutral",
      "rsi_status": "overbought | oversold | neutral",
      "macd_status": "bullish | bearish | neutral",
      "trend": "uptrend | downtrend | sideways",
      "action": "HOLD | EXIT | TRIM",
      "note": "1 sentence technical reasoning"
    }
  ],
  "candidates": [
    {
      "symbol": "NVDA",
      "verdict": "bullish | bearish | neutral",
      "entry_quality": "strong | moderate | weak",
      "note": "1 sentence on chart setup quality"
    }
  ],
  "confidence": "high | medium | low"
}"""

RISK_SYSTEM = """You are a Risk Manager on a trading desk. Your job: assess risk objectively.

You are managing a PAPER TRADING account. The purpose is to LEARN and make profitable trades, not to hoard cash. An under-deployed portfolio that never trades is also a failure mode.

Focus on:
- Position concentration: NEW entries are capped at 25% of portfolio. But EXISTING positions that drift above 25% due to price appreciation are WINNERS, not breaches. Do NOT recommend trimming a position just because it went from 25% to 26%. Only flag concentration as a risk if a single position exceeds 32% of portfolio (the trim threshold).
- The distinction: buying 30% of portfolio in one name = risky (breaches entry cap). A 25% position growing to 27% because the stock went up = good. Trimming winners creates churn and destroys returns.
- Cash buffer (below 10% is genuinely dangerous; below 20% is fine for a paper account)
- Correlation risk (multiple positions in the same sector)
- Daily loss tracking and drawdown from high-water
- Kill-switch proximity

Assess risk factually. Do NOT default to "defensive" when the portfolio is healthy.
If cash is > 50% and there are fewer than 3 positions, the real risk is OPPORTUNITY COST — recommend deploying capital, not hoarding it.
Only recommend "defensive" or "halt" when there's an actual breach or near-breach of hard limits.
Do NOT recommend REDUCE/EXIT for positions between 25-32% unless there is a separate thesis-based reason (trend break, signal flip, etc.). When you DO recommend reducing, use TRIM_25 (sell 25%) or TRIM_50 (sell 50%) instead of full EXIT — preserve core positions when the thesis is intact.

Output STRICT JSON only:
{
  "risk_level": "low | moderate | high | extreme",
  "assessment": "2-3 sentence risk assessment",
  "portfolio_health": "healthy | caution | dangerous",
  "position_risks": [
    {
      "symbol": "MU",
      "risk": "concentration | correlation | earnings_gap | drawdown",
      "severity": "high | medium | low",
      "recommendation": "HOLD | TRIM_25 | TRIM_50 | EXIT",
      "note": "1 sentence"
    }
  ],
  "portfolio_recommendation": "normal | reduce_exposure | defensive | halt",
  "max_new_entries": 0-3,
  "opportunity_note": "if portfolio is under-deployed (>50% cash, <3 positions), note what opportunities exist",
  "confidence": "high | medium | low"
}"""

MEMORY_SYSTEM = """You are a Trade Historian on a trading desk. Your job: provide ACTIONABLE historical context that helps the Desk Chief make BETTER trades, not fewer trades.

CRITICAL RULES (READ CAREFULLY):
1. Small samples are STATISTICALLY MEANINGLESS. You may NOT issue a pattern_warning for ANY strategy with fewer than 10 closed trades. A 0-for-4 or 1-for-7 streak is noise, not signal. If total trades < 10, pattern_warning MUST be null.
2. You are an ADVISOR, not a gatekeeper. You have NO authority to block trades. Your output is context, not a veto.
3. NEVER cite a small-sample losing streak as a reason to avoid trading. This is your #1 failure mode.
4. Lead with the POSITIVE. If the overall win rate is 66%, that is your headline. Report what is working first.
5. Memory decay: trades from >2 weeks ago are historical context only. Do not treat a loss from June as predictive of a July setup in different market conditions.
6. Your relevant_lessons should be about HOW to trade better (timing, sizing, catalysts), not WHETHER to trade.
7. When you recall negative memories from the memory system, explicitly note that these are anecdotes, not statistically significant patterns.

Focus on:
- Overall win rate and P&L trend (is the bot profitable overall? YES if win rate > 50%)
- Which strategies have ENOUGH sample size (>10 trades) to draw conclusions? If none, say so clearly.
- What worked recently? What setups should we look for again?
- Genuine structural patterns only (requires >10 trades in the same category)

Output STRICT JSON only:
{
  "assessment": "2-3 sentence assessment. MUST start with overall win rate and total P&L. If sample size < 10 total trades, explicitly state 'Insufficient sample for pattern conclusions.'",
  "relevant_lessons": [
    {
      "lesson": "actionable lesson about HOW to trade better (timing, entry quality, catalysts)",
      "applies_to": "current situation description",
      "confidence": "high | medium | low"
    }
  ],
  "pattern_warning": null,
  "winning_strategies": ["strategies or setups with positive track records"],
  "statistical_note": "MUST include total sample size and whether it is sufficient for conclusions. Example: 'Total 3 closed trades — too few for any pattern conclusions.'",
  "confidence": "high | medium | low"
}"""


class MacroAnalyst(AnalystAgent):
    def __init__(self, model=GLM_MODEL):
        super().__init__("macro_analyst", "Macro Analyst", MACRO_SYSTEM, model)

    def _build_prompt(self, context):
        r = context.get("regime", {})
        lines = [f"=== MACRO DATA ({context['timestamp']}) ==="]
        lines.append(f"Current regime assessment: {r.get('regime', 'N/A')}")
        lines.append(f"Regime reasons: {'; '.join(r.get('reasons', ['N/A']))}")
        lines.append(f"VIX proxy: {r.get('vix_proxy', 'N/A')}")
        lines.append(f"SPY trend: {r.get('spy_trend', 'N/A')}")

        # Regime proxies
        lines.append("\nREGIME PROXY QUOTES:")
        acct = context.get("account", {})
        for sym, info in self._get_proxy_quotes().items():
            lines.append(f"  {sym}: ${info['price']:.2f} ({info['change_pct']:+.2f}%)")

        # Market news for macro context
        news = context.get("news", {})
        if news.get("market"):
            lines.append("\nTOP MARKET HEADLINES:")
            for n in news["market"][:8]:
                lines.append(f"  [{n.get('source', '')}] {n.get('headline', '')}")

        lines.append("\nGive your macro assessment in JSON format.")
        return "\n".join(lines)

    def _get_proxy_quotes(self):
        proxies = {}
        for sym in ("SPY", "QQQ", "TLT", "GLD", "XLE", "XLF", "SMH", "IWM", "EEM", "ARKK"):
            try:
                q = lse.get_quote(sym)
                c = float(q.get("c") or 0)
                if c > 0:
                    proxies[sym] = {"price": c, "change_pct": round(float(q.get("dp") or 0), 2)}
            except Exception:
                continue
        return proxies


class NewsAnalyst(AnalystAgent):
    def __init__(self, model=GLM_MODEL):
        super().__init__("news_analyst", "News Analyst", NEWS_SYSTEM, model)

    def _build_prompt(self, context):
        lines = [f"=== NEWS DATA ({context['timestamp']}) ==="]

        # Market news
        news = context.get("news", {})
        if news.get("market"):
            lines.append("MARKET HEADLINES:")
            for n in news["market"][:15]:
                lines.append(f"  [{n.get('source', '')}] {n.get('headline', '')}")
                summary = n.get("summary", "")
                if summary:
                    lines.append(f"    → {summary[:140]}")

        # Company news for held positions + candidates
        for sym, articles in news.get("company", {}).items():
            lines.append(f"\n{sym} COMPANY NEWS:")
            for a in articles[:5]:
                lines.append(f"  [{a.get('source', '')}] {a.get('headline', '')}")

        # Current positions (for earnings catalyst context)
        held = [p["symbol"] for p in context.get("positions", [])]
        if held:
            lines.append(f"\nCURRENTLY HELD: {', '.join(held)}")

        # Earnings proximity
        for p in context.get("positions", []):
            if p.get("earnings_in_days") is not None:
                lines.append(f"  {p['symbol']}: earnings in {p['earnings_in_days']} days")

        lines.append("\nAnalyze the news for actionable signals. JSON format.")
        return "\n".join(lines)


class TechnicalAnalyst(AnalystAgent):
    def __init__(self, model=GLM_MODEL):
        super().__init__("technical_analyst", "Technical Analyst", TECHNICAL_SYSTEM, model)

    def _build_prompt(self, context):
        lines = [f"=== TECHNICAL DATA ({context['timestamp']}) ==="]

        # Positions
        lines.append("OPEN POSITIONS:")
        for p in context.get("positions", []):
            t = p.get("technicals", {})
            lines.append(
                f"  {p['symbol']} entry=${p['entry']:.2f} cur=${p['current']:.2f} "
                f"P&L={p['unrealized_plpc']:+.1f}% RSI={t.get('rsi', '?')} "
                f"MACD={t.get('macd_diff', '?')} ADX={t.get('adx', '?')} "
                f"ATR={t.get('atr', '?')} trend={t.get('trend', '?')} "
                f"buy/sell={t.get('buy_score', '?')}/{t.get('sell_score', '?')}"
            )

        # Scanner candidates
        lines.append("\nSCANNER CANDIDATES:")
        for c in context.get("candidates", []):
            lines.append(
                f"  {c['symbol']} ${c['price']:.2f} path={c['path']} "
                f"score={c['buy_score']}/5 ADX={c['adx']:.0f} RSI={c['rsi']:.0f}"
            )

        if not context.get("candidates"):
            lines.append("  (none qualified)")

        lines.append("\nGive technical verdicts for each position and candidate. JSON format.")
        return "\n".join(lines)


class RiskAnalyst(AnalystAgent):
    def __init__(self, model=GLM_MODEL):
        super().__init__("risk_analyst", "Risk Manager", RISK_SYSTEM, model)

    def _build_prompt(self, context):
        a = context.get("account", {})
        exp = context.get("exposure", {})
        risk_cfg = self._get_risk_config()

        lines = [f"=== RISK DATA ({context['timestamp']}) ==="]
        lines.append(f"Equity: ${a.get('equity', 0):,.0f}")
        lines.append(f"Cash: ${a.get('cash', 0):,.0f} ({exp.get('cash_pct', 0):.1f}%)")
        lines.append(f"Deployed: ${exp.get('total', 0):,.0f} ({exp.get('pct_of_portfolio', 0):.1f}%)")
        max_pos = risk_cfg.get('max_positions')
        pos_cap = str(max_pos) if max_pos is not None else "unlimited"
        lines.append(f"Positions: {exp.get('position_count', 0)}/{pos_cap}")
        lines.append(f"Day P&L: {a.get('day_pl_pct', 0):+.1f}%")
        lines.append(f"Risk limits: max_risk/trade={risk_cfg.get('max_risk_per_trade', 0.02)*100:.0f}% "
                      f"max_concentration(entry)={risk_cfg.get('max_concentration', 0.25)*100:.0f}% "
                      f"concentration_trim={risk_cfg.get('concentration_trim_threshold', 0.32)*100:.0f}% "
                      f"max_daily_loss={risk_cfg.get('max_daily_loss', 0.02)*100:.0f}% "
                      f"max_drawdown={risk_cfg.get('max_drawdown', 0.08)*100:.0f}%")

        lines.append("\nPOSITION DETAILS (positions 25-32% are WINNERS running, not breaches):")
        for p in context.get("positions", []):
            earn = f" EARNINGS={p['earnings_in_days']}d" if p.get("earnings_in_days") else ""
            pct = p['position_pct']
            tag = ""
            if pct > risk_cfg.get("concentration_trim_threshold", 0.32) * 100:
                tag = " ⚠ OVER_TRIM_THRESHOLD"
            elif pct > risk_cfg.get("max_concentration", 0.25) * 100:
                tag = " (winner running above entry cap — OK)"
            lines.append(
                f"  {p['symbol']} {pct:.1f}% of portfolio "
                f"P&L={p['unrealized_plpc']:+.1f}%{tag}{earn}"
            )

        # Kill-switch state
        ks = self._check_kill_switch_state()
        if ks:
            lines.append(f"\nKILL-SWITCH: {ks}")

        lines.append("\nAssess portfolio risk. JSON format.")
        return "\n".join(lines)

    def _get_risk_config(self):
        cfg_path = HERE / "config.yaml"
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f)
        return cfg.get("risk", {})

    def _check_kill_switch_state(self):
        try:
            from autonomous_engine import load_state
            state = load_state()
            if state.get("halted_until") and state.get("halt_reason"):
                return f"HALTED — {state['halt_reason']}"
            hw = state.get("high_water")
            dd = None
            if hw:
                acct = ac.get_account()
                eq = float(acct["equity"])
                dd = (eq - hw) / hw * 100
                return f"Drawdown from high-water: {dd:+.1f}%"
        except Exception:
            pass
        return None


class MemoryAnalyst(AnalystAgent):
    def __init__(self, model=GLM_MODEL):
        super().__init__("memory_analyst", "Trade Historian", MEMORY_SYSTEM, model)

    def _build_prompt(self, context):
        lines = [f"=== HISTORICAL DATA ({context['timestamp']}) ==="]

        # Journal stats
        journal = context.get("journal", {})
        overall = journal.get("overall")
        if overall:
            lines.append(f"JOURNAL: {overall['trades']} trades | Win rate: {overall['win_rate']}% | "
                        f"Total P&L: ${overall['total_pnl']:,.2f}")
            for s in journal.get("by_strategy", []):
                lines.append(f"  {s['strategy']:15} {s['trades']} trades | {s['win_rate']}% win | ${s['total_pnl']:,.2f}")
        else:
            lines.append("JOURNAL: No closed trades yet")

        # Recent lessons
        lessons = journal.get("recent_lessons", [])
        if lessons:
            lines.append("\nJOURNAL LESSONS:")
            for l in lessons[:5]:
                lines.append(f"  [{l['category']}|{l['confidence']}] {l['lesson']}")

        # Memory recall
        mem = context.get("memory", {})
        if mem.get("status") not in ("disconnected", "error"):
            if mem.get("recent"):
                lines.append("\nMEMORY RECALL (recent findings):")
                for m in mem["recent"][:5]:
                    lines.append(f"  · {m}")
            if mem.get("lessons"):
                lines.append("\nMEMORY LESSONS:")
                for m in mem["lessons"]:
                    lines.append(f"  · {m}")
            for sym, memories in mem.get("positions", {}).items():
                if memories:
                    lines.append(f"\n{sym} MEMORY:")
                    for m in memories:
                        lines.append(f"  · {m}")
        else:
            lines.append(f"\nMEMORY: {mem.get('status', 'unavailable')}")

        # Current positions for context
        held = [p["symbol"] for p in context.get("positions", [])]
        if held:
            lines.append(f"\nCURRENTLY HELD: {', '.join(held)}")

        lines.append("\nApply historical lessons to current situation. JSON format.")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
#  DESK CHIEF — THE ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════

DESK_CHIEF_SYSTEM = """You are the Desk Chief of a trading floor managing a paper-trading portfolio.

Five specialist analysts have given you their briefings:
1. MACRO ANALYST — overall market regime, sector rotation
2. NEWS ANALYST — actionable headlines, earnings catalysts
3. TECHNICAL ANALYST — chart analysis on positions + candidates
4. RISK MANAGER — portfolio risk assessment, position-level warnings
5. TRADE HISTORIAN — lessons from past trades, pattern warnings

Your job: synthesize ALL five briefings into a single, decisive trade plan.

DECISION RULES:
- You are running a PAPER TRADING account designed to LEARN and profit. Deploy capital when the evidence supports it — but a cycle that ends in HOLD with cash is acceptable when the candidate list is genuinely weak. Forced entries into marginal setups are ALSO a failure mode (live record: avg win +$28 vs avg loss −$53 — forced low-quality entries lose more than they make).
- If Risk Manager says "halt", do NOT add new positions. But "normal" or "low" risk means TRADE when setups are good.
- If Risk Manager notes opportunity cost (high cash, few positions), find the BEST candidate rather than the first — one strong position beats three marginal ones.
- Weight the Risk Manager highest on SIZING and HARD LIMITS. BUT: concentration rules use a TIERED system — new BUYs are capped at 25% of portfolio at entry, but EXISTING positions are only trimmed above 32% (the trim threshold). A position at 26-31% is a WINNER RUNNING, not a breach. Do NOT sell or trim positions in the 25-32% band purely for concentration compliance — that creates churn and destroys returns. Only trim above 32%.
- CRITICAL POSITION SIZING: Use size_pct to scale entries to conviction. A high-conviction trade uses 0.25 (25% of portfolio — the max). A medium-conviction exploratory position uses 0.10-0.15. A low-conviction toe-in-the-water uses 0.05. Do NOT default every BUY to 25% — vary your sizing.
- CRITICAL EXIT SIZING: When trimming a position, use qty_pct to specify what fraction to sell. Use 0.25-0.33 for a partial trim (take some profits, keep the core). Use 0.50 for a significant reduction. Only omit qty_pct (defaults to 100% = full exit) when you want to CLOSE the entire position. NEVER sell 100% of a position solely because it crossed 25% concentration — that is the #1 churn pattern.
- Weight the Technical Analyst highest on entry/exit timing.
- Weight the News Analyst highest on catalyst-driven moves.
- Weight the Multi-Strategy Alpha Analysis as a systematic VETO: the governor REJECTS BUYs whose composite score is below -0.15. Do not propose them — when the alpha zoo is bearish on a symbol, entering is fighting your own systematic layer.
- Trade Historian provides context ONLY, never a veto. Their pattern_warning MUST be ignored unless they cite >10 closed trades in the specific category. If they say "0-for-4" or "insufficient sample", you are FREE TO TRADE.
- ACT ON MAJORITY CONVICTION: if 2+ analysts lean bullish on a setup, take the trade even if not unanimous. Perfect consensus rarely exists. A 2-out-of-5 bullish vote with a good candidate IS a trade.
- CHURN DISCIPLINE (the governor ENFORCES these — do not fight them):
  * TRIMs of PROFITABLE positions held fewer than 3 trading days are REJECTED. Loss-cutting and full exits always pass.
  * New entries on Fridays are auto-half-sized by the executor.
  * Universe groups share one exposure budget (35% per group, e.g. all gold names combined).
  * Most cycles should end with 0-2 actions. If your plan keeps flipping in and out of the same names, you are churning — HOLD instead and let bracket stops/targets work.
- Maximum 3 new BUYs per cycle. Prefer quality over quantity, but DO trade when setups are good.

MANDATORY JUSTIFICATION RULE (replaces forced action):
- If you take NO position-changing action while candidates exist AND the portfolio has >50% cash AND fewer than 3 positions AND Risk Manager says risk is "low" or "moderate":
  Your summary must explain, with specific per-candidate analysis, why EVERY candidate fails on technical, fundamental, AND news criteria simultaneously. A blanket "weak entry quality" without specific analysis is not sufficient.

USER PREFERENCES (CRITICAL):
- The user PREFERS to hold through earnings when profitable. Do NOT suggest flattening before earnings as a blanket rule.
- Bot's historical losses came from selling at intraday lows (signal-flip exits too aggressive). Be cautious about exit recommendations at local lows.
- Prefer fewer, higher-conviction trades over many marginal ones. But "fewer" means 1-2, not ZERO.

Output STRICT JSON only — no markdown, no explanation outside JSON:
{
  "analysis": {
    "market_read": "2-3 sentence synthesis of all analyst views",
    "portfolio_assessment": "2-3 sentence assessment of current positions",
    "key_consensus": "what most analysts agree on",
    "key_disagreement": "where analysts disagree, if any",
    "risk_outlook": "overall risk outlook for this cycle"
  },
  "actions": [
    {
      "action": "BUY|SELL|TRIM|CLOSE|HOLD",
      "symbol": "AAPL",
      "thesis": "comprehensive rationale citing which analysts support this",
      "conviction": "high|medium|low",
      "size_pct": 0.25,
      "supporting_analysts": ["macro", "technical", "news"]
    },
    {
      "action": "TRIM",
      "symbol": "XLE",
      "thesis": "taking partial profits, uptrend intact",
      "qty_pct": 0.25,
      "conviction": "medium",
      "supporting_analysts": ["technical", "risk"]
    }
  ],
  "summary": "1-2 sentence strategy for this cycle",
  "confidence": "high|medium|low"
}

FIELD REFERENCE:
- action: BUY (new entry), TRIM (partial sell — MUST include qty_pct), SELL (full exit), CLOSE (force close via Alpaca API), HOLD
- size_pct (BUY only): fraction of portfolio for this position. 0.25=max conviction, 0.15=medium, 0.05=exploratory. Omitting defaults to risk-based sizing which historically maxes at 25%.
- qty_pct (TRIM/SELL): fraction of the HELD position to sell. 0.25=trim a quarter, 0.50=halve it. OMITTING qty_pct means full exit (100%). Use TRIM+qty_pct for partial profit-taking.
- risk_pct: optional risk budget override (default 0.02 = 2%), clamped to max 2%."""


class DeskChief:
    """The orchestrator: collects briefings, synthesizes final trade plan."""

    def __init__(self, model=GLM_MODEL):
        self.model = model
        self.system_prompt = DESK_CHIEF_SYSTEM

    def decide(self, context, briefings):
        """Synthesize all analyst briefings into a final trade plan."""
        prompt = self._build_prompt(context, briefings)
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": prompt},
        ]
        raw = glm_chat(messages, model=self.model, temperature=0.2,
                       timeout=240)

        plan = self._parse(raw)
        plan["raw_response"] = raw
        return plan

    def _build_prompt(self, context, briefings):
        lines = [f"=== DESK CHIEF SYNTHESIS ({context['timestamp']}) ==="]

        # Portfolio snapshot
        a = context.get("account", {})
        exp = context.get("exposure", {})
        lines.append(f"PORTFOLIO: ${a.get('equity', 0):,.0f} | Cash: ${a.get('cash', 0):,.0f} ({exp.get('cash_pct', 0):.0f}%)")
        lines.append(f"Deployed: ${exp.get('total', 0):,.0f} ({exp.get('pct_of_portfolio', 0):.1f}%) | Positions: {exp.get('position_count', 0)}")
        if context.get("positions"):
            held = [f"{p['symbol']}({p['unrealized_plpc']:+.1f}%)" for p in context["positions"]]
            lines.append(f"HOLDINGS: {', '.join(held)}")
        lines.append(f"Market open: {context.get('market_open', False)}")

        # Candidate list (for desk chief to know what's available)
        if context.get("candidates"):
            cand_text = ", ".join(f"{c['symbol']}({c['path']}, {c['buy_score']}/5)" for c in context["candidates"][:8])
            lines.append(f"SCANNER CANDIDATES: {cand_text}")

        # Multi-strategy alpha analysis
        strat_scan = context.get("strategy_scan", {})
        if strat_scan.get("status") == "ok" and strat_scan.get("assessments"):
            lines.append("\nMULTI-STRATEGY ALPHA ANALYSIS:")
            for a in strat_scan["assessments"]:
                if a.get("error"):
                    lines.append(f"  {a['symbol']:5} [ERROR: {a['error'][:40]}]")
                    continue
                sym = a["symbol"]
                score = a["composite_score"]
                signal = a["composite_signal"]
                bull = a.get("bullish_strategies", 0)
                bear = a.get("bearish_strategies", 0)
                total = a.get("total_strategies", 0)
                lines.append(f"  {sym:5} composite={score:+.2f} ({signal}) "
                             f"bull={bull}/{total} bear={bear}/{total}")
                for ts in a.get("top_signals", []):
                    lines.append(f"        {ts['strategy']:25} {ts['score']:+.2f} {ts['signal']}")

        # Analyst briefings
        lines.append("\n" + "="*60)
        lines.append("ANALYST BRIEFINGS")
        lines.append("="*60)

        briefing_order = ["macro_analyst", "news_analyst", "technical_analyst",
                         "risk_analyst", "memory_analyst"]
        role_names = {
            "macro_analyst": "MACRO ANALYST",
            "news_analyst": "NEWS ANALYST",
            "technical_analyst": "TECHNICAL ANALYST",
            "risk_analyst": "RISK MANAGER",
            "memory_analyst": "TRADE HISTORIAN",
        }

        for agent_key in briefing_order:
            b = briefings.get(agent_key, {})
            role = role_names.get(agent_key, agent_key)
            lines.append(f"\n--- {role} ---")
            if b.get("status") == "error":
                lines.append(f"  [UNAVAILABLE: {b.get('error', 'unknown')}]")
                continue
            # Dump the briefing as readable JSON
            clean = {k: v for k, v in b.items()
                    if k not in ("raw_response", "status")}
            lines.append(json.dumps(clean, indent=2))

        lines.append("\n" + "="*60)
        lines.append("Synthesize all briefings into a final trade plan. JSON format only.")
        lines.append("="*60)

        return "\n".join(lines)

    def _parse(self, raw):
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        try:
            plan = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1:
                try:
                    plan = json.loads(text[start:end+1])
                except json.JSONDecodeError:
                    plan = {"parse_error": True, "raw": raw[:500], "actions": [], "summary": "Parse error"}
            else:
                plan = {"parse_error": True, "raw": raw[:500], "actions": [], "summary": "Parse error"}
        return plan


# ═══════════════════════════════════════════════════════════════
#  TRADING FLOOR — THE FULL SYSTEM
# ═══════════════════════════════════════════════════════════════

class TradingFloor:
    """Multi-agent trading floor: 5 analysts → Desk Chief → Risk Governor → Execute."""

    def __init__(self, model=GLM_MODEL):
        self.model = model
        self.agents = [
            MacroAnalyst(model),
            NewsAnalyst(model),
            TechnicalAnalyst(model),
            RiskAnalyst(model),
            MemoryAnalyst(model),
        ]
        self.chief = DeskChief(model)
        self.cfg = self._load_config()

    def _load_config(self):
        with open(HERE / "config.yaml") as f:
            return yaml.safe_load(f)

    def run_cycle(self, dry_run=True):
        """Full trading floor cycle.

        Steps:
        1. Build shared context (market data, news, memory, journal)
        2. Run all 5 analyst agents IN PARALLEL
        3. Desk Chief synthesizes briefings → final trade plan
        4. Risk governor validates plan
        5. Execute (or dry-run)
        6. Log everything
        """
        ts_start = time.time()
        timestamp = datetime.now(timezone.utc).isoformat()

        # 1. Build shared context
        logger.info("Building market context...")
        context = build_market_context(self.cfg)

        # 2. Run analysts in parallel
        logger.info("Dispatching %d analyst agents in parallel...", len(self.agents))
        briefings = self._run_analysts_parallel(context)
        logger.info("All analysts complete. Briefings: %s",
                    {k: v.get("status", "?") for k, v in briefings.items()})

        # 3. Desk Chief synthesizes
        logger.info("Desk Chief synthesizing trade plan...")
        try:
            plan = self.chief.decide(context, briefings)
        except Exception as e:
            logger.error("Desk Chief failed: %s", e)
            return {
                "status": "error",
                "error": f"Desk Chief synthesis failed: {e}",
                "briefings": briefings,
                "timestamp": timestamp,
            }

        # 4. Risk governor validates (composite veto, min-hold, kill-switch)
        from ai_agent import AITradingAgent
        governor = AITradingAgent()
        valid_actions, rejections = governor.validate_plan(
            plan, strategy_scan=context.get("strategy_scan"))

        # 5. Execute
        execution = self._execute(valid_actions, dry_run)

        # 5b. Record trades to journal DB (for dashboard stats)
        self._record_to_journal(context, plan, execution, dry_run)

        # 6. Build report + log
        report = self._build_report(context, briefings, plan, execution, timestamp)
        elapsed = time.time() - ts_start

        self._log_cycle(context, briefings, plan, execution, report, timestamp, elapsed)

        return {
            "status": "ok",
            "context": context,
            "briefings": briefings,
            "plan": plan,
            "execution": execution,
            "report": report,
            "elapsed_seconds": round(elapsed, 1),
            "timestamp": timestamp,
        }

    def _run_analysts_parallel(self, context):
        """Run all analyst agents concurrently using ThreadPoolExecutor."""
        briefings = {}
        with ThreadPoolExecutor(max_workers=len(self.agents)) as pool:
            futures = {pool.submit(agent.analyze, context): agent.name
                      for agent in self.agents}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    briefings[name] = future.result()
                except Exception as e:
                    logger.warning("Agent %s raised: %s", name, e)
                    briefings[name] = {
                        "agent": name, "status": "error",
                        "error": str(e)[:100],
                        "assessment": f"[{name} failed]",
                        "signals": [], "confidence": "low",
                    }
        return briefings

    def _execute(self, valid_actions, dry_run):
        """Execute validated actions via the risk-governed executor."""
        if not valid_actions:
            return {"executed": False, "dry_run": dry_run,
                    "results": [], "rejections": ["No valid actions"]}

        try:
            from scripts.trading_floor_execute import execute_plan
            results = execute_plan(valid_actions, self.cfg, dry_run=dry_run)
            return {"executed": not dry_run, "dry_run": dry_run,
                    "results": results}
        except Exception as e:
            logger.error("Execution failed: %s", e)
            return {"executed": False, "dry_run": dry_run,
                    "results": [{"status": "error", "error": str(e)}]}

    def _record_to_journal(self, context, plan, execution, dry_run):
        """Record executed trades and cycle summary to the journal DB.

        This populates the dashboard's Trades and Analysis tabs.
        """
        try:
            import trade_journal as tj
            tj.init_db()
        except Exception as e:
            logger.warning("Journal init failed: %s", e)
            return

        regime = context.get("regime", {}).get("regime", "neutral")
        acct = context.get("account", {})
        exp = context.get("exposure", {})

        # Record cycle summary
        try:
            import trade_journal as tj
            tj.record_cycle(
                session="ai_floor",
                regime=regime,
                equity=acct.get("equity", 0),
                cash_pct=exp.get("cash_pct", 0),
                deployed_pct=exp.get("pct_of_portfolio", 0),
                position_count=exp.get("position_count", 0),
                actions=plan.get("actions", []),
                report=plan.get("summary", ""),
            )
        except Exception as e:
            logger.warning("Journal cycle record failed: %s", e)

        # Persist the Trade Historian's lessons to the journal DB so they feed
        # back into future cycles (previously the lessons table stayed empty).
        try:
            mem_brief = briefings.get("memory_analyst", {}) or {}
            recent = {l.get("lesson") for l in tj.get_stats().get("recent_lessons", [])}
            for l in (mem_brief.get("relevant_lessons") or [])[:5]:
                text = (l.get("lesson") or "").strip()
                if not text or text in recent:
                    continue
                tj.add_lesson("memory", text[:500],
                              evidence=(l.get("applies_to") or "")[:300],
                              confidence=l.get("confidence", "medium"))
        except Exception as e:
            logger.warning("Lesson persistence failed (non-fatal): %s", e)

        # Register cycle-executed BUYs for journal reconciliation (with regime
        # context the executor doesn't have). reconcile_journal() below records
        # them at REAL fill prices. ALL closes (SELL/CLOSE/TRIM/bracket legs)
        # are likewise applied by reconcile from actual fills — single writer,
        # no double-counting, real prices.
        results = execution.get("results", [])
        for r in results:
            status = r.get("status", "")
            act = r.get("action", "").upper()
            sym = r.get("symbol", "")

            # Only actual submissions (not dry runs or skips)
            if status not in ("submitted", "executed"):
                continue
            if not sym or act != "BUY":
                continue
            oid = r.get("order_id")
            if not oid:
                continue

            try:
                import trade_journal as tj
                tj.record_pending(oid, "buy", {
                    "thesis": r.get("thesis", plan.get("summary", "")),
                    "strategy": "ai_multi_agent",
                    "regime": regime,
                    "stop_price": r.get("stop"),
                    "target_price": r.get("target"),
                    "position_pct": r.get("pos_pct"),
                    "risk_pct": r.get("risk_pct"),
                })
            except Exception as e:
                logger.warning("Pending buy registration failed for %s: %s", sym, e)

        # Reconcile journal against broker fills — applies every filled sell
        # (TRIMs, stop-outs, take-profit legs, manual exits) FIFO against open
        # lots at real fill prices, and backfills any missing buys. Idempotent
        # via broker_order_id + applied_sells markers; self-healing next cycle.
        try:
            rec = tj.reconcile_journal()
            if rec.get("buys_added") or rec.get("sells_applied"):
                logger.info("Journal reconciled with broker: %s", rec)
        except Exception as e:
            logger.warning("Journal reconcile failed (non-fatal): %s", e)

        # Store balanced context to supermemory (not just losses)
        self._store_cycle_memory(context, plan, execution)

    def _store_cycle_memory(self, context, plan, execution):
        """Store a balanced cycle summary to supermemory.

        This ensures positive outcomes (profitable trades, good entries)
        are stored alongside losses, preventing recall bias.
        """
        try:
            from trade_memory import TradeMemory
            tm = TradeMemory()
            if not tm.connected:
                return

            ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
            acct = context.get("account", {})
            equity = acct.get("equity", 0)
            day_pl = acct.get("day_pl_pct", 0)
            positions = context.get("positions", [])
            regime = context.get("regime", {}).get("regime", "?")

            # Build a balanced summary
            actions = plan.get("actions", [])
            action_summary = "; ".join(
                f"{a.get('action','?')} {a.get('symbol','')}" for a in actions
            ) or "no actions"

            # Store positive context when we have winning positions
            winners = [p for p in positions if p.get("unrealized_plpc", 0) > 0]
            losers = [p for p in positions if p.get("unrealized_plpc", 0) < 0]

            parts = [
                f"CYCLE {ts}: equity=${equity:,.0f} day_pl={day_pl:+.1f}% regime={regime}",
                f"actions: {action_summary}",
            ]

            if winners:
                win_text = ", ".join(f"{p['symbol']}({p['unrealized_plpc']:+.1f}%)" for p in winners)
                parts.append(f"WINNERS: {win_text}")

            if losers:
                loss_text = ", ".join(f"{p['symbol']}({p['unrealized_plpc']:+.1f}%)" for p in losers)
                parts.append(f"LOSERS: {loss_text}")

            summary = plan.get("summary", "")
            if summary:
                parts.append(f"strategy: {summary}")

            content = " | ".join(parts)
            tm.store_finding(content, {
                "type": "cycle_summary",
                "equity": equity,
                "day_pl_pct": day_pl,
                "regime": regime,
                "winners": len(winners),
                "losers": len(losers),
            })

            # Store winning trade outcomes explicitly
            for w in winners:
                sym = w["symbol"]
                pnl = w["unrealized_plpc"]
                tm.store_finding(
                    f"WINNING POSITION {sym} at {pnl:+.1f}% ({ts}) — entry thesis working",
                    {"type": "winning_trade", "symbol": sym, "pnl_pct": pnl}
                )

        except Exception as e:
            logger.debug("Memory store failed: %s", e)

    def _build_report(self, context, briefings, plan, execution, timestamp):
        """Build a comprehensive trading floor report."""
        r = []
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        r.append(f"{'='*65}")
        r.append(f" MULTI-AGENT TRADING FLOOR — {stamp}")
        r.append(f" 5 Analysts → Desk Chief → Risk Governor → Execute")
        r.append(f"{'='*65}\n")

        # Portfolio snapshot
        a = context.get("account", {})
        exp = context.get("exposure", {})
        r.append(f"PORTFOLIO: ${a.get('equity', 0):,.0f} | Cash: ${a.get('cash', 0):,.0f} ({exp.get('cash_pct', 0):.0f}%)")
        r.append(f"Deployed: ${exp.get('total', 0):,.0f} ({exp.get('pct_of_portfolio', 0):.1f}%) | "
                 f"Positions: {exp.get('position_count', 0)}")
        if context.get("positions"):
            held = [f"{p['symbol']}({p['unrealized_plpc']:+.1f}%)" for p in context["positions"]]
            r.append(f"HOLDINGS: {', '.join(held)}")
        r.append("")

        # Analyst briefings summary
        r.append("─"*65)
        r.append(" ANALYST BRIEFINGS")
        r.append("─"*65)

        briefing_order = [
            ("macro_analyst", "MACRO", "regime"),
            ("news_analyst", "NEWS", "market_sentiment"),
            ("technical_analyst", "TECH", "confidence"),
            ("risk_analyst", "RISK", "risk_level"),
            ("memory_analyst", "MEMORY", "confidence"),
        ]

        for key, label, metric in briefing_order:
            b = briefings.get(key, {})
            status = b.get("status", "?")
            if status == "error":
                r.append(f"  [{label:6}] ⚠ UNAVAILABLE — {b.get('error', '')}")
                continue
            val = b.get(metric, "")
            assessment = b.get("assessment", "N/A")
            confidence = b.get("confidence", "?")
            r.append(f"  [{label:6}] {metric}={str(val).upper():8} conf={confidence:6}")
            r.append(f"           {assessment}")

            # Domain-specific highlights
            if key == "macro_analyst":
                mult = b.get("risk_multiplier", "")
                if mult != "":
                    r.append(f"           risk_mult={mult} | avoid: {', '.join(b.get('sector_avoid', []))}")
            elif key == "news_analyst":
                catalysts = b.get("earnings_catalysts", [])
                if catalysts:
                    r.append(f"           earnings catalysts: {', '.join(catalysts)}")
                actionable = b.get("actionable", [])
                high_impact = [a for a in actionable if a.get("impact") == "high"]
                if high_impact:
                    r.append(f"           high-impact: {high_impact[0].get('headline', '')[:80]}")
            elif key == "technical_analyst":
                for pos in b.get("positions", []):
                    r.append(f"           {pos.get('symbol',''):5} → {pos.get('action','?').upper()} ({pos.get('verdict','?')}) {pos.get('note','')}")
            elif key == "risk_analyst":
                r.append(f"           health={b.get('portfolio_health','?')} | "
                         f"recommendation={b.get('portfolio_recommendation','?')} | "
                         f"max_new={b.get('max_new_entries','?')}")
                for pr in b.get("position_risks", []):
                    r.append(f"           ⚠ {pr.get('symbol',''):5} {pr.get('risk','?')} "
                             f"severity={pr.get('severity','?')} → {pr.get('recommendation','?').upper()}")
            elif key == "memory_analyst":
                warning = b.get("pattern_warning")
                if warning and warning != "null":
                    r.append(f"           ⚠ PATTERN WARNING: {str(warning)[:80]}")
                for l in b.get("relevant_lessons", [])[:2]:
                    r.append(f"           lesson: {l.get('lesson','')[:80]}")

        r.append("")

        # Desk Chief synthesis
        r.append("─"*65)
        r.append(" DESK CHIEF DECISION")
        r.append("─"*65)
        analysis = plan.get("analysis", {})
        if analysis:
            r.append(f"Market read: {analysis.get('market_read', 'N/A')}")
            r.append(f"Risk outlook: {analysis.get('risk_outlook', 'N/A')}")
            consensus = analysis.get("key_consensus", "")
            if consensus:
                r.append(f"Consensus: {consensus}")
            disagreement = analysis.get("key_disagreement", "")
            if disagreement and disagreement != "none":
                r.append(f"Disagreement: {disagreement}")
            r.append("")

        # Actions
        actions = plan.get("actions", [])
        r.append(f"ACTIONS ({len(actions)}):")
        for a in actions:
            act = a.get("action", "?").upper()
            sym = a.get("symbol", "")
            thesis = a.get("thesis", "")
            conv = a.get("conviction", "?")
            supporters = a.get("supporting_analysts", [])
            tag = {"BUY": "▸", "SELL": "✗", "CLOSE": "✗", "HOLD": "○"}.get(act, "?")
            sup = f" ← {', '.join(supporters)}" if supporters else ""
            r.append(f"  {tag} {act:5} {sym:6} [{conv}]{sup}")
            if thesis:
                r.append(f"           {thesis}")
        r.append("")

        # Execution
        results = execution.get("results", [])
        if results:
            r.append(f"EXECUTION ({'LIVE' if execution.get('executed') else 'DRY RUN'}):")
            for res in results:
                status = res.get("status", "?")
                sym = res.get("symbol", "")
                act = res.get("action", "")
                if status in ("submitted", "executed"):
                    r.append(f"  ✓ {act} {sym}: {status}")
                    if "qty" in res:
                        r.append(f"    {res['qty']:.0f}sh @ ${res.get('entry', 0):.2f}")
                elif status == "dry_run":
                    r.append(f"  ⊙ {act} {sym}: would execute")
                elif status == "skipped":
                    r.append(f"  ⊘ {act} {sym}: {res.get('reason', 'skipped')}")
                elif status == "ok":
                    pass  # HOLD
                elif status == "error":
                    r.append(f"  ✗ {act} {sym}: ERROR — {res.get('error', '?')}")
        rejs = execution.get("rejections", [])
        if rejs:
            r.append(f"\nREJECTED: {'; '.join(rejs)}")
        r.append("")

        # Summary
        summary = plan.get("summary", "")
        if summary:
            r.append(f"STRATEGY: {summary}")
        overall_conf = plan.get("confidence", "?")
        r.append(f"CONFIDENCE: {overall_conf}")

        return "\n".join(r)

    def _log_cycle(self, context, briefings, plan, execution, report, timestamp, elapsed):
        """Persist the full trading floor cycle to disk."""
        log_dir = HERE / "reports" / "trading_floor"
        log_dir.mkdir(parents=True, exist_ok=True)

        ts = time.strftime("%Y%m%d_%H%M%S")
        log_path = log_dir / f"cycle_{ts}.json"
        latest_path = log_dir / "latest.json"

        record = {
            "ts": timestamp,
            "elapsed_seconds": elapsed,
            "model": self.model,
            "agents": [a.name for a in self.agents],
            "context_summary": {
                "equity": context.get("account", {}).get("equity", 0),
                "positions": len(context.get("positions", [])),
                "candidates": len(context.get("candidates", [])),
                "regime": context.get("regime", {}).get("regime", "?"),
            },
            "briefings": {k: {kk: vv for kk, vv in v.items() if kk != "raw_response"}
                         for k, v in briefings.items()},
            "desk_chief_plan": {k: v for k, v in plan.items() if k != "raw_response"},
            "execution": execution,
            "report": report,
        }

        with open(log_path, "w") as f:
            json.dump(record, f, indent=2, default=str)
        with open(latest_path, "w") as f:
            json.dump(record, f, indent=2, default=str)

        logger.info("Trading floor cycle logged to %s (%.1fs)", log_path, elapsed)


# ═══════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

    ap = argparse.ArgumentParser(description="Multi-Agent Trading Floor")
    ap.add_argument("--execute", action="store_true",
                    help="LIVE submit orders (default: dry run)")
    ap.add_argument("--briefings-only", action="store_true",
                    help="Run analysts + show briefings, skip Desk Chief synthesis")
    ap.add_argument("--model", default=GLM_MODEL,
                    help=f"Model to use (default: {GLM_MODEL})")
    args = ap.parse_args()

    floor = TradingFloor(model=args.model)

    if args.briefings_only:
        logger.info("Briefings-only mode: running analysts without Desk Chief")
        context = build_market_context(floor.cfg)
        briefings = floor._run_analysts_parallel(context)

        print(f"\n{'='*65}")
        print(f" ANALYST BRIEFINGS ONLY — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        print(f"{'='*65}\n")

        for key in ["macro_analyst", "news_analyst", "technical_analyst",
                     "risk_analyst", "memory_analyst"]:
            b = briefings.get(key, {})
            label = key.replace("_", " ").upper()
            print(f"\n--- {label} ---")
            clean = {k: v for k, v in b.items() if k not in ("raw_response", "status")}
            print(json.dumps(clean, indent=2))
    else:
        result = floor.run_cycle(dry_run=not args.execute)
        print(result.get("report", "No report generated"))
        if result.get("status") == "error":
            print(f"\nERROR: {result.get('error')}")
        else:
            print(f"\n⏱ Total cycle time: {result.get('elapsed_seconds', 0):.1f}s")
