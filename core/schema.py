"""
Core data contracts for the pipeline.

Everything downstream (generator, grader, orchestrator, Streamlit UI)
imports from here so the "shape" of a brief and a grade result only
lives in one place.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

ImageMap = dict[str, str]

from core.regulatory import resolve_market, is_hcp_audience


class Channel(str, Enum):
    EMAIL = "email"
    WEB = "web"


class EmailType(str, Enum):
    MASS = "mass"
    ONE_TO_ONE = "1:1"


# NOTE: Market and Audience used to be closed enums (UK/US/EU/Swiss,
# HCP/Patient/General public). The UI now takes free text for these -
# "Ireland", "Payers", "Caregivers", whatever the brief actually needs -
# so CampaignBrief.market / .audience are plain strings below.
# regulatory.py is where free text gets interpreted; nothing else in the
# pipeline should try to string-match market/audience directly.


class Severity(str, Enum):
    """Grade-item severity — an enum, not a magic string, so a typo
    like 'bloking' blows up at validation time instead of silently
    behaving as an unknown category."""
    BLOCKING = "blocking"
    WARNING = "warning"
    ADVISORY = "advisory"  # soft-review notes only


class ContentClassification(str, Enum):
    """
    Whether the product name is allowed to appear in the body copy.
    This single field drives most of the hard grading rules below.
    """
    BRANDED = "branded"                # product name allowed, PI link mandatory
    UNBRANDED_DISEASE_AWARENESS = "unbranded"  # product name must NOT appear in body


class CampaignBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")

    """The structured input a user submits (mirrors your sample input format)."""

    channel: Channel
    email_type: Optional[EmailType] = None  # required if channel == EMAIL
    market: str = Field(..., description="Free text, e.g. 'UK', 'United Kingdom', 'Ireland'")
    audience: str = Field(..., description="Free text, e.g. 'HCP', 'Prescribing nurses', 'Patients'")
    brand: str = Field(..., description="e.g. Dovato, Nucala, Trelegy, Shingrix")
    objective: str = Field(..., description="e.g. 'Pre-launch HIV treatment awareness'")
    classification: ContentClassification = ContentClassification.UNBRANDED_DISEASE_AWARENESS
    uploaded_images: ImageMap = Field(default_factory=dict, description="Dictionary mapping filenames to base64 data URIs of uploaded images")

    def regulatory_body(self) -> str:
        """Convenience only — dictionary/cache lookup, no LLM fallback (no client
        available here). The pipeline itself resolves market once with LLM fallback
        and threads that through; this method is for quick ad-hoc/test use."""
        return resolve_market(self.market).body_name

    def is_hcp(self) -> bool:
        """Convenience only — same caveat as regulatory_body() above."""
        return is_hcp_audience(self.audience)


class GradeItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    label: str
    passed: bool
    detail: str
    severity: Severity = Severity.BLOCKING


class GradeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[GradeItem]
    iteration: int

    @property
    def all_passed(self) -> bool:
        return all(i.passed for i in self.items if i.severity == Severity.BLOCKING)

    @property
    def failed_items(self) -> list[GradeItem]:
        return [i for i in self.items if not i.passed]


class SoftReviewNote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    """Defined here (not just in soft_review.py) so schema.py stays the single
    place PipelineResult's shape is declared. Deliberately NOT part of
    GradeReport — see soft_review.py for why keeping it separate matters."""
    concern: str
    detail: str
    severity: Severity = Severity.ADVISORY


class PipelineResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    brief: CampaignBrief
    final_html: str
    grade_report: GradeReport
    iterations_used: int
    soft_review_notes: list[SoftReviewNote] = []  # advisory only, see soft_review.py
    approved_for_production: bool = False  # ALWAYS false — see pipeline.py note
