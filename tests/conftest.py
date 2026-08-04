"""
Shared test fixtures — DRYs up the base_brief / branded_brief / run_rule
helpers that were previously duplicated across each test file.
"""

import pytest
from core.schema import CampaignBrief, ContentClassification
from core.regulatory import MarketInfo, AudienceInfo
from pipeline.grader import GradingContext


@pytest.fixture
def base_brief():
    return CampaignBrief(
        channel="email",
        email_type="mass",
        market="UK",
        audience="HCP",
        brand="Dovato",
        objective="Test objective",
        classification=ContentClassification.UNBRANDED_DISEASE_AWARENESS,
    )


@pytest.fixture
def branded_brief(base_brief):
    return base_brief.model_copy(update={"classification": ContentClassification.BRANDED})


@pytest.fixture
def uk_hcp_ctx():
    """Standard UK/HCP grading context for most tests."""
    return GradingContext(
        tokens={},
        market_info=MarketInfo(
            market_text="UK", body_name="ABPI", tags=["ABPI"],
            known=True, aliases=["uk", "united kingdom"], source="dictionary",
        ),
        audience_info=AudienceInfo(
            audience_text="HCP", source="dictionary", known=True, is_hcp=True,
        ),
    )
