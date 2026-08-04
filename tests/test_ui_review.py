import json
from pathlib import Path
import pytest
from ui.review import update_draft_status


def test_update_draft_status(tmp_path: Path):
    test_json = tmp_path / "test_draft.json"
    initial_data = {
        "id": "#1201",
        "brand": "Dovato",
        "market": "UK",
        "status": "Draft",
        "compliance": "16/16",
    }
    test_json.write_text(json.dumps(initial_data), encoding="utf-8")

    updated = update_draft_status(
        json_path=test_json,
        new_status="Approved",
        reviewer_name="Dr. Alex Rivera, PharmD",
        comment="All ABPI compliance requirements satisfied. Approved for production.",
    )

    assert updated["status"] == "Approved"
    assert updated["reviewed_by"] == "Dr. Alex Rivera, PharmD"
    assert "ABPI" in updated["reviewer_comment"]
    assert len(updated["history_log"]) == 1
    assert updated["history_log"][0]["action"] == "Approved"

    # Test second transition
    updated2 = update_draft_status(
        json_path=test_json,
        new_status="Under Revision",
        reviewer_name="Sarah Chen, Legal",
        comment="Adjust layout of AE box.",
    )
    assert updated2["status"] == "Under Revision"
    assert len(updated2["history_log"]) == 2
