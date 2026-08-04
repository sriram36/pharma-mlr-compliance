"""
Soft review — the genuinely agentic half of Loop 2.

grader.py's structural rules check objective, checkable facts (a border exists,
a string is present). None of them are judgment calls, so none of them
should cost an LLM call. But a real MLR review also asks questions no
regex can answer: does this copy *imply* an efficacy claim without
stating one outright? Is "fair balance" actually balanced, or just
technically present? Does the tone match clinical register?

This module runs ONE LLM call, ONLY after all blocking grader rules
already pass (no point spending it on a structurally incomplete draft),
and returns advisory notes that are:
  - never pass/fail — there's no ground truth for "does this feel
    borderline," so scoring it as blocking would be false confidence
  - never merged into GradeReport — an LLM reviewing its own sibling's
    output is a weaker signal than the deterministic rules, and mixing
    it into the same list would make it look equally authoritative
  - always labeled as what they are: a second AI's opinion, for a human
    to weigh, not a verified finding
"""

from __future__ import annotations

import json
from typing import Any

from core.schema import CampaignBrief, SoftReviewNote
from core.utils import strip_code_fences


_SOFT_REVIEW_SYSTEM = """You are doing a SECOND-PASS advisory read of pharma marketing draft \
copy, after it has already passed structural compliance checks (AE box, watermark, audience \
tag, etc. — don't re-check any of that). You're looking ONLY for subjective concerns a \
regex/DOM check structurally cannot catch:

- Implied efficacy or safety claims that aren't explicitly stated but could be read that way
- "Fair balance" that's technically present but visually/rhetorically lopsided (e.g. benefits \
  in a bold headline, risks in six-point-equivalent afterthought text)
- Tone that doesn't match clinical/professional register for the stated audience
- Anything that reads as engineered to survive an automated compliance check rather than to \
  actually satisfy its intent (e.g. a technically-present AE box formatted to be easy to skim past)
- Mismatched or inappropriate imagery. If images are provided in the prompt, verify that their \
  contents are relevant and appropriate for the context (e.g., flag if a joyful lifestyle image is \
  used inappropriately next to a severe Boxed Warning, or if the logo belongs to the wrong brand).

Respond with ONLY a JSON array, no other text, no markdown fences. Each item:
{"concern": "<short label>", "detail": "<one or two sentences, specific to what's in this draft>"}

Return an empty array [] if you don't see any real concerns — don't manufacture something to \
seem thorough. Most passing drafts should get 0-2 notes, not a checklist-length list."""


def soft_review(html: str, brief: CampaignBrief, client: Any) -> list[SoftReviewNote]:
    """
    One LLM call. Callers (pipeline.py) are responsible for only invoking
    this after GradeReport.all_passed is True, so it's never spent on a
    draft that's not even structurally finished yet.

    No try/except around the API call or JSON parsing — a failure here
    should surface as a real, visible exception, not silently degrade
    into a fake "unavailable" note that looks like a normal result.
    """
    user = f"""Brief context: {brief.market} market, {brief.audience} audience, \
{brief.classification.value} classification, objective: "{brief.objective}"

DRAFT HTML:
{html}
"""
    images = list(brief.uploaded_images.values()) if brief.uploaded_images else None
    raw = client.complete(system=_SOFT_REVIEW_SYSTEM, user=user, max_tokens=2000, images=images)
    text = strip_code_fences(raw)
    items = json.loads(text)
    return [SoftReviewNote(concern=i.get("concern", "Untitled concern"), detail=i.get("detail", ""))
            for i in items]
