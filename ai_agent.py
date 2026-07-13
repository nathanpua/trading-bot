#!/usr/bin/env python3
"""
AI Decision Agent — GLM 5.2-powered trading intelligence layer.

This module wraps the deterministic trading engine with an LLM "desk chief"
that reviews the full market context (technicals, news, portfolio state,
trade memory, journal stats) and produces a structured trade plan.

Architecture:
    Market Data → Context Builder → GLM 5.2 (decision) → Risk Governor → Execute

The AI is ADVISORY on WHAT to trade (entries, exits, holds).
The risk_manager is AUTHORITATIVE on HOW MUCH (sizing, stops, limits).
The kill-switch overrides everything.

Usage:
    from ai_agent import AITradingAgent
    agent = AITradingAgent()
    plan = agent.decide()           # full context → trade plan
    agent.execute(plan)             # risk-gate + submit (dry_run by default)
"""
import os
import sys
import json
import time
import logging
import requests
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import yaml
import alpaca_client as ac
import indicators as ind
import risk_manager as rm
import finnhub_client as fc

# ───────────────────────── GLM API Client ─────────────────────────

def _load_glm_config():
    """Load GLM API credentials from .env or environment."""
    key = os.environ.get("GLM_API_KEY") or os.environ.get("ZAI_API_KEY")
    base_url = os.environ.get("GLM_BASE_URL", "https://api.z.ai/api/coding/paas/v4")

    if not key:
        env_path = HERE / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line.startswith("GLM_API_KEY=") and not line.startswith("#"):
                    key = line.split("=", 1)[1].strip().strip("'\"")
                elif line.startswith("ZAI_API_KEY=") and not line.startswith("#"):
                    if not key:
                        key = line.split("=", 1)[1].strip().strip("'\"")
                elif line.startswith("GLM_BASE_URL=") and not line.startswith("#"):
                    base_url = line.split("=", 1)[1].strip().strip("'\"")

    # Also check Hermes .env
    if not key:
        hermes_env = Path.home() / ".hermes" / ".env"
        if hermes_env.exists():
            for line in hermes_env.read_text().splitlines():
                line = line.strip()
                if line.startswith("GLM_API_KEY=") and not line.startswith("#"):
                    key = line.split("=", 1)[1].strip().strip("'\"")

    return key, base_url


def glm_chat(messages, model="glm-4.7", temperature=0.3, max_tokens=4096, timeout=180):
    """Call the GLM (Z.AI) chat completions API.

    Returns the assistant message content string.
    Falls back gracefully on errors.
    """
    key, base_url = _load_glm_config()
    if not key:
        raise RuntimeError("GLM_API_KEY not found in environment or .env files")

    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


# ───────────────────────── Context Builder ─────────────────────────

def _safe_call(fn, *args, **kwargs):
    """Call fn, return None on error."""
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        logger.debug("safe_call error: %s", e)
        return None


