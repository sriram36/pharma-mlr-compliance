import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from api import app
from core.schema import PipelineResult, GradeReport, GradeItem, Severity, Channel, ContentClassification, CampaignBrief

client = TestClient(app)

def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_history_and_analytics_endpoints():
    response = client.get("/api/history")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

    response = client.get("/api/analytics")
    assert response.status_code == 200
    data = response.json()
    assert "total_drafts" in data
    assert "overall_pass_rate" in data

def test_rate_limiter_registered():
    assert hasattr(app.state, "limiter")
    assert app.state.limiter is not None

def test_webhook_campaign_endpoint_mocked(monkeypatch):
    test_brief = CampaignBrief(
        channel=Channel.EMAIL,
        market="UK",
        audience="HCP",
        brand="Dovato",
        objective="Test objective",
        classification=ContentClassification.UNBRANDED_DISEASE_AWARENESS
    )
    mock_result = PipelineResult(
        brief=test_brief,
        final_html="<html><body>Draft HTML</body></html>",
        grade_report=GradeReport(
            items=[
                GradeItem(rule_id="test", label="Test Rule", passed=True, severity=Severity.BLOCKING, detail="All clear")
            ],
            iteration=1,
        ),
        iterations_used=1,
        soft_review_notes=[],
        approved_for_production=False
    )

    with patch("api.run_pipeline_langgraph", return_value=mock_result):
        payload = {
            "channel": "email",
            "market": "UK",
            "audience": "HCP",
            "brand": "Dovato",
            "objective": "Test objective",
            "classification": "unbranded",
            "run_soft_review": False
        }
        response = client.post("/api/webhook/campaign", json=payload)
        assert response.status_code == 200
        res = response.json()
        assert res["status"] == "success"
        assert res["all_passed"] is True
        assert res["iterations_used"] == 1
