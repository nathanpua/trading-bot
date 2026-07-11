"""
Risk management module — position sizing, stop-loss/take-profit calculation,
and portfolio risk rules.

Core principles:
- Never risk more than max_risk_pct of portfolio per trade (default 2%)
- Position size = (Portfolio × risk%) / (entry - stop_loss)
- Maximum concurrent positions (default 5)
- Sector concentration limits
"""

import math


def calculate_position_size(portfolio_value, entry_price, stop_loss_price,
                            max_risk_pct=0.02, max_position_pct=0.25):
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

    Returns:
        dict with shares, risk_amount, risk_per_share, position_value
    """
    risk_amount = portfolio_value * max_risk_pct
    risk_per_share = abs(entry_price - stop_loss_price)

    if risk_per_share <= 0:
        return {"shares": 0, "error": "Stop loss must differ from entry price"}

    shares_by_risk = math.floor(risk_amount / risk_per_share)
    shares_by_concentration = math.floor(portfolio_value * max_position_pct / entry_price)
    shares = min(shares_by_risk, shares_by_concentration)
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
        "capped_by_concentration": shares_by_concentration < shares_by_risk,
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


def check_portfolio_risk(positions, portfolio_value, max_positions=5, max_position_pct=0.25):
    """
    Check if portfolio risk rules are satisfied before adding a new position.
    
    Args:
        positions: list of current position dicts (from alpaca_client.get_positions)
        portfolio_value: current portfolio value
        max_positions: max concurrent positions allowed
        max_position_pct: max % of portfolio in a single position
    
    Returns:
        dict with allowed (bool), reason, current_exposure
    """
    num_positions = len(positions)
    total_exposure = sum(float(p["market_value"]) for p in positions)
    exposure_pct = (total_exposure / portfolio_value * 100) if portfolio_value > 0 else 0
    
    issues = []
    
    if num_positions >= max_positions:
        issues.append(f"Max positions reached ({num_positions}/{max_positions})")
    
    if exposure_pct > 80:
        issues.append(f"High exposure ({exposure_pct:.1f}% of portfolio)")
    
    # Check individual position concentration
    for p in positions:
        pos_pct = float(p["market_value"]) / portfolio_value * 100 if portfolio_value > 0 else 0
        if pos_pct > max_position_pct * 100:
            issues.append(f"{p['symbol']} over weight ({pos_pct:.1f}% > {max_position_pct*100:.0f}%)")
    
    return {
        "allowed": len(issues) == 0,
        "issues": issues,
        "num_positions": num_positions,
        "total_exposure": round(total_exposure, 2),
        "exposure_pct": round(exposure_pct, 1),
    }


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
