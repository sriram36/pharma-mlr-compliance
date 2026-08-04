"""
Pipeline orchestrator — wires Loop 1 (generate) to Loop 2 (grade) with
a bounded revision loop, and logs every attempt for Loop 4 analysis.

Resolution (market/audience free text -> structured info, with LLM
fallback for anything the dictionary doesn't know) happens exactly
ONCE here, before generation even starts. The resolved MarketInfo/
AudienceInfo then gets threaded through as plain data to the generator
and grader — neither of them re-resolves anything, which is what keeps
the grader's "zero LLM calls" guarantee true regardless of how exotic
the input market/audience text was.

IMPORTANT: `approved_for_production` on the result is hard-coded False.
Passing every automated check means the draft is structurally
complete, not that a qualified MLR reviewer has approved the clinical
claims, fair balance, and final copy. Don't let a UI or a future
version of this script quietly repurpose "all checks passed" as
"safe to send" — that decision has to stay with a human. The optional
soft_review notes are even further from that: a second AI's opinion,
advisory only, never a verified finding.
"""

from __future__ import annotations

from core.brand_config import get_brand_tokens
from pipeline.generator import generate, revise
from pipeline.grader import grade, GradingContext
from core.llm_client import LLMClient
from core.regulatory import resolve_market, resolve_audience
from core.schema import CampaignBrief, PipelineResult, Severity
from pipeline.soft_review import soft_review
from core.trace_logger import log_iteration, log_resolution

MAX_ITERATIONS = 3


def run_pipeline(brief: CampaignBrief, client: LLMClient | None = None, run_soft_review: bool = True) -> PipelineResult:
    client = client or LLMClient()

    # Resolve once, up front. Dictionary/cache hits cost nothing; an LLM call only
    # happens here if market/audience is genuinely unrecognized free text — and
    # only once per unique string ever, since resolve_* caches to disk.
    market_info = resolve_market(brief.market, client=client)
    audience_info = resolve_audience(brief.audience, client=client)
    log_resolution(brief, market_info, audience_info)

    ctx = GradingContext(
        tokens=get_brand_tokens(brief.brand),
        market_info=market_info,
        audience_info=audience_info,
        client=client
    )
    html = generate(brief, client, ctx)
    report = grade(html, brief, ctx, iteration=1)
    log_iteration(brief, report, iteration=1)

    iteration = 1
    prev_failed_ids = None
    while not report.all_passed and iteration < MAX_ITERATIONS:
        # Stuck detector: if the exact same rules failed on the previous attempt too, another
        # identical revision call is very unlikely to fix it — it means the prompt needs a real
        # fix, not another retry. Stop here rather than burn a 3rd call repeating the same result
        # (this is exactly what the live browser demo hit before this check was added: 3 calls,
        # same 4 failures every time, because a truncated first draft made every "patch" attempt
        # reproduce the same too-long structure and hit the same wall again).
        current_failed_ids = tuple(sorted(i.rule_id for i in report.failed_items))
        if prev_failed_ids is not None and current_failed_ids == prev_failed_ids:
            break
        prev_failed_ids = current_failed_ids

        iteration += 1
        html = revise(brief, html, report, client, ctx)
        report = grade(html, brief, ctx, iteration=iteration)
        log_iteration(brief, report, iteration=iteration)

    notes = []
    if run_soft_review and report.all_passed:
        # Only spent on a draft that's already structurally complete — no point
        # asking for a subjective read of something that's still missing an AE box.
        notes = soft_review(html, brief, client)

    return PipelineResult(
        brief=brief,
        final_html=html,
        grade_report=report,
        iterations_used=iteration,
        soft_review_notes=notes,
        approved_for_production=False,  # always — see module docstring
    )


if __name__ == "__main__":
    # Quick manual smoke test — mirrors your sample input.
    client = LLMClient()
    brief = CampaignBrief(
        channel="email",
        email_type="mass",
        market="UK",
        audience="HCP",
        brand="Dovato",
        objective="Pre-launch HIV treatment awareness",
        classification="unbranded",
    )
    result = run_pipeline(brief, client=client)
    print(f"Iterations used: {result.iterations_used}")
    for item in result.grade_report.items:
        status = "PASSED" if item.passed else ("WARN" if item.severity == Severity.WARNING else "FAILED")
        print(f"  [{status}] {item.label} — {item.detail}")
    if result.soft_review_notes:
        print("\nSoft review (advisory, not verified):")
        for n in result.soft_review_notes:
            print(f"  - {n.concern}: {n.detail}")
    if client.last_usage:
        u = client.last_usage
        print(f"\nFinal call usage: {u.get('input_tokens')} in / {u.get('output_tokens')} out tokens")
        if u.get("cache_read_input_tokens"):
            print(f"  cache read: {u['cache_read_input_tokens']} tokens (cheaper — exact discount depends on Azure's own pricing)")
        if u.get("reasoning_tokens"):
            print(f"  reasoning tokens: {u['reasoning_tokens']} (hidden thinking, not visible output — Azure reasoning models only)")
    with open("outputs/last_run.html", "w", encoding="utf-8") as f:
        f.write(result.final_html)
    print("\nWrote outputs/last_run.html")
