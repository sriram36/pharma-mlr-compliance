# Manual review

`manual_review.csv` records where a person checked the grader's work. One row per decision:

| Column | Meaning |
|---|---|
| `draft_id` | which generated draft, for example `scen-03-run-1` |
| `rule_id` | the grader rule, for example `ae_box` |
| `grader` | what the grader said: `pass` or `fail` |
| `human` | what the reviewer decided by hand: `pass` or `fail` |
| `note` | optional, for a disagreement |

Then run:

```
python scripts/manual_review_agreement.py
```

It prints how many decisions matched, as "X of Y", and where they disagreed.

How to keep it honest:

- Review the draft first, then look at the grader's verdict, so it does not sway you.
- Use only drafts the pipeline generated from the synthetic scenarios in `scripts/eval_harness.py`. Never commit real client, employer or confidential material.
- Say in `docs/manual_review.md` how many drafts and decisions you reviewed, who reviewed them and when. A small sample and a single reviewer are limits, so say so.

This file is empty until a review has been done. Nothing here is a result yet.
