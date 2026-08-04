"""
LangGraph version of pipeline.py — same nodes, same logic, different
orchestration mechanism. This is NOT a generic "here's how LangGraph
works" example: every node calls the exact same generator.py/grader.py/
regulatory.py/soft_review.py functions pipeline.py does. Nothing about
the generation, grading, or resolution logic changes — only how the
control flow between them is expressed.

WHY THIS VERSION EXISTS (vs. the plain-Python pipeline.py):
pipeline.py's loop was a defensible "just a while loop" when it was 3
steps (generate -> grade -> revise). Now that resolution can branch
into an LLM call or not, and there's a genuinely separate soft-review
step, that's 4 nodes with real conditional routing — closer to where
LangGraph's actual value (declarative graph structure, and free
step-by-step tracing via .stream(), see __main__ below) starts to
outweigh the extra dependency. Ship whichever one matches what you're
being evaluated on: pipeline.py is easier to explain line-by-line in
an interview; this one is easier to extend if you're adding more nodes
later (e.g. loop 3's event trigger calling this graph from a queue
consumer) or if a client specifically wants LangGraph on the resume.

Graph shape:

    resolve --> generate --> grade --(not done, not stuck, iter<MAX)--> generate
                                 |
                                 +--(all_passed OR stuck OR iter>=MAX)--> soft_review --> END
"""

from __future__ import annotations
import sys
# Guard: Streamlit may replace sys.stdout with a custom object that
# lacks .encoding or .reconfigure(). Only reconfigure real terminal stdout.
if (hasattr(sys.stdout, 'encoding')
        and sys.stdout.encoding
        and sys.stdout.encoding.lower() != 'utf-8'
        and hasattr(sys.stdout, 'reconfigure')):
    sys.stdout.reconfigure(encoding='utf-8')

from typing import Optional, TypedDict, Any
from langgraph.graph import StateGraph, END
from core.logger import get_logger
from core.exceptions import GenerationError, PipelineError
from core.brand_config import get_brand_tokens
from core.schema import CampaignBrief, PipelineResult, GradeReport, SoftReviewNote, Severity
from core.llm_client import LLMClient
from core.regulatory import resolve_market, resolve_audience, MarketInfo, AudienceInfo
from pipeline.grader import GradingContext
from pipeline.generator import generate as gen_generate, revise as gen_revise
from pipeline.grader import grade as gen_grade
from pipeline.soft_review import soft_review as gen_soft_review
from core.trace_logger import log_iteration, log_resolution

import os
MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "3"))

class PipelineState(TypedDict, total=False):
    brief: CampaignBrief
    client: Any  # LLMClient — not put through LangGraph's serialization, this graph runs in-process only
    run_soft_review: bool

    market_info: MarketInfo
    audience_info: AudienceInfo
    ctx: GradingContext

    html: str
    grade_report: GradeReport
    iteration: int
    prev_failed_ids: Optional[tuple]
    stuck: bool

    soft_review_notes: list[SoftReviewNote]
    human_feedback: Optional[str]


logger = get_logger(__name__)

def node_resolve(state: PipelineState) -> dict:
    brief, client = state["brief"], state["client"]
    market_info = resolve_market(brief.market, client=client)
    audience_info = resolve_audience(brief.audience, client=client)
    log_resolution(brief, market_info, audience_info)
    ctx = GradingContext(tokens=get_brand_tokens(brief.brand), market_info=market_info, audience_info=audience_info, client=client)
    
    logger.info(f"[Resolve] Market '{brief.market}' -> {market_info.body_name} (Source: {market_info.source})")
    logger.info(f"[Resolve] Audience '{brief.audience}' -> HCP={audience_info.is_hcp} (Source: {audience_info.source})")
    
    return {"market_info": market_info, "audience_info": audience_info, "ctx": ctx}


def node_generate(state: PipelineState) -> dict:
    brief, client, ctx = state["brief"], state["client"], state["ctx"]
    iteration = state.get("iteration", 0) + 1
    logger.info(f"Generating draft, iteration {iteration}")
    try:
        if iteration == 1 and not state.get("human_feedback"):
            html = gen_generate(brief, client, ctx)
        else:
            html = gen_revise(brief, state["html"], state.get("grade_report"), client, ctx, state.get("human_feedback"))
    except Exception as e:
        if not isinstance(e, PipelineError):
            raise GenerationError(f"Draft generation failed: {e}") from e
        raise
    
    logger.info(f"[Generate] Draft generated successfully ({len(html)} bytes)")
    return {"html": html, "iteration": iteration}


