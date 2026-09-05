"""Sector breadth — thin CLI wrapper over the root breadth module.

Refreshes prices via the broker/LSE feed (alpaca_client bars, CSV-cached)
instead of reading stale local CSVs, and prints the same table format the
premarket report expects. Includes leadership names alongside sectors.
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import breadth


def main():
    b = breadth.compute_breadth()
    print("=== S&P SECTOR BREADTH vs 20-SMA ===")
    for d in sorted(b["details"], key=lambda x: -x["pct_vs_sma"]):
        print(f"{d['name']:<8}{d['close']:>9.2f}{d['pct_vs_sma']:>+8.2f}%  "
              f"{'ABOVE' if d['above'] else 'BELOW'}")
    print(f"\nABOVE 20-SMA: {b['above']}  |  BELOW: {b['below']}  |  "
          f"net breadth: {b['net']:+d}  (broad: >+5, narrow risk-off: <0)")

    print("\n=== MARKET LEADERSHIP vs 20-SMA ===")
    leaders = breadth.compute_breadth(
        symbols=["SMH", "SOXX", "NVDA", "AVGO", "MU", "MSFT", "META", "AMZN", "TSLA", "XBI"])
    for d in sorted(leaders["details"], key=lambda x: -x["pct_vs_sma"]):
        print(f"{d['symbol']:<6}{d['close']:>9.2f}{d['pct_vs_sma']:>+8.2f}%  "
              f"{'ABOVE' if d['above'] else 'BELOW'}")


if __name__ == "__main__":
    main()
