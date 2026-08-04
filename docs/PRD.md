# PRD — Pharma Marketing Draft Pipeline (Generate → Grade → Revise)

**Status:** Prototype / portfolio build
**Owner:** Sriram Kolli
**Last updated:** 2026-07-04

---

## 1. Summary

A tool that turns a structured campaign brief (channel, market,
audience, brand, objective, branded/unbranded classification) into an
HTML email/web mockup, then mechanically checks that draft against a
set of pharma-marketing structural compliance rules (ABPI/FDA-style),
feeding any failures back into the generator for a bounded number of
automatic revisions before handing the result to a human reviewer.

It does **not** replace Medical/Legal/Regulatory (MLR) review. It
produces a *structurally complete draft* — one that already has the
AE reporting box, the HCP-only line, the correct branded/unbranded
copy rules, etc. — so a human reviewer's time goes toward judging
clinical accuracy and tone rather than catching a missing safety box.

---

## 2. Problem statement

Producing a first draft of a pharma marketing email today typically
means a copywriter and designer spending real time on something that
will very likely bounce back from MLR review for a structural,
checklist-level reason (missing AE box, brand name leaked into
unbranded copy, no HCP-only statement) — not a substantive one. That
round trip is slow and repetitive precisely *because* the failure
modes are repetitive and enumerable.

## 3. Goals

- **G1.** Given a structured brief, produce a first-draft HTML mockup
  in under a minute.
- **G2.** Mechanically verify the draft against a defined set of
  structural rules before a human ever sees it, with a clear
  pass/fail/warning explanation per rule.
- **G3.** When a rule fails, automatically attempt a targeted fix
  (not a full rewrite) and re-check, bounded to a small number of
  attempts.
- **G4.** Make every failure mode legible: a human reviewer should be
  able to see *why* something passed or failed without re-reading the
  whole draft.
- **G5.** Accept free-text market/audience/brand input rather than a
  fixed list, without silently mis-grading unrecognized values.

## 4. Non-goals

- **NG1.** This tool does not grant regulatory approval. No output is
  ever marked "approved for production" by the system itself — that
  decision stays with a qualified human reviewer, always.
- **NG2.** This tool does not verify clinical/scientific accuracy of
  any claim. Any statistic or trial result in a draft is required to
  be marked `[PENDING VERIFICATION]` rather than asserted as fact —
  the tool checks that the *marker* is present, not that a claim is
  true.
- **NG3.** Not a DAM (digital asset management) system — logos and
  real image assets are never embedded; they stay labeled
  placeholders by design.
- **NG4.** Not a CMS or send/distribution tool. No email is ever
  actually sent; no real destination URL is ever generated.
- **NG5.** Not a full localization engine — market resolution covers
  UK/US/EU/Swiss out of the box; more markets are a config change
  (`regulatory.py::MARKET_MAP`), not a redesign, but aren't
  pre-built.

## 5. Users / personas

| Persona | Need |
|---|---|
| Marketing copywriter | Fast, structurally-sound first draft to edit rather than starting blank |
| MLR / compliance reviewer | A draft that's already past the "obvious" structural issues, with a visible audit trail explaining what was auto-checked |
| Agency/dev building this for a client (you) | A defensible, explainable architecture — not a black box — for presenting to that client or in an interview |

## 6. Functional requirements

| ID | Requirement |
|---|---|
| FR-1 | System accepts a brief with: channel, email type (if channel=email), market (free text), audience (free text), brand (free text), objective (free text), classification (branded/unbranded). |
| FR-2 | System generates a single HTML draft from the brief via an LLM call, using brand-specific visual/compliance tokens where the brand is recognized, and explicit `[TBC]` placeholder tokens where it isn't. |
| FR-3 | System grades the draft against 11 structural rules (§8) and returns a pass/fail/warning + human-readable explanation per rule. |
| FR-4 | On any blocking rule failure, system sends the specific failing rules (not the whole rule set) back to the generator with the previous draft, requesting a targeted patch, and re-grades. |
| FR-5 | Revision loop is bounded (default: 3 total attempts) and halts early once only non-blocking warnings remain. |
| FR-6 | System resolves free-text market input against a known-alias map (UK/US/EU/Swiss + common synonyms) using word-boundary matching; unrecognized markets degrade the relevant rule to a non-blocking warning rather than a silent pass or unfair hard fail. |
| FR-7 | System resolves free-text audience input for HCP-like keywords (hcp, doctor, physician, clinician, nurse, prescriber) to decide whether the HCP-only audience statement rule applies. |
| FR-8 | Every draft visibly includes a DRAFT / "not approved for distribution" watermark and a pending job-code placeholder. |
| FR-9 | `PipelineResult.approved_for_production` is always `False`; no code path sets it to `True`. |
| FR-10 | Every pipeline run appends a trace record (brand, market, audience, iteration, pass/fail per rule) to an append-only log for later analysis. |
| FR-11 | A UI (Streamlit and/or browser demo) lets a user submit a brief and see, in order: brand/market/audience resolution, each generation call, each rule's result, and the final rendered draft with a download option. |

