import pytest
from unittest.mock import MagicMock
from pipeline.soft_review import soft_review
from core.schema import CampaignBrief, Channel, EmailType

@pytest.fixture
def mock_llm_client():
    mock_instance = MagicMock()
    # It should return a JSON array string since json.loads(text) is used
    mock_instance.complete.return_value = '[{"concern": "Tone", "detail": "This looks good, but could be friendlier."}]'
    return mock_instance

def test_soft_review_agent(mock_llm_client):
    brief = CampaignBrief(
        channel=Channel.EMAIL,
        email_type=EmailType.MASS,
        market="UK",
        audience="Patients",
        brand="TestDrug",
        objective="Testing SR"
    )
    
    html_content = "<html>Some draft content</html>"
    
    result = soft_review(html_content, brief, mock_llm_client)
    
    assert len(result) == 1
    assert result[0].concern == "Tone"
    assert result[0].detail == "This looks good, but could be friendlier."
    mock_llm_client.complete.assert_called_once()
