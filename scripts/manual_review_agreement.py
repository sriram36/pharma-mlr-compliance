"""Agreement between the grader and a manual review.

Reads evals/manual_review.csv (one row per decision) and prints how often the
grader and the human reviewer agreed.

Columns: draft_id, rule_id, grader (pass or fail), human (pass or fail), note

Usage:   python scripts/manual_review_agreement.py [path/to/manual_review.csv]
"""
from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

DEFAULT = Path(__file__).resolve().parent.parent / "evals" / "manual_review.csv"
VALID = {"pass", "fail"}


def load(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def agreement(rows):
    """Return (agreed, total, counts). counts maps (grader_passed, human_passed) to a number."""
    counts = Counter()
    for i, r in enumerate(rows, start=2):
        g, h = r["grader"].strip().lower(), r["human"].strip().lower()
        if g not in VALID or h not in VALID:
            raise ValueError(f"row {i}: grader and human must be 'pass' or 'fail', got {g!r} and {h!r}")
        counts[(g == "pass", h == "pass")] += 1
    total = sum(counts.values())
    agreed = counts[(True, True)] + counts[(False, False)]
    return agreed, total, counts


def main(argv):
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT
    rows = load(path)
    if not rows:
        print(f"{path} has no decisions yet. Add rows, then run this again.")
        return 1
    agreed, total, c = agreement(rows)
    drafts = len({r["draft_id"] for r in rows})
    print(f"drafts: {drafts}   decisions: {total}")
    print(f"agreement: {agreed}/{total} = {agreed / total:.0%}")
    print(
        f"both pass {c[(True, True)]}, both fail {c[(False, False)]}, "
        f"grader pass but human fail {c[(True, False)]}, grader fail but human pass {c[(False, True)]}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