def build_market_context(cfg):
    """Gather all market data the AI needs to make decisions.

    Returns a structured dict with:
    - portfolio state (account, positions with technicals)
    - regime assessment (VIX, SPY trend)
    - scanner results (ranked entry candidates)
    - recent news headlines (market + per-position)
    - trade memory recall (from supermemory)
    - journal stats (win rates, recent lessons)
    """
    ctx = {"timestamp": datetime.now(timezone.utc).isoformat()}

    # 1. Account + positions
    acct = _safe_call(ac.get_account) or {}
    positions_raw = _safe_call(ac.get_positions) or []
    clock = _safe_call(ac.is_market_open) or {}

    ctx["market_open"] = clock.get("is_open", False)
    ctx["account"] = {
        "equity": float(acct.get("equity", 0)),
        "cash": float(acct.get("cash", 0)),
        "portfolio_value": float(acct.get("portfolio_value", 0)),
        "buying_power": float(acct.get("buying_power", 0)),
        "day_pl_pct": round(float(acct.get("day_plpc", 0)) * 100, 2),
    }

    # 2. Positions with technicals
    positions = []
    held_symbols = set()
    for p in positions_raw:
        sym = p["symbol"]
        held_symbols.add(sym)
        pos = {
            "symbol": sym,
            "qty": float(p["qty"]),
            "entry": float(p["avg_entry_price"]),
            "current": float(p["current_price"]),
            "market_value": float(p["market_value"]),
            "unrealized_pl": float(p["unrealized_pl"]),
            "unrealized_plpc": round(float(p["unrealized_plpc"]) * 100, 2),
            "position_pct": round(float(p["market_value"]) / float(acct.get("portfolio_value", 1)) * 100, 2),
        }
        # Add technicals
        tech = _get_technicals(sym)
        if tech:
            pos["technicals"] = tech
        # Check earnings catalyst
        days_to_earnings = _check_earnings(sym, cfg)
        if days_to_earnings is not None:
            pos["earnings_in_days"] = days_to_earnings
        positions.append(pos)
    ctx["positions"] = positions

    # 3. Exposure
    total_exposure = sum(p["market_value"] for p in positions)
    pv = ctx["account"]["portfolio_value"]
    ctx["exposure"] = {
        "total": round(total_exposure, 2),
        "pct_of_portfolio": round(total_exposure / pv * 100, 1) if pv else 0,
        "position_count": len(positions),
        "cash_pct": round(float(acct.get("cash", 0)) / pv * 100, 1) if pv else 0,
    }

    # 4. Regime assessment
    ctx["regime"] = _assess_regime(cfg)

    # 5. Scanner — entry candidates (deterministic pre-filter)
    ctx["candidates"] = _scan_candidates(cfg, held_symbols)

    # 6. News — market headlines + per-position company news
    ctx["news"] = _gather_news(held_symbols, [c["symbol"] for c in ctx["candidates"][:3]])

    # 7. Trade memory recall
    ctx["memory"] = _recall_memory(held_symbols)

    # 8. Journal stats
    ctx["journal"] = _get_journal_stats()

    return ctx


def _get_technicals(symbol):
    """Get latest technical indicators for a symbol."""
    try:
        df = ind.add_all_indicators(ac.get_bars(symbol, "1Day", 120))
        df = ind.generate_signals(df)
        if df is None or df.empty:
            return None
        last = df.iloc[-1]
        return {
            "rsi": round(float(last.get("rsi", 0)), 1),
            "macd_diff": round(float(last.get("macd_diff", 0)), 3),
            "adx": round(float(last.get("adx", 0)), 1),
            "atr": round(float(last["atr"]), 2),
            "sma_20": round(float(last["sma_20"]), 2),
            "sma_50": round(float(last["sma_50"]), 2),
            "price": round(float(last["close"]), 2),
            "buy_score": int(last.get("buy_score", 0)),
            "sell_score": int(last.get("sell_score", 0)),
            "trend": "uptrend" if float(last["close"]) > float(last["sma_50"]) else "downtrend",
            "bb_position": ("above_upper" if float(last["close"]) > float(last["bb_high"])
                            else "below_lower" if float(last["close"]) < float(last["bb_low"])
                            else "mid"),
        }
    except Exception as e:
        logger.debug("Technicals failed for %s: %s", symbol, e)
        return None


def _check_earnings(symbol, cfg, days=5):
    """Check if earnings are within N days for a symbol."""
    try:
        from autonomous_engine import _check_earnings_within_days
        return _check_earnings_within_days(symbol, days)
    except Exception:
        return None


