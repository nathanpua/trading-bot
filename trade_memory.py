#!/usr/bin/env python3
"""
Trade Memory — persistent cross-cycle intelligence via supermemory.

Dedicated container_tag 'trading_bot' partitions trading memories from
general Hermes conversation memory. Stores analyst findings, regime
patterns, catalyst outcomes, and lessons learned. Recalls them at the
start of each cycle so the desk chief has accumulated context.

Usage:
    from trade_memory import TradeMemory
    tm = TradeMemory()
    tm.store_finding("MU HBM4 demand surging, DRAM +60% YoY", {"symbol":"MU","type":"fundamental"})
    results = tm.recall("memory pricing trends")
    summary = tm.recall_for_cycle()  # pre-formatted context block
"""
import os, sys, json, time, logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

CONTAINER_TAG = "trading_bot"


def _load_api_key():
    """Load supermemory key from .env files (authoritative — env var may be stale)."""
    # Always read from .env files first — the environment variable may hold a
    # stale key from before the user refreshed it.
    for envpath in [
        Path(__file__).parent / ".env",
        Path.home() / ".hermes" / "profiles" / "trading" / ".env",
        Path.home() / ".hermes" / ".env",
    ]:
        if not envpath.exists():
            continue
        for line in envpath.read_text().splitlines():
            line = line.strip()
            if line.startswith("SUPERMEMORY_API_KEY"):
                val = line.split("=", 1)[1].strip().strip("'\"")
                if val.startswith("sm_"):
                    return val
    # Fall back to env var only if no .env file has it
    key = os.environ.get("SUPERMEMORY_API_KEY")
    if key and key.startswith("sm_"):
        return key
    return None


class TradeMemory:
    """Supermemory-backed persistent memory for the trading bot."""

    def __init__(self):
        self._client = None
        self._connected = False
        key = _load_api_key()
        if not key:
            logger.warning("No SUPERMEMORY_API_KEY found — memory disabled")
            return
        try:
            from supermemory import Supermemory
            os.environ["SUPERMEMORY_API_KEY"] = key
            self._client = Supermemory(max_retries=1)
            # Verify connectivity
            self._client.search.memories(q="ping", container_tag=CONTAINER_TAG, limit=1)
            self._connected = True
            logger.info("Supermemory connected (container: %s)", CONTAINER_TAG)
        except Exception as e:
            logger.warning("Supermemory unavailable: %s — memory disabled", e)
            self._client = None
            self._connected = False

    @property
    def connected(self):
        return self._connected

    def store_finding(self, content, metadata=None, custom_id=None):
        """Store an unstructured finding (analyst insight, regime pattern, lesson).

        Args:
            content: the finding text (e.g. "MU beat EPS by 5.8%, HBM4 guidance strong")
            metadata: flat dict with string/number/bool values (e.g. {"symbol":"MU","type":"earnings"})
            custom_id: optional dedup key (same ID = update, not duplicate)
        """
        if not self._client:
            return {"stored": False, "reason": "disconnected"}
        meta = {"source": "trading_bot", "ts": datetime.now(timezone.utc).isoformat(), **(metadata or {})}
        try:
            kwargs = {"content": content.strip(), "container_tags": [CONTAINER_TAG], "metadata": meta}
            if custom_id:
                kwargs["custom_id"] = custom_id
            result = self._client.documents.add(**kwargs)
            doc_id = getattr(result, "id", "")
            logger.info("Stored finding: %s (id=%s)", content[:60], doc_id)
            return {"stored": True, "id": doc_id}
        except Exception as e:
            logger.error("Store failed: %s", e)
            return {"stored": False, "error": str(e)[:100]}

    def store_cycle_summary(self, cycle_report):
        """Store a full cycle report (the desk chief's briefing)."""
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        content = f"CYCLE {ts}: {cycle_report}"
        return self.store_finding(content, {"type": "cycle_summary"})

    def recall(self, query, limit=5):
        """Semantic search across all trading memories.

        Args:
            query: natural language (e.g. "what happened with MU earnings?")
            limit: max results

        Returns:
            list of dicts: [{"memory": str, "similarity": float, "metadata": dict}, ...]
        """
        if not self._client:
            return []
        try:
            response = self._client.search.memories(
                q=query, container_tag=CONTAINER_TAG, limit=limit
            )
            results = []
            for item in (getattr(response, "results", None) or []):
                results.append({
                    "memory": getattr(item, "memory", "") or "",
                    "similarity": getattr(item, "similarity", 0) or 0,
                    "metadata": getattr(item, "metadata", {}) or {},
                })
            return results
        except Exception as e:
            logger.error("Recall failed: %s", e)
            return []

    def recall_for_cycle(self, current_positions=None):
        """Pre-formatted memory context block for the desk chief to read.

        Pulls: recent findings, relevant lessons for held positions,
        and best practices. Returns a formatted string.
        """
        if not self._client:
            return "[memory unavailable]"

        lines = ["=== MEMORY RECALL ==="]

        # Recent findings (last cycle summaries + analyst insights)
        # Use a query that explicitly seeks BOTH wins and losses
        recent = self.recall("recent trades outcomes wins losses analysis", limit=5)
        if recent:
            lines.append("RECENT FINDINGS:")
            for r in recent:
                lines.append(f"  • [{r['similarity']:.0%}] {r['memory'][:150]}")
        else:
            lines.append("RECENT FINDINGS: (none yet)")

        # Position-specific recall
        if current_positions:
            lines.append("POSITION-SPECIFIC:")
            for sym in current_positions:
                results = self.recall(f"{sym} thesis earnings catalyst", limit=2)
                for r in results:
                    lines.append(f"  • [{sym}] {r['memory'][:120]}")

        # Best practices / lessons
        lessons = self.recall("trading lessons what worked what failed best practices", limit=3)
        if lessons:
            lines.append("LESSONS:")
            for r in lessons:
                lines.append(f"  • {r['memory'][:120]}")

        lines.append("=== END MEMORY ===")
        return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Trade memory CLI")
    sub = ap.add_subparsers(dest="command")

    sp = sub.add_parser("store", help="Store a finding")
    sp.add_argument("content")
    sp.add_argument("--type", default="finding")
    sp.add_argument("--symbol", default="")

    sp = sub.add_parser("recall", help="Recall memories")
    sp.add_argument("query")
    sp.add_argument("--limit", type=int, default=5)

    sp = sub.add_parser("status", help="Check connectivity")

    sp = sub.add_parser("context", help="Get full cycle context block")

    args = ap.parse_args()
    tm = TradeMemory()

    if args.command == "status":
        print(f"Connected: {tm.connected}")
    elif args.command == "store":
        meta = {"type": args.type}
        if args.symbol:
            meta["symbol"] = args.symbol
        result = tm.store_finding(args.content, meta)
        print(json.dumps(result, indent=2))
    elif args.command == "recall":
        results = tm.recall(args.query, args.limit)
        for r in results:
            print(f"[{r['similarity']:.0%}] {r['memory']}")
            if r.get("metadata"):
                print(f"         meta: {r['metadata']}")
    elif args.command == "context":
        print(tm.recall_for_cycle())
    else:
        ap.print_help()
