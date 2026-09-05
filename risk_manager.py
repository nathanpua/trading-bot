"""
Risk management module — position sizing, stop-loss/take-profit calculation,
and portfolio risk rules.

Core principles:
- Never risk more than max_risk_pct of portfolio per trade (default 2%)
- Position size = (Portfolio × risk%) / (entry - stop_loss)
- Unlimited concurrent positions by default (max_positions=None);
  capital is bounded by per-trade risk %, concentration caps, and exposure
- Sector concentration limits
"""

import math


def calculate_position_size(portfolio_value, entry_price, stop_loss_price,
                            max_risk_pct=0.02, max_position_pct=0.25,
                            size_pct=None):
    """
    Calculate position size based on risk percentage.

    Args:
        portfolio_value: total portfolio value in dollars
        entry_price: planned entry price
        stop_loss_price: stop-loss price
        max_risk_pct: max % of portfolio to risk per trade (default 2%)
        max_position_pct: max % of portfolio for a single position (default 25%).
            A tight stop (low ATR relative to price) can make the risk-based
            share count huge — e.g. QQQ at ATR 15.8 / price 740 wants 84 shares
            = 62% concentration. The cap prevents that over-concentration. When
            it binds, actual risk per trade drops below max_risk_pct (safer).
        size_pct: target position size as fraction of portfolio (e.g. 0.10 = 10%).
            When provided, this is the DESIRED size — the AI saying "I want a
            10% position" instead of always maxing out at 25%. Clamped to
            max_position_pct so it can never exceed the hard cap. When None,
            falls back to risk-based sizing capped by concentration (legacy mode).

    Returns:
        dict with shares, risk_amount, risk_per_share, position_value
    """
    risk_amount = portfolio_value * max_risk_pct
    risk_per_share = abs(entry_price - stop_loss_price)

    if risk_per_share <= 0:
        return {"shares": 0, "error": "Stop loss must differ from entry price"}

    shares_by_risk = math.floor(risk_amount / risk_per_share)
    shares_by_concentration = math.floor(portfolio_value * max_position_pct / entry_price)

    if size_pct is not None:
        # AI-requested target size: clamp to hard cap, also bounded by risk.
        # This lets the AI say "low conviction, 5% position" instead of always 25%.
        effective_pct = min(size_pct, max_position_pct)
        shares_by_size = math.floor(portfolio_value * effective_pct / entry_price)
        shares = min(shares_by_size, shares_by_concentration)
        capped_by = "size_pct" if shares_by_size < shares_by_concentration else "concentration"
    else:
        # Legacy mode: risk-based sizing, capped by concentration.
        shares = min(shares_by_risk, shares_by_concentration)
        capped_by = "concentration" if shares_by_concentration < shares_by_risk else "risk"

    position_value = shares * entry_price

    return {
        "shares": shares,
        "risk_amount": round(risk_amount, 2),
        "actual_risk_amount": round(shares * risk_per_share, 2),
        "risk_per_share": round(risk_per_share, 2),
        "position_value": round(position_value, 2),
        "position_pct": round((position_value / portfolio_value) * 100, 2),
        "risk_pct": round((shares * risk_per_share / portfolio_value) * 100, 2),
        "max_risk_pct": round(max_risk_pct * 100, 2),
        "capped_by": capped_by,
        # Keep legacy field for backward compat (old code checks capped_by_concentration)
        "capped_by_concentration": capped_by == "concentration",
    }


def calculate_stops(entry_price, atr, risk_mult=1.5, reward_mult=2.0):
    """
    Calculate stop-loss and take-profit based on ATR.
    
    Args:
        entry_price: entry price
        atr: Average True Range value
        risk_mult: stop distance = atr × risk_mult (default 1.5)
        reward_mult: reward/risk ratio (default 2.0 = 2:1 R/R)
    
    Returns:
        dict with stop_loss, take_profit, risk, reward, rr_ratio
    """
    stop_distance = atr * risk_mult
    reward_distance = stop_distance * reward_mult
    
    # For longs (adjust logic for shorts in caller)
    stop_loss = entry_price - stop_distance
    take_profit = entry_price + reward_distance
    
    return {
        "stop_loss": round(stop_loss, 2),
        "take_profit": round(take_profit, 2),
        "risk_per_share": round(stop_distance, 2),
        "reward_per_share": round(reward_distance, 2),
        "rr_ratio": reward_mult,
    }