## 7. Non-functional requirements

- **Transparency over abstraction.** No agent framework (LangChain/
  LangGraph/DeepAgents) — the orchestration is a plain bounded loop,
  intentionally, so every step is inspectable and explainable without
  reference to a third-party runtime's internals.
- **Determinism where it matters.** All 11 blocking/warning rules are
  regex/DOM-based, not a second LLM call — grading must be
  reproducible and auditable, not a matter of an LLM's judgment on a
  given day.
- **Single provider, no silent fallback.** `llm_client.py` supports
  Azure OpenAI only — no alternate provider, no "try something else if
  this isn't configured." Missing credentials or a failed API call
  raise immediately rather than degrading to a placeholder result.
  This was a deliberate choice, not a limitation: a fallback that
  silently switches providers (or worse, silently returns fake
  content) turns a real failure into something that looks like a
  normal result, which is worse than the pipeline just stopping.
- **Honest uncertainty is not the same as error-swallowing.** An
  unrecognized market/audience with no `client` passed in, or an LLM
  response that says "I'm not confident," still resolves to an honest
  `known=False` state rather than crashing — that's a legitimate
  answer, not a failure. A failed API call or malformed response,
  by contrast, raises. The distinction matters: one is "the input is
  genuinely ambiguous," the other is "something broke," and only the
  first should ever look like a normal outcome.
- **Token cost discipline.** The system prompt is kept market-agnostic
  specifically so it's one stable prefix reused across every call
  rather than resent fresh each time. Azure documents automatic
  caching on repeated prompts, though this hasn't been independently
  verified for a reasoning-model deployment specifically. Market-
  specific guidance is front-loaded into the first generation call to
  reduce revision-loop iterations, since an extra iteration costs a
  full extra input+output round trip, not just a few tokens.

## 8. Compliance rule specification (the Grader)

