import pytest
from unittest.mock import MagicMock
from pipeline.generator import generate
from core.schema import CampaignBrief, Channel, EmailType
from pipeline.grader import GradingContext
from core.regulatory import MarketInfo, AudienceInfo

@pytest.fixture
def mock_llm_client():
    mock_instance = MagicMock()
    mock_instance.complete.return_value = "<html>Test Draft</html>"
    return mock_instance

def test_draft_generator(mock_llm_client):
    brief = CampaignBrief(
        channel=Channel.EMAIL,
        email_type=EmailType.MASS,
        market="US",
        audience="HCPs",
        brand="TestDrug",
        objective="Testing Generation"
    )
    ctx = GradingContext(
        market_info=MarketInfo(market_text="US", body_name="FDA", known=True, source="dictionary"),
        audience_info=AudienceInfo(audience_text="HCPs", is_hcp=True, known=True, source="keyword"),
        tokens={"company": "TestCo", "primary": "#000", "secondary": "#fff", "ae_report_line": "Call AE", "pi_link_placeholder": "PI here"}
    )
    
    result = generate(brief, mock_llm_client, ctx)
    
    assert result == "<html>Test Draft</html>"
    mock_llm_client.complete.assert_called_once()