def check_portfolio_risk(positions, portfolio_value, max_positions=None,
                         max_position_pct=0.25, concentration_trim_threshold=None):
    """
    Check if portfolio risk rules are satisfied before adding a new position.

    Args:
        positions: list of current position dicts (from alpaca_client.get_positions)
        portfolio_value: current portfolio value
        max_positions: max concurrent positions allowed; None = unlimited
                       (capital is bounded by concentration/exposure instead)
        max_position_pct: max % of portfolio for a NEW position at entry
        concentration_trim_threshold: trim EXISTING positions only above this %.
            Defaults to max_position_pct + 7% tolerance band if not specified.
            This prevents churn: a position bought at 25% that drifts to 25.5%
            due to price movement should NOT trigger a trim. Only trim when the
            position has genuinely grown to dominate the portfolio.

    Returns:
        dict with allowed (bool), reason, current_exposure
    """
    if concentration_trim_threshold is None:
        concentration_trim_threshold = max_position_pct + 0.07  # 7% tolerance band

    num_positions = len(positions)
    total_exposure = sum(float(p["market_value"]) for p in positions)
    exposure_pct = (total_exposure / portfolio_value * 100) if portfolio_value > 0 else 0

    issues = []

    if max_positions is not None and num_positions >= max_positions:
        issues.append(f"Max positions reached ({num_positions}/{max_positions})")

    if exposure_pct > 80:
        issues.append(f"High exposure ({exposure_pct:.1f}% of portfolio)")

    # Check individual position concentration.
    # IMPORTANT: use the TRIM threshold for existing positions, not the entry cap.
    # A position bought at 24% that grows to 26% because the stock went up is NOT
    # a risk breach — it's a winner. Trimming it just creates churn + taxes.
    # Only flag if position exceeds the trim threshold (default 32%).
    for p in positions:
        pos_pct = float(p["market_value"]) / portfolio_value * 100 if portfolio_value > 0 else 0
        if pos_pct > concentration_trim_threshold * 100:
            issues.append(f"{p['symbol']} over weight ({pos_pct:.1f}% > {concentration_trim_threshold*100:.0f}% trim threshold)")
    
    return {
        "allowed": len(issues) == 0,
        "issues": issues,
        "num_positions": num_positions,
        "total_exposure": round(total_exposure, 2),
        "exposure_pct": round(exposure_pct, 1),
    }


def sleeve_of(symbol, cfg):
    """Return the universe group ('commodities', 'semis', …) a symbol belongs
    to, or None if it's not in the configured universe."""
    for group, syms in (cfg.get("strategy", {}).get("universe", {}) or {}).items():
        if symbol in (syms or []):
            return group
    return None


def check_sleeve_cap(symbol, order_value, cfg, positions, portfolio_value,
                     pending_value=0.0):
    """Cap exposure per universe group — correlated positions move together,
    so GLD+SLV+GDX must share one budget, not three.

    Args:
        symbol: symbol being bought (its sleeve is looked up from cfg)
        order_value: desired order cost in dollars
        cfg: full config dict (uses risk.max_sleeve_exposure + strategy.universe)
        positions: current broker positions (dicts with symbol/market_value)
        portfolio_value: current portfolio value in dollars
        pending_value: BUY cost already approved this cycle in the same sleeve

    Returns:
        (allowed_order_value, reason) — allowed_value of 0.0 means reject;
        a reduced positive value means "size down to fit".
        Symbols outside the universe (or cap <= 0) are uncapped.
    """
    cap = float(cfg.get("risk", {}).get("max_sleeve_exposure", 0.35) or 0)
    sleeve = sleeve_of(symbol, cfg)
    if not sleeve or cap <= 0 or portfolio_value <= 0:
        return order_value, None

    sleeve_syms = set(cfg["strategy"]["universe"].get(sleeve) or [])
    held = sum(float(p["market_value"]) for p in positions
               if p.get("symbol") in sleeve_syms)
    limit = portfolio_value * cap
    room = max(0.0, limit - held - pending_value)

    if order_value <= room + 1e-9:
        return order_value, None
    if room <= 0:
        return 0.0, (f"sleeve '{sleeve}' at cap: {held/portfolio_value*100:.1f}% held "
                     f"(cap {cap*100:.0f}%)")
    return room, (f"sleeve '{sleeve}' cap: sized down to fit "
                  f"({held/portfolio_value*100:.1f}% held, cap {cap*100:.0f}%)")


def assess_trade(symbol, entry_price, stop_loss_price, portfolio_value, current_positions=None):
    """
    Full trade risk assessment. Combines position sizing and portfolio checks.
    
    Returns a recommendation dict.
    """
    if current_positions is None:
        current_positions = []
    
    sizing = calculate_position_size(portfolio_value, entry_price, stop_loss_price)
    portfolio_check = check_portfolio_risk(current_positions, portfolio_value)
    
    if sizing["shares"] == 0:
        return {"recommendation": "SKIP", "reason": sizing.get("error", "Invalid sizing"), "sizing": sizing}
    
    if not portfolio_check["allowed"]:
        return {
            "recommendation": "WAIT",
            "reason": "; ".join(portfolio_check["issues"]),
            "sizing": sizing,
            "portfolio_check": portfolio_check,
        }
    
    return {
        "recommendation": "GO",
        "symbol": symbol,
        "sizing": sizing,
        "portfolio_check": portfolio_check,
    }