def _assess_regime(cfg):
    """Quick regime assessment: VIX proxy + SPY trend."""
    reasons = []
    vix = None
    for sym in ("VIX", "VIXY", "UVXY"):
        try:
            q = fc.get_quote(sym)
            c = float(q.get("c") or 0)
            if c > 0:
                vix = c / 2 if sym == "UVXY" else c
                reasons.append(f"{sym}={c:.0f}")
                break
        except Exception:
            continue

    spy_trend = None
    try:
        spy_df = ind.add_all_indicators(ac.get_bars("SPY", "1Day", 70))
        spy_close = float(spy_df.iloc[-1]["close"])
        spy_sma = float(spy_df.iloc[-1]["sma_50"])
        spy_trend = "bullish" if spy_close > spy_sma else "bearish"
        reasons.append(f"SPY {spy_close:.0f} {'>' if spy_close > spy_sma else '<'} SMA50 {spy_sma:.0f}")
    except Exception:
        pass

    rcfg = cfg.get("regime", {})
    if vix is not None:
        if vix >= rcfg.get("vix_risk_off_threshold", 25):
            regime_label = "RISK-OFF"
        elif vix >= rcfg.get("vix_risk_on_threshold", 18):
            regime_label = "NEUTRAL"
        else:
            regime_label = "RISK-ON"
    else:
        regime_label = "NEUTRAL"

    return {
        "regime": regime_label,
        "vix_proxy": vix,
        "spy_trend": spy_trend,
        "reasons": reasons,
    }


def _scan_candidates(cfg, held_symbols):
    """Run the deterministic scanner to pre-filter entry candidates."""
    try:
        from autonomous_engine import scan_entries
        regime = {"risk_multiplier": 1.0}
        candidates = scan_entries(cfg, regime, held_symbols)
        # Cap to top 8 for the AI context window
        return candidates[:8]
    except Exception as e:
        logger.debug("Scanner failed: %s", e)
        return []


def _gather_news(held_symbols, candidate_symbols, max_headlines=20):
    """Gather market news + relevant company news."""
    news = {"market": [], "company": {}}

    # Market headlines
    try:
        raw = fc.get_market_news(category="general", count=max_headlines)
        news["market"] = [
            {"headline": a.get("headline", ""),
             "source": a.get("source", ""),
             "summary": (a.get("summary", "") or "")[:200],
             "related": a.get("related", "")}
            for a in raw[:max_headlines]
        ]
    except Exception:
        pass

    # Company news for held positions + top candidates
    all_syms = list(held_symbols) + candidate_symbols
    for sym in all_syms[:5]:  # cap to avoid rate limits
        try:
            raw = fc.get_company_news(sym, days=5, count=5)
            if raw:
                news["company"][sym] = [
                    {"headline": a.get("headline", ""), "source": a.get("source", "")}
                    for a in raw[:5]
                ]
        except Exception:
            continue
        time.sleep(0.1)

    return news


def _recall_memory(held_symbols):
    """Recall trade memory context from supermemory."""
    try:
        from trade_memory import TradeMemory
        tm = TradeMemory()
        if not tm.connected:
            return {"status": "disconnected"}

        memory = {"recent": [], "positions": {}, "lessons": []}
        recent = tm.recall("recent market analysis and trades", limit=5)
        memory["recent"] = [r["memory"][:150] for r in recent]

        for sym in held_symbols:
            results = tm.recall(f"{sym} thesis earnings catalyst", limit=2)
            if results:
                memory["positions"][sym] = [r["memory"][:150] for r in results]

        lessons = tm.recall("trading lessons what worked what failed", limit=3)
        memory["lessons"] = [r["memory"][:150] for r in lessons]
        return memory
    except Exception as e:
        return {"status": "error", "error": str(e)[:80]}


def _get_journal_stats():
    """Get journal performance stats."""
    try:
        import trade_journal as tj
        stats = tj.get_stats()
        return {
            "overall": stats.get("overall"),
            "by_strategy": stats.get("by_strategy", []),
            "recent_lessons": stats.get("recent_lessons", [])[:5],
        }
    except Exception:
        return {}


# ───────────────────────── System Prompt ─────────────────────────

