import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "manual_review_agreement",
    Path(__file__).resolve().parent.parent / "scripts" / "manual_review_agreement.py",
)
mra = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mra)


def rows(*pairs):
    return [
        {"draft_id": "d1", "rule_id": f"r{i}", "grader": g, "human": h, "note": ""}
        for i, (g, h) in enumerate(pairs)
    ]


def test_counts_agreement_and_disagreement():
    agreed, total, counts = mra.agreement(rows(("pass", "pass"), ("fail", "fail"), ("pass", "fail"), ("fail", "pass")))
    assert (agreed, total) == (2, 4)
    assert counts[(True, False)] == 1 and counts[(False, True)] == 1


def test_everything_agrees():
    agreed, total, _ = mra.agreement(rows(("pass", "pass"), ("pass", "pass")))
    assert agreed == total == 2


def test_labels_are_case_and_space_tolerant():
    agreed, total, _ = mra.agreement(rows((" Pass", "PASS "), ("fail", "Fail")))
    assert (agreed, total) == (2, 2)


def test_rejects_unknown_labels():
    with pytest.raises(ValueError):
        mra.agreement(rows(("pass", "maybe")))


def test_empty_file_is_reported_not_crashed(tmp_path, capsys):
    p = tmp_path / "empty.csv"
    p.write_text("draft_id,rule_id,grader,human,note\n", encoding="utf-8")
    assert mra.main(["x", str(p)]) == 1
    assert "no decisions yet" in capsys.readouterr().out
