import pytest
from bs4 import BeautifulSoup
from core.schema import CampaignBrief, ContentClassification, Severity

from pipeline.grader import rule_hcp_audience_tag, rule_regulatory_footer_tag, GradingContext
from core.regulatory import MarketInfo, AudienceInfo

def test_word_boundary_regression():
    # Market="US" should NOT be satisfied by body text containing "focuses" or "discusses"
    brief = CampaignBrief(
        channel="email",
        email_type="mass",
        market="US",
        audience="HCP",
        brand="Dovato",
        objective="Test objective",
        classification=ContentClassification.UNBRANDED_DISEASE_AWARENESS
    )

    # Note that rule_hcp_audience_tag requires both the "healthcare professional" string
    # AND the market name to appear if the market is known.
    html_fail = "<div>This focuses on healthcare professional insights and discusses outcomes.</div>"
    soup = BeautifulSoup(html_fail, "html.parser")

    ctx = GradingContext(
        tokens={},
        market_info=MarketInfo(market_text="US", body_name="FDA", tags=["FDA"], known=True, aliases=["us", "united states"], source="dictionary"),
        audience_info=AudienceInfo(audience_text="HCP", source="dictionary", known=True, is_hcp=True)
    )
    item = rule_hcp_audience_tag(soup, html_fail, brief, ctx)
    assert not item.passed, "Word boundary check failed, incorrectly matched 'us' inside 'focuses' or 'discusses'."

    # Correct case
    html_pass = "<div>This US healthcare professional site is for HCPs.</div>"
    soup_pass = BeautifulSoup(html_pass, "html.parser")
    item_pass = rule_hcp_audience_tag(soup_pass, html_pass, brief, ctx)
    assert item_pass.passed

def test_unrecognized_market_narnia():
    brief = CampaignBrief(
        channel="email",
        email_type="mass",
        market="Narnia",
        audience="HCP",
        brand="Dovato",
        objective="Test objective",
        classification=ContentClassification.UNBRANDED_DISEASE_AWARENESS
    )

    html = "<footer>Some footer text.</footer>"
    soup = BeautifulSoup(html, "html.parser")

    ctx2 = GradingContext(
        tokens={},
        market_info=MarketInfo(market_text="Narnia", body_name="Unknown", tags=[], known=False, aliases=[], source="llm"),
        audience_info=AudienceInfo(audience_text="HCP", source="dictionary", known=True, is_hcp=True)
    )
    item = rule_regulatory_footer_tag(soup, html, brief, ctx2)

    assert not item.passed
    assert item.severity == Severity.BLOCKING, "Unrecognized market now treated as blocking per policy change."