SYSTEM_PROMPT = """You are the AI Desk Chief of a quantitative trading desk managing a paper-trading portfolio on Alpaca.

## Your Role
You analyze market data, technical indicators, news, and historical trade memory to make BUY/SELL/HOLD/CLOSE decisions. You are intelligent, decisive, and risk-aware.

## Decision Framework
1. **REGIME first**: If the market regime is RISK-OFF, prefer HOLD/CLOSE over BUY. In NEUTRAL, only take high-conviction trades. In RISK-ON, normal operation.
2. **Manage existing positions before opening new ones**: Review each position's technicals vs entry thesis. Exit when thesis is invalidated.
3. **Earnings catalyst awareness**: If earnings are within 5 days, prefer HOLDING through the catalyst (user preference) unless the position is at a loss AND technicals have deteriorated.
4. **Confluence over single signals**: A buy signal is stronger when multiple indicators agree (RSI oversold + MACD positive + above SMA50).
5. **Respect risk limits**: Max 5 positions, max 25% concentration, max 2% risk per trade. The risk manager will enforce these, but factor them into your plan.
6. **Cut losses, ride winners**: If a position is losing and the thesis is broken, exit. If winning and momentum continues, hold or let the trailing stop work.

## User Preferences (IMPORTANT)
- The user PREFERS to hold through earnings when the position is profitable. Do NOT suggest flattening before earnings as a blanket rule.
- Bot's historical losses came from selling at intraday lows (signal-flip exits too aggressive), not from holding catalysts. Be cautious about recommending exits at local lows.
- Prefer fewer, higher-conviction trades over many marginal ones.

## Output Format (STRICT JSON)
Respond with ONLY a JSON object, no markdown, no explanation outside the JSON:
{
  "analysis": {
    "regime_assessment": "Your 1-2 sentence read on market conditions",
    "portfolio_review": "Your 1-2 sentence assessment of current positions",
    "key_risks": "What could go wrong with the current portfolio"
  },
  "actions": [
    {
      "action": "BUY|SELL|CLOSE|HOLD",
      "symbol": "AAPL",
      "thesis": "1-sentence rationale for this action",
      "conviction": "high|medium|low",
      "risk_pct": 0.02
    }
  ],
  "summary": "1-sentence overall strategy for this cycle"
}

Rules for actions:
- For BUY: include symbol, thesis, conviction, and risk_pct (0.01-0.02).
- For SELL/CLOSE: include symbol and thesis.
- For HOLD: action with empty or no symbol means "hold all positions, no changes."
- Maximum 3 new BUYs per cycle.
- Only BUY symbols that are in the candidates list OR that you identify from news/technicals as high-conviction (must still pass risk gates).
- If the kill-switch is tripped, only output HOLD or CLOSE actions."""


# ───────────────────────── AI Decision Agent ─────────────────────────

