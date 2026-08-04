"""
Run this after you've accumulated some traces.jsonl history to see
which rules the Generator trips on most, broken down by brand/market.
That's your prioritized list for sharpening generator_system.md —
data-driven prompt iteration instead of vibes.

Usage: python analyze_traces.py
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

TRACE_FILE = Path(__file__).parent.parent / "traces.jsonl"


def main():
    if not TRACE_FILE.exists():
        print("No traces.jsonl yet — run pipeline.py a few times first.")
        return

    all_records = [json.loads(line) for line in TRACE_FILE.read_text().splitlines() if line.strip()]
    # Old trace files predate the "type" field — everything in them was an iteration record.
    records = [r for r in all_records if r.get("type", "iteration") == "iteration"]
    resolutions = [r for r in all_records if r.get("type") == "resolution"]

    first_attempts = [r for r in records if r["iteration"] == 1]

    rule_fail_counts = Counter()
    for r in first_attempts:
        rule_fail_counts.update(r["failed_rules"])

    print(f"Total runs: {len(first_attempts)}")
    print(f"First-attempt pass rate: {sum(r['all_passed'] for r in first_attempts) / max(len(first_attempts),1):.0%}\n")

    print("Rules that fail most often on the FIRST attempt (fix these in the prompt first):")
    for rule, count in rule_fail_counts.most_common():
        pct = count / max(len(first_attempts), 1)
        print(f"  {rule:20s} failed {count:3d}x  ({pct:.0%} of runs)")

    avg_iters = sum(r["iteration"] for r in records if r["all_passed"]) / max(
        sum(1 for r in records if r["all_passed"]), 1
    )
    print(f"\nAvg iterations to pass (when it passes): {avg_iters:.1f}")

    if resolutions:
        print(f"\nMarket/audience resolution cost breakdown ({len(resolutions)} runs):")
        market_sources = Counter(r["market_source"] for r in resolutions)
        audience_sources = Counter(r["audience_source"] for r in resolutions)
        for label, counts in [("market", market_sources), ("audience", audience_sources)]:
            print(f"  {label}:")
            for source, count in counts.most_common():
                cost_note = "free" if source in ("dictionary", "keyword", "cache") else "paid LLM call"
                print(f"    {source:12s} {count:3d}x  ({cost_note})")
        llm_calls = sum(1 for r in resolutions if r["market_source"] == "llm") + \
                    sum(1 for r in resolutions if r["audience_source"] == "llm")
        print(f"  -> {llm_calls} resolution LLM call(s) across {len(resolutions)} runs. If this "
              f"number is high and the same unrecognized markets/audiences keep recurring, add "
              f"them to MARKET_MAP/HCP_KEYWORDS directly — the cache already saves repeats of the "
              f"exact same string, but a slightly different phrasing of the same market still "
              f"pays for a fresh LLM call once.")


if __name__ == "__main__":
    main()
