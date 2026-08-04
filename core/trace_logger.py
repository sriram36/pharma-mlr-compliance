"""
Trace logger — Loop 4 (hill-climbing loop) in loop-engineering terms.

Every pipeline run appends one JSON line per iteration to traces.jsonl:
which rules failed, on which brand/market, on which attempt number.
Run `python analyze_traces.py` after you've collected some runs to see
which rules the Generator struggles with most — that's your signal for
which part of prompts/generator_system.md to sharpen next, instead of
guessing.
"""

from __future__ import annotations

import json
import time
import threading
from pathlib import Path

from core.utils import redact_text

TRACE_FILE = Path(__file__).parent.parent / "traces.jsonl"
_write_lock = threading.Lock()


def _redact_brief(brief) -> dict:
    return {
        "brand": redact_text(brief.brand),
        "market": redact_text(brief.market),
        "audience": redact_text(brief.audience),
        "classification": redact_text(brief.classification.value),
    }


def log_iteration(brief, grade_report, iteration: int, prompt_hash: str | None = None, input_hash: str | None = None) -> None:
    record = {
        "ts": time.time(),
        "type": "iteration",
        **_redact_brief(brief),
        "iteration": iteration,
        "all_passed": grade_report.all_passed,
        "failed_rules": [i.rule_id for i in grade_report.failed_items],
        "prompt_hash": prompt_hash,
        "input_hash": input_hash,
    }
    with _write_lock:
        with TRACE_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")


def log_resolution(brief, market_info, audience_info) -> None:
    """
    Separate from log_iteration so analyze_traces.py can answer a cost
    question directly: "what fraction of runs actually needed an LLM
    call to resolve market/audience, versus hitting the free dictionary
    or cache path?" A market/audience list that's mostly "dictionary"
    after a while means the free tier is covering real traffic well;
    mostly "llm" means MARKET_MAP/HCP_KEYWORDS are worth expanding.
    """
    record = {
        "ts": time.time(),
        "type": "resolution",
        **_redact_brief(brief),
        "market_source": market_info.source,
        "market_known": market_info.known,
        "audience_source": audience_info.source,
        "audience_known": audience_info.known,
    }
    with _write_lock:
        with TRACE_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