class AITradingAgent:
    """AI-powered trading decision agent using GLM 5.2."""

    def __init__(self, model="glm-4.7", temperature=0.3):
        self.model = model
        self.temperature = temperature
        self.cfg = self._load_config()

    def _load_config(self):
        cfg_path = HERE / "config.yaml"
        with open(cfg_path) as f:
            return yaml.safe_load(f)

    def decide(self):
        """Full AI decision cycle: gather context → ask GLM 5.2 → parse plan.

        Returns:
            dict with keys:
            - context: the market context dict (for logging)
            - raw_response: raw LLM output
            - plan: parsed JSON trade plan (or None on parse failure)
            - model: model used
            - timestamp: ISO timestamp
        """
        logger.info("Building market context for AI agent...")
        context = build_market_context(self.cfg)

        # Build the user message with all context
        user_msg = self._format_context_for_llm(context)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]

        logger.info("Querying %s for trade decisions...", self.model)
        try:
            raw = glm_chat(messages, model=self.model, temperature=self.temperature,
                          max_tokens=4096, timeout=180)
        except Exception as e:
            logger.error("GLM API call failed: %s", e)
            return {
                "context": context,
                "raw_response": None,
                "plan": None,
                "error": str(e),
                "model": self.model,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        plan = self._parse_response(raw)

        return {
            "context": context,
            "raw_response": raw,
            "plan": plan,
            "model": self.model,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _format_context_for_llm(self, ctx):
        """Format the context dict as a readable prompt for the LLM."""
        lines = []

        # Header
        lines.append(f"=== TRADING CYCLE {ctx['timestamp']} ===")
        lines.append(f"Market open: {ctx['market_open']}")

        # Account
        a = ctx["account"]
        lines.append(f"\n--- PORTFOLIO ---")
        lines.append(f"Equity: ${a['equity']:,.0f} | Cash: ${a['cash']:,.0f} ({ctx['exposure']['cash_pct']:.0f}%)")
        lines.append(f"Day P&L: {a['day_pl_pct']:+.1f}%")
        lines.append(f"Deployed: ${ctx['exposure']['total']:,.0f} ({ctx['exposure']['pct_of_portfolio']:.1f}%) | Positions: {ctx['exposure']['position_count']}")

        # Regime
        r = ctx["regime"]
        lines.append(f"\n--- REGIME: {r['regime']} ---")
        for reason in r["reasons"]:
            lines.append(f"  · {reason}")

        # Positions
        if ctx["positions"]:
            lines.append(f"\n--- POSITIONS ---")
            for p in ctx["positions"]:
                t = p.get("technicals", {})
                earn = p.get("earnings_in_days")
                earn_str = f" | EARNINGS IN {earn}d" if earn else ""
                lines.append(
                    f"  {p['symbol']:5} qty={p['qty']:.0f} entry=${p['entry']:.2f} "
                    f"cur=${p['current']:.2f} P&L={p['unrealized_plpc']:+.1f}% "
                    f"({p['position_pct']:.1f}% of portfolio){earn_str}"
                )
                if t:
                    lines.append(
                        f"        RSI={t['rsi']:.0f} MACD={t['macd_diff']:+.3f} "
                        f"ADX={t['adx']:.0f} ATR={t['atr']:.1f} "
                        f"trend={t['trend']} buy/sell={t['buy_score']}/{t['sell_score']}"
                    )
        else:
            lines.append(f"\n--- POSITIONS: none ---")

        # Scanner candidates
        if ctx["candidates"]:
            lines.append(f"\n--- SCANNER CANDIDATES (deterministic pre-filter) ---")
            for c in ctx["candidates"]:
                lines.append(
                    f"  {c['symbol']:5} ${c['price']:.2f} "
                    f"path={c['path']} score={c['buy_score']}/5 "
                    f"ADX={c['adx']:.0f} RSI={c['rsi']:.0f} ATR={c['atr']:.2f}"
                )
        else:
            lines.append(f"\n--- SCANNER CANDIDATES: none qualified ---")

        # News
        news = ctx.get("news", {})
        if news.get("market"):
            lines.append(f"\n--- MARKET NEWS (top headlines) ---")
            for n in news["market"][:10]:
                lines.append(f"  [{n['source']}] {n['headline']}")
                if n.get("summary"):
                    lines.append(f"    → {n['summary'][:120]}")

        for sym, articles in news.get("company", {}).items():
            if articles:
                lines.append(f"\n--- {sym} COMPANY NEWS ---")
                for n in articles[:3]:
                    lines.append(f"  [{n['source']}] {n['headline']}")

        # Memory
        mem = ctx.get("memory", {})
        if mem.get("status") != "disconnected" and mem.get("status") != "error":
            if mem.get("recent"):
                lines.append(f"\n--- TRADE MEMORY (recent findings) ---")
                for m in mem["recent"][:3]:
                    lines.append(f"  · {m}")
            if mem.get("lessons"):
                lines.append(f"\n--- LESSONS LEARNED ---")
                for m in mem["lessons"]:
                    lines.append(f"  · {m}")
            for sym, memories in mem.get("positions", {}).items():
                if memories:
                    lines.append(f"\n--- {sym} MEMORY ---")
                    for m in memories:
                        lines.append(f"  · {m}")

        # Journal
        journal = ctx.get("journal", {})
        overall = journal.get("overall")
        if overall:
            lines.append(f"\n--- JOURNAL STATS ---")
            lines.append(f"  Record: {overall['trades']} trades | Win rate: {overall['win_rate']}% | Total P&L: ${overall['total_pnl']:,.2f}")
            for strat in journal.get("by_strategy", [])[:3]:
                lines.append(f"  {strat['strategy']:15} {strat['trades']} trades | {strat['win_rate']}% win | ${strat['total_pnl']:,.2f}")

        lessons = journal.get("recent_lessons", [])
        if lessons:
            lines.append(f"\n--- RECENT JOURNAL LESSONS ---")
            for l in lessons[:3]:
                lines.append(f"  [{l['category']}|{l['confidence']}] {l['lesson'][:100]}")

        # Config constraints
        risk = self.cfg.get("risk", {})
        lines.append(f"\n--- RISK CONSTRAINTS ---")
        lines.append(f"  Max risk/trade: {risk.get('max_risk_per_trade', 0.02)*100:.0f}% | "
                      f"Max concentration: {risk.get('max_concentration', 0.25)*100:.0f}% | "
                      f"Max positions: {risk.get('max_positions', 5)}")

        lines.append("\n=== END CONTEXT — Make your decisions, Desk Chief ===")

        return "\n".join(lines)

    def _parse_response(self, raw):
        """Parse the LLM JSON response into a trade plan."""
        if not raw:
            return None

        # Strip markdown code fences if present
        text = raw.strip()
        if text.startswith("```"):
            # Remove ```json or ``` fences
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        # Try to find JSON object
        try:
            plan = json.loads(text)
        except json.JSONDecodeError:
            # Try extracting JSON from mixed text
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1:
                try:
                    plan = json.loads(text[start:end+1])
                except json.JSONDecodeError:
                    logger.error("Failed to parse LLM response as JSON")
                    return {"parse_error": True, "raw": raw[:500]}
            else:
                return {"parse_error": True, "raw": raw[:500]}

        return plan

    def validate_plan(self, plan):
        """Validate the AI plan against safety rules.

        Returns (valid_actions, rejections).
        """
        if not plan or plan.get("parse_error"):
            return [], ["Plan parse failed — no actions"]

        actions = plan.get("actions", [])
        if not actions:
            return [], []

        valid = []
        rejections = []
        rcfg = self.cfg["risk"]

        # Check kill-switch state
        try:
            from autonomous_engine import load_state, check_kill_switch
            state = load_state()
            acct = ac.get_account()
            equity = float(acct["equity"])
            halt, halt_reason = check_kill_switch(state, equity, self.cfg)
            if halt:
                # Allow CLOSE/SELL/HOLD but block BUY
                for a in actions:
                    act = a.get("action", "").upper()
                    if act == "BUY":
                        rejections.append(f"BUY {a.get('symbol', '?')}: blocked by kill-switch ({halt_reason})")
                    else:
                        valid.append(a)
                return valid, rejections
        except Exception as e:
            logger.warning("Kill-switch check failed (allowing): %s", e)

        # Validate each action
        positions = {p["symbol"] for p in (_safe_call(ac.get_positions) or [])}
        buy_count = sum(1 for p in _safe_call(ac.get_positions) or [] if p["symbol"])

        for a in actions:
            act = a.get("action", "").upper()
            sym = a.get("symbol", "").upper()

            if act == "HOLD":
                valid.append(a)
                continue

            if act == "BUY":
                # Max 3 new buys per cycle
                new_buys = sum(1 for v in valid if v.get("action", "").upper() == "BUY" and v.get("symbol", "").upper() not in positions)
                if new_buys >= 3:
                    rejections.append(f"BUY {sym}: max 3 new entries per cycle")
                    continue
                # Risk pct clamp
                risk_pct = a.get("risk_pct", rcfg["max_risk_per_trade"])
                a["risk_pct"] = min(float(risk_pct), rcfg["max_risk_per_trade"])
                valid.append(a)

            elif act in ("SELL", "CLOSE"):
                if sym and sym not in positions:
                    rejections.append(f"{act} {sym}: not currently held")
                    continue
                valid.append(a)

            else:
                rejections.append(f"Unknown action: {act}")

        return valid, rejections

    def execute(self, plan, dry_run=True):
        """Validate + execute the AI trade plan via risk-governed execution.

        Returns full results dict.
        """
        valid_actions, rejections = self.validate_plan(plan)

        if not valid_actions:
            logger.info("No valid actions to execute. Rejections: %s", rejections)
            return {
                "executed": False,
                "dry_run": dry_run,
                "valid_actions": [],
                "rejections": rejections,
                "results": [],
            }

        # Use the existing risk-governed executor
        try:
            from scripts.trading_floor_execute import execute_plan
            results = execute_plan(valid_actions, self.cfg, dry_run=dry_run)
        except Exception as e:
            logger.error("Execution failed: %s", e)
            results = [{"status": "error", "error": str(e)}]

        return {
            "executed": not dry_run,
            "dry_run": dry_run,
            "valid_actions": valid_actions,
            "rejections": rejections,
            "results": results,
        }

    def run_cycle(self, dry_run=True):
        """Full cycle: decide → validate → execute → report.

        This is the main entry point for cron jobs.
        """
        # 1. Decide
        decision = self.decide()

        if decision.get("error"):
            return {
                "status": "error",
                "error": decision["error"],
                "timestamp": decision["timestamp"],
            }

        plan = decision["plan"]

        # 2. Execute
        execution = self.execute(plan, dry_run=dry_run)

        # 3. Build report
        report = self._build_report(decision, execution)

        # 4. Log everything
        self._log_cycle(decision, execution, report)

        return {
            "status": "ok",
            "decision": plan,
            "execution": execution,
            "report": report,
            "timestamp": decision["timestamp"],
        }

    def _build_report(self, decision, execution):
        """Build a human-readable report of the AI cycle."""
        ctx = decision["context"]
        plan = decision["plan"] or {}
        r = []

        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        r.append(f"{'='*60}")
        r.append(f" AI TRADING CYCLE — {stamp}")
        r.append(f" Model: {decision['model']}")
        r.append(f"{'='*60}\n")

        # Analysis from AI
        analysis = plan.get("analysis", {})
        if analysis:
            r.append("AI ANALYSIS:")
            r.append(f"  Regime: {analysis.get('regime_assessment', 'N/A')}")
            r.append(f"  Portfolio: {analysis.get('portfolio_review', 'N/A')}")
            r.append(f"  Risks: {analysis.get('key_risks', 'N/A')}")
            r.append("")

        # Portfolio snapshot
        a = ctx["account"]
        r.append(f"PORTFOLIO: ${a['equity']:,.0f} | Cash: ${a['cash']:,.0f} | "
                 f"Deployed: {ctx['exposure']['pct_of_portfolio']:.1f}%")
        if ctx["positions"]:
            r.append(f"  Positions: {', '.join(p['symbol'] for p in ctx['positions'])}")
        r.append("")

        # AI actions
        actions = plan.get("actions", [])
        if actions:
            r.append(f"AI DECISIONS ({len(actions)}):")
            for a in actions:
                act = a.get("action", "?").upper()
                sym = a.get("symbol", "")
                thesis = a.get("thesis", "")
                conv = a.get("conviction", "")
                tag = {"BUY": "▸", "SELL": "✗", "CLOSE": "✗", "HOLD": "○"}.get(act, "?")
                r.append(f"  {tag} {act:5} {sym:6} [{conv}] {thesis}")
        else:
            r.append("AI DECISIONS: none")
        r.append("")

        # Execution results
        results = execution.get("results", [])
        rejections = execution.get("rejections", [])
        if results:
            r.append(f"EXECUTION ({'LIVE' if execution.get('executed') else 'DRY RUN'}):")
            for res in results:
                status = res.get("status", "?")
                sym = res.get("symbol", "")
                act = res.get("action", "")
                if status in ("submitted", "executed"):
                    r.append(f"  ✓ {act} {sym}: {status}")
                    if "qty" in res:
                        r.append(f"    {res['qty']:.0f}sh @ ${res.get('entry', 0):.2f} "
                                 f"stop=${res.get('stop', 0):.2f} tgt=${res.get('target', 0):.2f}")
                elif status == "dry_run":
                    r.append(f"  ⊙ {act} {sym}: dry-run")
                elif status == "skipped":
                    r.append(f"  ⊘ {act} {sym}: {res.get('reason', 'skipped')}")
                elif status == "error":
                    r.append(f"  ✗ {act} {sym}: ERROR — {res.get('error', '?')}")
        if rejections:
            r.append(f"\nREJECTED ({len(rejections)}):")
            for rej in rejections:
                r.append(f"  ⊘ {rej}")
        r.append("")

        # AI summary
        summary = plan.get("summary", "")
        if summary:
            r.append(f"STRATEGY: {summary}")

        return "\n".join(r)

    def _log_cycle(self, decision, execution, report):
        """Persist the full AI cycle to disk for audit trail."""
        log_dir = HERE / "reports" / "ai_cycles"
        log_dir.mkdir(parents=True, exist_ok=True)

        ts = time.strftime("%Y%m%d_%H%M%S")
        log_path = log_dir / f"cycle_{ts}.json"
        latest_path = log_dir / "latest.json"

        record = {
            "ts": decision["timestamp"],
            "model": decision["model"],
            "context_summary": {
                "equity": decision["context"]["account"]["equity"],
                "positions": len(decision["context"]["positions"]),
                "candidates": len(decision["context"]["candidates"]),
                "regime": decision["context"]["regime"]["regime"],
            },
            "plan": decision["plan"],
            "execution": {
                "executed": execution.get("executed", False),
                "rejections": execution.get("rejections", []),
                "results": execution.get("results", []),
            },
            "report": report,
            "raw_response": decision.get("raw_response", "")[:2000],
        }

        with open(log_path, "w") as f:
            json.dump(record, f, indent=2)
        with open(latest_path, "w") as f:
            json.dump(record, f, indent=2)

        logger.info("AI cycle logged to %s", log_path)


# ───────────────────────── CLI ─────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    ap = argparse.ArgumentParser(description="AI Trading Agent (GLM 5.2)")
    ap.add_argument("--execute", action="store_true",
                    help="LIVE submit orders (default: dry run)")
    ap.add_argument("--decide-only", action="store_true",
                    help="Just show the AI decision without executing")
    ap.add_argument("--model", default="glm-4.7",
                    help="Model to use (default: glm-4.7)")
    ap.add_argument("--temperature", type=float, default=0.3,
                    help="LLM temperature (default: 0.3)")
    args = ap.parse_args()

    agent = AITradingAgent(model=args.model, temperature=args.temperature)

    if args.decide_only:
        decision = agent.decide()
        print(f"\n{'='*60}")
        print(" AI DECISION (decide-only mode)")
        print(f"{'='*60}\n")
        plan = decision.get("plan")
        if plan:
            print(json.dumps(plan, indent=2))
        else:
            print(f"Error: {decision.get('error', 'unknown')}")
            if decision.get("raw_response"):
                print(f"\nRaw response:\n{decision['raw_response'][:1000]}")
    else:
        result = agent.run_cycle(dry_run=not args.execute)
        print(result.get("report", "No report generated"))
        if result.get("status") == "error":
            print(f"\nERROR: {result['error']}")