| Rule ID | Checks | Default severity |
|---|---|---|
| `watermark` | "DRAFT" + "Not approved for distribution" present | blocking |
| `job_code` | `[CL ID` placeholder present | blocking |
| `audience_tag` | If audience resolves as HCP: "healthcare professional" + a known market alias present in visible body copy | blocking (warning if audience isn't HCP-like) |
| `ae_box` | A real CSS border + "adverse event" text + the brand's exact AE line (verbatim) all present | blocking |
| `brand_leak` | If unbranded: product name absent from visible body copy (annotation footer excluded) | blocking (n/a if branded) |
| `pi_link` | If branded: "Prescribing Information" placeholder present | blocking (n/a if unbranded) |
| `reg_footer` | Market resolves to a known regulatory tag (ABPI/FDA/OPDP/EFPIA/Swissmedic) and that tag appears in the footer | blocking (warning if market unrecognized) |
| `cta_url` | Every `<a href>` is `#` or otherwise clearly a placeholder — no real-looking destination URL | blocking |
| `logo_placeholder` | No `<img>` with a "logo" class pointing at a real `src` — logo stays a text placeholder | blocking |
| `black_triangle` | UK/EU only: draft mentions ▼ / "additional monitoring" status | warning — reminder, not a verified fact |
| `boxed_warning` | US only: draft mentions "Boxed Warning" status | warning — reminder, not a verified fact |

The last two exist specifically because EU/UK and US promotional
requirements genuinely differ in content, not just in which acronym
appears in a footer — see `regulatory.py::MARKET_MAP`. Both are
warning-severity by design: the tool cannot know a given product's
real additional-monitoring or Boxed Warning status, so it flags the
question for a human rather than asserting an answer it doesn't have.

## 9. System architecture

```
CampaignBrief ──▶ generator.py ──▶ HTML draft ──▶ grader.py ──▶ GradeReport
                     ▲                                  │
                     │ (failed items + previous draft)   │ all_passed?
                     └──────────── revise() ◀────────────┘ no → loop (max 3)
                                                          │ yes → done
                                                          ▼
                                              PipelineResult (approved_for_production=False)
```

- `schema.py` — data contracts
- `brand_config.py` — per-brand visual + AE-line tokens, with a
  placeholder default for unknown brands
- `regulatory.py` — free-text market/audience resolution
- `llm_client.py` — Azure OpenAI client, no fallback provider
- `generator.py` — Loop 1 (generate/revise)
- `grader.py` — Loop 2 (9 deterministic rules)
- `pipeline.py` — orchestration + circuit breaker
- `trace_logger.py` / `analyze_traces.py` — lightweight hill-climbing
  loop (failure-rate analysis across runs)
- `app.py` — Streamlit UI
- `live-loop-demo.html` — standalone browser demo (same rule logic,
  ported to JS, for zero-setup live demonstration)

## 10. Success metrics (for a prototype/portfolio context)

- **First-attempt pass rate** across a batch of test briefs (tracked
  via `analyze_traces.py`) — the metric to watch as you iterate on
  `prompts/generator_system.md`.
- **Average iterations to pass**, when it does pass.
- **Rule-level failure frequency** — which of the 11 rules the
  generator struggles with most, used to prioritize prompt fixes.
- Qualitative: can a reviewer unfamiliar with the code understand
  *why* a given draft passed or failed from the audit trail alone,
  without reading the HTML?

## 11. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Output mistaken for an MLR-approved, sendable asset | Hard-coded `approved_for_production=False`; visible DRAFT watermark on every output; README states this explicitly |
| Fabricated clinical/statistical claims presented as fact | Generator prompt requires `[PENDING VERIFICATION]` markers on any specific stat; no rule currently verifies claim *truth*, only marker presence — documented as NG2 |
| False compliance signal from an LLM "self-grading" its own output | Grading is deterministic (regex/DOM), not a second LLM call |
| Free-text market/audience causing false positives/negatives | Word-boundary matching (not substring) after catching a real "us" ⊂ "focuses" bug during testing; unrecognized values degrade to warnings, not silent passes |
| Real brand names/colors used in a demo escaping context | DRAFT watermark, placeholder logos (never real image assets embedded), placeholder CTAs, no synthesized real destination URLs |
| Revision loop running away / burning API cost on an unfixable brief | `MAX_ITERATIONS = 3` circuit breaker; early exit once only non-blocking warnings remain |
| A failed API call silently producing a placeholder result that looks like a normal outcome | Removed entirely — `llm_client.py`, `regulatory.py`'s LLM resolvers, and `soft_review.py` all raise on failure now instead of catching and returning a fake result; see CODE_WALKTHROUGH.md §15 |
| Misconfigured credentials silently running on a different/unintended provider | Single provider only (Azure OpenAI) — no fallback chain that could mask a config error by quietly using something else |

## 12. Open questions / future work

- Loop 3 (event-driven trigger): wrap `run_pipeline()` in a FastAPI
  endpoint for async, queue-driven brief submission — deferred, not
  designed yet.
- Should the LLM-judgment layer (flagging *soft* issues like drifting
  toward an efficacy claim, as distinct from the 9 hard structural
  rules) be added as a clearly-separated "suggestions for human
  review" section, never mixed into the blocking pass/fail list?
- Expand `regulatory.py::MARKET_MAP` beyond UK/US/EU/Swiss as needed —
  config change, not a redesign.
- Optional: a LangGraph port of `pipeline.py`'s loop, if a client
  specifically wants that framework represented in the architecture.

## 13. Glossary

- **MLR** — Medical, Legal, Regulatory review; the mandatory human
  approval process pharma promotional content must pass before use.
- **ABPI** — Association of the British Pharmaceutical Industry; UK
  code of practice for pharma promotion.
- **OPDP** — FDA's Office of Prescription Drug Promotion (US).
- **AE** — Adverse Event.
- **Branded vs. unbranded (disease awareness)** — branded content
  names the product; unbranded/disease-awareness content discusses a
  condition without naming any product, per ABPI-style pre-launch
  rules.
