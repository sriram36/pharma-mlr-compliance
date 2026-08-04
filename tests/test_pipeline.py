import pytest
from unittest.mock import MagicMock, patch
from core.schema import CampaignBrief, ContentClassification, GradeReport, GradeItem, Severity

from pipeline.pipeline import run_pipeline

class FakeLLMClient:
    def __init__(self):
        self.provider = "fake"
        self.last_usage = {"input_tokens": 100, "output_tokens": 50}

    def complete(self, *args, **kwargs):
        # We don't actually use complete directly in our mock because we'll patch generator functions.
        # But we mock it just in case.
        return "<html>Fake HTML</html>"

@patch('pipeline.pipeline.generate')
@patch('pipeline.pipeline.grade')
@patch('pipeline.pipeline.revise')
@patch('pipeline.pipeline.soft_review')
def test_pipeline_revision_loop_passes_only_failed_items(mock_soft_review, mock_revise, mock_grade, mock_generate, base_brief):
    mock_soft_review.return_value = []
    mock_client = FakeLLMClient()

    mock_generate.return_value = "<html>Initial Draft</html>"

    item_pass = GradeItem(rule_id="rule_pass", label="Pass Rule", passed=True, detail="Passed", severity=Severity.BLOCKING)
    item_fail = GradeItem(rule_id="rule_fail", label="Fail Rule", passed=False, detail="Failed detail", severity=Severity.BLOCKING)

    report1 = GradeReport(items=[item_pass, item_fail], iteration=1)
    report2 = GradeReport(items=[item_pass], iteration=2)

    mock_grade.side_effect = [report1, report2]

    mock_revise.return_value = "<html>Revised Draft</html>"

    result = run_pipeline(base_brief, client=mock_client)

    # Assertions
    assert result.iterations_used == 2
    assert result.approved_for_production is False

    mock_revise.assert_called_once()
    args, kwargs = mock_revise.call_args
    # revise(brief, previous_html, grade_report, client, ctx)
    called_report = args[2]
    # Check that the report passed to revise has failed items
    failed = called_report.failed_items
    assert len(failed) == 1
    assert failed[0].rule_id == "rule_fail"
