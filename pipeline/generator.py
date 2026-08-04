"""
Generator node for the MLR pipeline.
Turns a CampaignBrief into a full HTML draft, or patches an existing draft
based on GradeReport feedback during revision cycles.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from core.schema import CampaignBrief, GradeReport
from core.regulatory import market_addendum
from core.llm_client import LLMClient
from core.utils import strip_code_fences
from pipeline.grader import GradingContext

# Loaded once at import time and reused byte-for-byte on every call, for every
# brand and market. Deliberately market-agnostic — see llm_client.py: this is
# what lets it stay one stable prefix (Azure documents automatic caching on
# repeated prompts >=1024 tokens, though this hasn't been independently
# verified for a reasoning-model deployment specifically — check
# usage.cache_read_input_tokens on a real run rather than trusting this
# comment) across the entire app's lifetime, not just within a single
# brief's generate/revise loop. Market-specific rules live in regulatory.py
# and get injected into the (per-call, not cached the same way) USER prompt
# per-call) USER prompt instead — see _brief_prompt() below.
SYSTEM_PROMPT = Path(__file__).parent.parent.joinpath("prompts", "generator_system.md").read_text(encoding="utf-8")


def _extract_html(raw: str) -> str:
    """Strip markdown code fences if the model wrapped its answer in one."""
    return strip_code_fences(raw)


def _brief_prompt(brief: CampaignBrief, ctx: GradingContext) -> str:
    tokens = ctx.tokens
    return f"""
Generate the HTML draft for this brief:

- Channel: {brief.channel.value}{f" ({brief.email_type.value})" if brief.email_type else ""}
- Market: {brief.market}
- Audience: {brief.audience}
- Brand: {brief.brand} ({tokens['company']})
- Objective: {brief.objective}
- Classification: {brief.classification.value}
- Uploaded Images: {", ".join(brief.uploaded_images.keys()) if brief.uploaded_images else "None"}

Market-specific compliance notes (these vary by market — apply only what's relevant here):
{market_addendum(ctx.market_info)}

Brand tokens to use exactly as given (do not invent alternatives):
- Primary color: {tokens['primary']}
- Secondary color: {tokens['secondary']}
- AE reporting line (use verbatim inside the bordered AE box): {tokens['ae_report_line']}
- PI link placeholder text: {tokens['pi_link_placeholder']}

Follow the system prompt's "Required-concepts checklist" section and try to satisfy those items on the initial generation.

Return ONLY the HTML file contents. No preamble, no explanation, no markdown fences.
"""


def generate(brief: CampaignBrief, client: LLMClient, ctx: GradingContext) -> str:
    images = list(brief.uploaded_images.values()) if brief.uploaded_images else None
    raw = client.complete(system=SYSTEM_PROMPT, user=_brief_prompt(brief, ctx), max_tokens=6000, images=images)
    return _extract_html(raw)



def revise(brief: CampaignBrief, previous_html: str, grade_report: Optional[GradeReport], client: LLMClient, ctx: GradingContext, human_feedback: Optional[str] = None) -> str:
    tokens = ctx.tokens
    
    feedback_section = ""
    if grade_report and grade_report.failed_items:
        failed = grade_report.failed_items
        failure_list = "\n".join(f"- [{i.rule_id}] {i.label}: {i.detail}" for i in failed)
        feedback_section += f"\nFAILED CHECKS:\n{failure_list}\n\nPatch ONLY what's needed to fix the failed checks above."
    
    if human_feedback:
        feedback_section += f"\nHUMAN REVIEWER FEEDBACK:\n{human_feedback}\n\nPrioritize these human changes while maintaining all previous brand rules."

    user_prompt = f"""
Here is the previous draft:

PREVIOUS DRAFT HTML:
{previous_html}
{feedback_section}

Keep everything else — including any passing checks and existing copy — unchanged.
Brand tokens (unchanged from the original brief):
- Primary color: {tokens['primary']}
- Secondary color: {tokens['secondary']}
- AE reporting line: {tokens['ae_report_line']}
- PI link placeholder text: {tokens['pi_link_placeholder']}
- Uploaded Images: {", ".join(brief.uploaded_images.keys()) if brief.uploaded_images else "None"}

Return ONLY the corrected full HTML file. No preamble, no markdown fences.
"""
    images = list(brief.uploaded_images.values()) if brief.uploaded_images else None
    raw = client.complete(system=SYSTEM_PROMPT, user=user_prompt, max_tokens=6000, images=images)
    return _extract_html(raw)