def node_grade(state: PipelineState) -> dict:
    brief, ctx, html, iteration = state["brief"], state["ctx"], state["html"], state["iteration"]
    report = gen_grade(html, brief, ctx, iteration=iteration)
    log_iteration(brief, report, iteration=iteration)

    current_failed_ids = tuple(sorted(i.rule_id for i in report.failed_items))
    old_prev = state.get("prev_failed_ids")
    stuck = old_prev is not None and current_failed_ids == old_prev  # same stuck-detector as pipeline.py

    passed_count = sum(1 for i in report.items if i.passed)
    logger.info(f"[Grade] Iteration {iteration}: {passed_count}/{len(report.items)} rules passed")
    for item in report.failed_items:
        status_label = "WARN" if item.severity.value == "warning" else "FAILED"
        logger.info(f"  [{status_label}] {item.label} — {item.detail}")

    if stuck:
        logger.warning(f"[Grade] Pipeline is stuck! Failed rules are identical to the previous iteration: {current_failed_ids}")

    return {"grade_report": report, "prev_failed_ids": current_failed_ids, "stuck": stuck}


def node_soft_review(state: PipelineState) -> dict:
    if not state.get("run_soft_review", True) or not state["grade_report"].all_passed:
        logger.info("[Soft Review] Skipped (either disabled or blocking rules failed)")
        return {"soft_review_notes": []}
    
    logger.info("[Soft Review] Running subjective LLM advisory review...")
    notes = gen_soft_review(state["html"], state["brief"], state["client"])
    
    logger.info(f"[Soft Review] Generated {len(notes)} advisory notes")
    for n in notes:
        logger.info(f"  - {n.concern}: {n.detail}")
        
    return {"soft_review_notes": notes}


def route_after_grade(state: PipelineState) -> str:
    report = state["grade_report"]
    if report.all_passed:
        return "soft_review"
    if state.get("stuck"):
        return "soft_review"  # give up — same call pipeline.py's stuck-detector makes
    if state["iteration"] >= MAX_ITERATIONS:
        return "soft_review"
    return "generate"


def build_graph():
    g = StateGraph(PipelineState)
    g.add_node("resolve", node_resolve)
    g.add_node("generate", node_generate)
    g.add_node("grade", node_grade)
    g.add_node("soft_review", node_soft_review)

    g.set_entry_point("resolve")
    g.add_edge("resolve", "generate")
    g.add_edge("generate", "grade")
    g.add_conditional_edges("grade", route_after_grade, {"generate": "generate", "soft_review": "soft_review"})
    g.add_edge("soft_review", END)

    return g.compile()


def run_pipeline_langgraph(brief: CampaignBrief, client: LLMClient | None = None,
                            run_soft_review: bool = True) -> PipelineResult:
    client = client or LLMClient()
    graph = build_graph()
    final_state = graph.invoke({
        "brief": brief, "client": client, "run_soft_review": run_soft_review,
        "iteration": 0, "prev_failed_ids": None,
    })
    return PipelineResult(
        brief=brief,
        final_html=final_state["html"],
        grade_report=final_state["grade_report"],
        iterations_used=final_state["iteration"],
        soft_review_notes=final_state.get("soft_review_notes", []),
        approved_for_production=False,  # always — same guarantee as pipeline.py, enforced here too
    )


if __name__ == "__main__":
    # Same sample brief as pipeline.py's smoke test, but using .stream() instead of
    # .invoke() to print each node as it runs — this incremental visibility is
    # essentially free with LangGraph (no ui_log() calls threaded through every
    # function by hand, unlike app.py's version of this same loop).
    client = LLMClient()
    brief = CampaignBrief(
        channel="email", email_type="mass", market="UK", audience="HCP", brand="Dovato",
        objective="Pre-launch HIV treatment awareness", classification="unbranded",
    )
    graph = build_graph()
    final_state = {}
    for step in graph.stream({"brief": brief, "client": client, "run_soft_review": True,
                               "iteration": 0, "prev_failed_ids": None}):
        node_name = list(step.keys())[0]
        logger.info(f"[node: {node_name}] completed")
        final_state.update(step[node_name])

    print(f"\nIterations used: {final_state['iteration']}")
    for item in final_state["grade_report"].items:
        status = "PASSED" if item.passed else ("WARN" if item.severity == Severity.WARNING else "FAILED")
        print(f"  [{status}] {item.label} — {item.detail}")
    if final_state.get("soft_review_notes"):
        print("\nSoft review (advisory, not verified):")
        for n in final_state["soft_review_notes"]:
            print(f"  - {n.concern}: {n.detail}")
    if client.last_usage:
        u = client.last_usage
        print(f"\nFinal call usage: {u.get('input_tokens')} in / {u.get('output_tokens')} out tokens")
        if u.get("cache_read_input_tokens"):
            print(f"  cache read: {u['cache_read_input_tokens']} tokens (cheaper — exact discount depends on Azure's own pricing)")
        if u.get("reasoning_tokens"):
            print(f"  reasoning tokens: {u['reasoning_tokens']} (hidden thinking, not visible output)")
    with open("outputs/last_run_langgraph.html", "w", encoding="utf-8") as f:
        f.write(final_state["html"])
    print("\nWrote outputs/last_run_langgraph.html")
