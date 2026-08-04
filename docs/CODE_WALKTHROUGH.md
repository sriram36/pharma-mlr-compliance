# Code Walkthrough — Pharma Marketing Draft Pipeline

This explains *why* each file exists and *how* the pieces fit together —
not just what the code does, but the reasoning behind each decision, so
you can defend every choice if your client or an interviewer asks.

---

## 1. The core idea: two loops, not one AI call

A single LLM call producing a "final" marketing email is a demo. What
makes this a *pipeline* is that the output is never trusted on the
first try — it's mechanically checked, and specific failures are fed
back for a second attempt. That's the whole concept from the LangChain
article you sent, reduced to its essence:

```
Loop 1 (generator/agent loop):  brief → LLM → HTML
Loop 2 (verification loop):     HTML → rule engine → pass/fail list
                                 fail? → feed failures back into Loop 1
```

Everything below is either building Loop 1, building Loop 2, or wiring
them together.

---

## 2. `schema.py` — the data contracts

```python
class CampaignBrief(BaseModel):
    channel: Channel
    email_type: Optional[EmailType] = None
    market: str          # free text now — was an enum, see §7
    audience: str         # free text now — was an enum
    brand: str
    objective: str
    classification: ContentClassification   # still a controlled enum, deliberately
```

**Why Pydantic:** it validates shape at the boundary (e.g. `channel`
must be `"email"` or `"web"`, nothing else) so nothing downstream has
to defensively check "did I get a sane object." One `BaseModel`
definition, and Streamlit's form, the CLI smoke test, and the grader
all agree on what a brief looks like.

**Why `classification` stayed an enum while market/audience didn't:**
`unbranded` vs `branded` isn't descriptive metadata — it's a fork in
the actual logic. `rule_brand_leak` and `rule_pi_link_if_branded`
branch on it directly. Market and audience, by contrast, only need to
be *interpreted* (which regulatory tag does "United Kingdom" imply?),
not branched on structurally — so they became strings, and
`regulatory.py` does the interpretation. If a field changes what code
path runs, keep it a closed enum. If a field only changes what content
gets checked for, free text plus a resolver is more flexible and just
as safe.

`GradeItem` / `GradeReport` — a rule produces a `GradeItem` (id, human
label, pass/fail, explanation, and a `severity` of `"blocking"` or
`"warning"`). `GradeReport.all_passed` only looks at blocking items —
this is what lets an unrecognized market produce an honest "I don't
know" warning instead of either a false pass or an unfair hard fail.

---

## 3. `brand_config.py` — visual + compliance tokens per brand

```python
BRAND_TOKENS = {
    "Dovato": { "primary": "#D4007A", "ae_report_line": "...", ... },
    ...
}
DEFAULT_TOKENS = { "ae_report_line": "[INSERT ... TBC ...]", ... }
```

Two things worth noticing:

1. **The AE reporting line is dictated, not generated.** The LLM is
   told to embed this string *verbatim*. That's the single most
   important design decision in the whole system — it means the
   Generator is never inventing a phone number or a reporting URL. It
   also means the Grader can check for an exact substring instead of
   asking "does this AE line sound plausible," which would be a much
   weaker check.
2. **`DEFAULT_TOKENS` uses `[TBC]`-style placeholders as the actual AE
   line.** For an unrecognized brand, the "real" AE line the LLM
   embeds verbatim literally says "TBC with local regulatory team."
   That's not a bug — an unknown brand *should* produce a visible TBC
   marker, not a confidently wrong guess.

---

## 4. `regulatory.py` — free-text interpretation layer

This is the file that exists specifically *because* you asked for text
inputs instead of dropdowns. Two functions:

```python
def resolve_market(market_text: str) -> dict:
    # "United Kingdom" → {"tags": ["ABPI"], "known": True, "aliases": [...]}
    # "Narnia"         → {"tags": [], "known": False, "aliases": [...]}

def is_hcp_audience(audience_text: str) -> bool:
    # "Prescribing nurses" → True (contains "nurse")
    # "Payers"             → False
```

**The word-boundary bug I caught and fixed while building this:** the
first version matched aliases with plain substring checks (`"us" in
text`). That's wrong — `"us"` is a substring of "foc**us**es" and
"disc**us**ses". Pharma copy about patient outcomes is full of words
like that. I switched every alias check to `\bword\b` regex matching.
I mention this because it's a good concrete example of why you test a
compliance tool against adversarial-ish input before trusting it — a
demo running only on the "happy path" (US market brief containing the
literal word "US") would never have surfaced this.

**Why unknown markets are `"warning"`, not silently `True` or a hard
`False`:** a silent pass would be actively dangerous (claiming ABPI
compliance for a market the tool has never heard of). A hard blocking
fail would punish the pipeline for something it's honestly uncertain
about, and would make "type a market not in the demo list" look like a
crash instead of a known limitation. Warning is the honest middle:
"I can't verify this — a human needs to look."

---

## 5. `llm_client.py` — Azure OpenAI only, no fallback

```python
class LLMClient:
    def __init__(self):
        if not (AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT):
            raise RuntimeError(...)  # no fallback provider — this is the only path
        self._client = AzureOpenAI(api_key=..., azure_endpoint=..., api_version=...)
```

This went through two real revisions worth knowing about:

**Revision 1 — the client class was wrong.** The first version pointed
plain `openai.OpenAI(base_url=...)` at an Azure endpoint, which works
for Azure AI Foundry's newer unified "models" endpoint (genuinely
OpenAI-wire-compatible) but not for a classic Azure OpenAI resource,
which requires an `api-version` query parameter on every request. The
actual credentials in use (`AZURE_OPENAI_API_KEY` /
`AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_API_VERSION`) are the classic
pattern, which needs `openai.AzureOpenAI` specifically — that class
handles the api-version plumbing automatically.

**Revision 2 — reasoning models need different parameters.** The
deployment is `gpt-5-mini`, a reasoning model. Reasoning models reject
`temperature` outright and require `max_completion_tokens` instead of
`max_tokens` — sending the wrong ones is a hard API error, not a
warning. `_is_reasoning_model()` is a small name-pattern check
(`"gpt-5" in name`, or matches `o1`/`o3`/`o4`-style names) that
switches which parameters get sent. It also sets
`reasoning_effort="low"`, because reasoning models spend hidden
"thinking" tokens before writing visible output — real cost that
never shows up as content — and a templated HTML draft doesn't need
deep deliberation.

**Revision 3 — the fallback chain itself got removed.** Earlier
versions of this file tried three things in order: a classic Azure
resource, then an Azure AI Foundry endpoint, then Anthropic, using
whichever env vars happened to be set. That's gone. There's exactly
one real credential this project uses, so `__init__` checks for
exactly that one, and raises immediately with a specific "these env
vars are missing" message if it's not there — no silent attempt at
something else. Same principle applied throughout `regulatory.py` and
`soft_review.py`: their LLM-call try/except blocks, which used to
catch a failed API call and return a fake "resolution failed" /
"review unavailable" result, got removed too. A failed call now raises
a real exception. See §15 for the full reasoning on why that
distinction (honest uncertainty vs. a hidden failure) matters.

`last_usage` is normalized to one shape (`input_tokens`,
`output_tokens`, and `cache_read_input_tokens` / `reasoning_tokens`
when Azure returns them) so `app.py`/`pipeline.py`'s logging code
doesn't need to know which provider answered — a smaller holdover from
when there were multiple providers to normalize between, kept because
it's still useful even with one.

---

## 6. `generator.py` — Loop 1

Two functions, `generate()` and `revise()`. The interesting part is
what `revise()` sends:

```python
def revise(brief, previous_html, grade_report, client):
    failed = grade_report.failed_items
    failure_list = "\n".join(f"- [{i.rule_id}] {i.label}: {i.detail}" for i in failed)
    # ...sends previous_html + failure_list, asks for a PATCH not a rewrite
```

It does **not** start from scratch on a failed attempt. It hands back
the exact previous draft plus only the specific rules that failed, and
asks for a patch. This matters for two reasons: it's cheaper (less to
regenerate), and it's more stable — a full regeneration risks fixing
the AE box while accidentally breaking the audience tag that passed
last time. Patch-not-rewrite is the same instinct as a real code
review: "fix these two comments" beats "rewrite the PR."

---

## 7. `grader.py` — Loop 2, and why it's not another LLM call

Nine rule functions, all with the identical signature
`(soup, raw_html, brief, tokens) -> GradeItem`, collected in
`ALL_RULES` and run in `grade()`. A few worth walking through:

**`_visible_body_text()`** — selects `.email-content`, then removes
any nested `.annotation-wrap` before extracting text. This is the
function that makes the branded/unbranded check meaningful: the brand
name is *allowed* to appear in the internal audit footer (production
team needs to know what they're building), just never in what a
recipient would actually read. I validated this against your real
`DOVATO-UK-EMAIL-2026-004.html` — it correctly found the file
unbranded (product name only in the annotation, never the visible
body) before I'd told it anything about that specific file.

**`rule_ae_box()`** checks three independent things — a real CSS
border, the phrase "adverse event," and the first 25 characters of the
brand's exact AE line — and only passes if all three hold. Checking
all three instead of just one avoids two failure modes: a model that
writes "please report adverse events" with no visible box (passes
text-search, fails visually), or a model that adds a border around
unrelated content (passes visually, says nothing useful).

**Why rules return an explanation string, not just a boolean.** A bare
`False` tells you something's wrong; `i.detail` tells a human
reviewer *what* and *where*, without them having to read the whole
HTML diff themselves. That detail string is also what gets fed back
into `revise()` — the Generator doesn't get "audience_tag: failed," it
gets "Body copy does not clearly state this is for UK healthcare
professionals only," which is specific enough to act on directly.

---

## 8. `pipeline.py` — wiring Loop 1 to Loop 2

```python
html = generate(brief, client)
report = grade(html, brief, tokens, iteration=1)
while not report.all_passed and iteration < MAX_ITERATIONS:
    iteration += 1
    html = revise(brief, html, report, client)
    report = grade(html, brief, tokens, iteration=iteration)
return PipelineResult(..., approved_for_production=False)
```

`MAX_ITERATIONS = 3` is a circuit breaker — without it, a
badly-specified brief (e.g. a brand token that contradicts the market)
could loop forever, burning API calls. Three is arbitrary but
reasonable: if a draft hasn't converged in three attempts, that's a
signal the *prompt* needs fixing, not that a fourth attempt would help
— which is exactly what `analyze_traces.py` is for.

`approved_for_production=False` is hard-coded, not computed from
`all_passed`. This is the one line in the whole codebase I'd flag as
non-negotiable: passing every structural check is not the same claim
as "an MLR reviewer signed off on the clinical accuracy and fair
balance of this specific copy." Never let a future version of this
script (or someone skimming it under deadline pressure) quietly wire
`all_passed` into an auto-send button.

---

## 9. `trace_logger.py` + `analyze_traces.py` — the lightweight Loop 4

Every grading pass appends one line of JSON — brand, market, audience,
iteration number, which rules failed — to `traces.jsonl`.
`analyze_traces.py` then aggregates: which rule fails most often on
*first* attempts, across every run you've ever done. That's a
prioritized, data-backed list of what to fix in
`prompts/generator_system.md` next, instead of guessing from the last
run you happened to look at. This is a lightweight version of what the
LangChain article calls the hill-climbing loop — real loop-engineering
setups usually pair this with an eval harness and scheduled re-runs;
this version is intentionally the minimum useful slice of that idea.

---

## 10. `app.py` — Streamlit UI

This went through two real versions. The first inlined its own
generate→grade→revise loop (duplicating `pipeline.py`'s logic) so it
could call `st.status()`/`ui_log()` after every individual step. The
current version doesn't do that anymore — it calls
`pipeline_langgraph.py`'s `build_graph().stream(...)` directly and
logs from the graph's own node updates as they arrive. Same
step-by-step visibility, but it comes from actually running the graph
engine instead of hand-written logging calls threaded through a
custom loop — which is the concrete version of the "LangGraph gives
you free incremental tracing" claim from §14, not just a description
of it. Soft review is a checkbox in the form, off by default, so
nothing costs an extra call unless explicitly requested.

---

## 11. `live-loop-demo.html` — the browser version, and where it differs from Python

This exists to prove the loop is real without you needing to export
credentials or run anything locally. It's a **faithful but scoped-down
port**, not a separate implementation:

| | Python (`grader.py`, `regulatory.py`) | Browser (`live-loop-demo.html`) |
|---|---|---|
| Grading logic | `BeautifulSoup` + regex | `DOMParser` + regex — same 11 rules, same word-boundary alias matching, ported 1:1 |
| Generator output | Full desktop+mobile split mockup, unbounded length | Compact single-column draft, hard-capped at 1000 output tokens (artifact sandbox limit) |
| LLM call | Your Azure OpenAI key, server-side, no fallback provider | Anthropic API, browser-side — a platform constraint of the artifact sandbox this demo runs in, not a choice made in this codebase; doesn't touch your Azure credentials at all |
| Persistence | `traces.jsonl` on disk | None — resets on refresh |
| UI feedback | Terminal `print()` / Streamlit `st.status()` | Live stepper (5 pipeline stages) + scrolling log with real token counts per call |

The reason the two can't be fully identical: an artifact-embedded API
call is capped at 1000 output tokens by the platform, and your actual
templates run 20–28KB of HTML. Cramming a full split-screen
desktop/mobile mockup into that budget isn't possible — so the
in-browser system prompt explicitly asks for a compact single view
instead. The *loop mechanics* (generate → grade → feed back specific
failures → regenerate) are identical; only the fidelity of what gets
generated differs.

**What "detailed logs" means in the updated version specifically:**
- A 5-stage stepper (`resolve → generate → grade → revise → verdict`)
  that highlights the currently-running stage.
- Every log line is timestamped, and includes real numbers from the
  API response (`input_tokens`/`output_tokens`/`stop_reason`) — those
  numbers don't exist unless a real model call happened.
- Brand-token and market resolution are logged explicitly *before* the
  first generation call, so you can see "Dovato → known token set" or
  "Narnia → unrecognized, reg_footer will be a warning" up front,
  rather than only finding out when a check fails later.
- The full system + user prompt sent on the final call is available in
  a collapsible panel, so you can see exactly what the model was asked
  for, not just what it returned.

---

## 12. A real bug caught via live testing: the truncation death spiral

Worth documenting because it's a good example of a failure mode that
only shows up under real constraints, not in a mock-based test.

**What happened:** running the live demo for real, every single call
(the first generation and both revisions) came back with
`stop_reason: max_tokens` — the model was hitting the artifact
sandbox's hard 1000-output-token cap and getting cut off mid-response,
every time. The original compact system prompt asked the model to
write the body copy and decoration first and the compliance footer
(DRAFT watermark, `[CL ID]`, AE box, regulatory tag) *last* — so when
the cap hit, exactly the checks that matter most were the ones that
never got written. Same 4 rules failed, identically, on all 3
attempts.

**Why the revision loop made it worse, not better:** the original
revision prompt said "here's the previous draft, patch only what's
needed, return the full corrected HTML." But the previous draft was
already truncated — possibly mid-tag — and "patch it, return the
full thing" forces the model to reproduce that same too-long structure
plus the fix, which hits the identical wall again. Three calls, same
failure, zero progress. That's also three calls' worth of tokens spent
confirming something the first call's `stop_reason` had already told
us.

**The fix, two parts:**
1. **Reorder by priority, not by natural writing order.** The system
   prompt now has an explicit "Part A / Part B" structure: every
   compliance-critical element (watermark, job code, regulatory tag,
   AE box, audience line) must be written *first*, tersely, before any
   headline or body copy. If a cutoff happens now, it can only ever
   lose decorative content, never a graded element.
2. **Stop patching truncated output — regenerate minimally instead.**
   `buildRevisionPrompt()` now checks `wasTruncated` (was the previous
   `stop_reason` `max_tokens`?). If so, it doesn't send the broken
   previous draft back for "patching" — it tells the model plainly
   that the previous attempt was cut off, shows a short snippet of
   where, and asks for a fresh, deliberately shorter attempt instead.

**A second, more general fix that came out of this:** a "stuck
detector" in both the live demo and `pipeline.py`/`app.py`. If the
exact same set of rules fails on two consecutive attempts, the loop
stops instead of spending a 3rd call on a strategy that's already
proven not to work twice. This isn't specific to the token-cap
scenario — an unrecognized, un-fixable prompt issue could produce the
same symptom even with an uncapped `max_tokens` in the real Python
pipeline, and there's no reason to pay for a 3rd identical failure to
find that out. Tested directly: a mock client that always returns the
same broken output now stops the pipeline after 2 calls instead of 3.

The lesson generalizes past this one bug: **`stop_reason` is a signal
you should always check, not just `usage.output_tokens`.** A response
that "succeeded" (200 status, valid JSON, no exception) can still be
silently incomplete, and silently-incomplete output feeding into
"patch this" instructions is exactly how you get a loop that looks
like it's iterating but is actually just re-failing the same way.

## 13. Why free text instead of dropdowns changes more than the UI

Converting market/audience/brand from `<select>`/enum to `<input
type="text">`/`str` looks like a UI change but touches four files:
`schema.py` (type change), `regulatory.py` (new — the resolution
layer didn't need to exist when inputs were closed enums),
`grader.py` (two rules rewritten to use the resolver instead of enum
equality), and `trace_logger.py` (dropped `.value` calls on fields
that are no longer enums). That cascade is normal — a closed set of
inputs lets you skip writing an interpretation layer; opening the
input back up means something has to do that interpretation, and it's
better for that something to be one small, testable module
(`regulatory.py`) than scattered `if "uk" in text.lower()` checks
throughout the codebase.

## 14. Dictionary → cache → LLM resolver, `GradingContext`, soft review, and the LangGraph version

Four connected changes, all from the same underlying question: *if
market/audience input is genuinely open-ended (not just UK/US/EU/Swiss
but "Ireland," "formulary committee," anything), can a static
dictionary really cover it — and if not, should the grader itself
become an AI agent?*

**Answer to the second half: no.** All 11 grader rules check objective
facts (a border exists, a string is present). Making the grader
agentic wouldn't add accuracy, it'd add cost and a self-grading
weakness. The real gap was one layer up, in *resolution*, not grading.

**The fix: `resolve_market()`/`resolve_audience()` now take an
optional `client`.** Three tiers, cheapest first:
1. Dictionary/keyword match (unchanged, free, instant).
2. `resolution_cache.json` — a flat JSON file keyed by normalized
   input string. Anything an LLM has resolved once gets cached forever
   (well, until you delete the file — see the Known gaps note in
   README.md about this having no eviction policy yet).
3. An LLM call, ONLY reached if the first two miss, using a strict
   "respond with only this JSON shape" system prompt
   (`_MARKET_LLM_SYSTEM`/`_AUDIENCE_LLM_SYSTEM`) that requires a
   `"confident": bool` field — an uncertain answer stays `known=False`
   rather than the resolver quietly guessing.

Tested directly (see the three-part test in this session): a known
market makes zero resolution calls; an unrecognized one makes exactly
one LLM call; the *same* unrecognized input on a completely separate
`run_pipeline()` call afterward makes zero new calls, reading from
disk instead.

**`GradingContext` exists because resolution now happens once, not
per-rule.** Before this change, 4 of the 11 grader rules each called
`resolve_market(brief.market)` independently — harmless when it was a
free dictionary lookup, but wasteful (or worse, a source of
inconsistent results) once resolution could involve a cached-but-still
non-trivial LLM round trip. Now `pipeline.py`/`pipeline_langgraph.py`
resolve market and audience exactly once at the start of a run, bundle
the result with brand tokens into a `GradingContext` dataclass, and
every rule function, `generate()`, and `revise()` all read from that
same resolved object. The grader's "zero LLM calls" guarantee is now
provable by inspection: nothing in `grader.py` imports anything that
could make a network call.

**`soft_review.py` is the actually-agentic verifier the article
describes** — for the subjective half of what a real MLR review checks
that no rule can: implied claims, whether "fair balance" is genuinely
balanced rather than technically present, tone. It's deliberately kept
out of `GradeReport` entirely (a separate `PipelineResult.soft_review_notes`
list) and only ever runs once, after every blocking rule already
passes — spending it on a structurally incomplete draft would be
pointless, and merging its output into the same list as the
deterministic rules would make a second AI's opinion look as
authoritative as a regex match, which it isn't.

**`pipeline_langgraph.py` — built once the shape actually changed.**
The earlier "no LangGraph" answer was for a 3-node loop; that was
correct at the time. This is now resolve → generate → grade →
soft_review with real conditional routing (loop back to generate, or
proceed to soft_review, decided by `route_after_grade()`), which is
where a graph-based orchestrator's value — declarative structure, and
step-by-step tracing via `.stream()` with no `ui_log()` calls threaded
by hand — starts to be worth the dependency. Critically, it does not
reimplement anything: every node (`node_resolve`, `node_generate`,
`node_grade`, `node_soft_review`) calls the exact same functions
`pipeline.py` does. The stuck-detector logic is duplicated (LangGraph
state updates don't mutate in place, so the "compare against the
*previous* iteration's failures, using the state value from *before*
this node's update" logic had to be written explicitly in
`node_grade()` rather than inherited from a shared loop) — that
duplication is the one real cost of maintaining both versions, called
out directly in README.md's Known gaps.

## 15. Removing every fallback-on-failure pattern

A late but important pass: going through every `except Exception` in
the codebase and asking, for each one, "does this hide a real failure
behind something that looks like a normal result?"

**What got removed, and why each one was actually a problem:**

- `llm_client.py` used to try three providers in sequence (classic
  Azure OpenAI → Azure AI Foundry → Anthropic) based on whichever env
  vars happened to be set. Harmless-looking, but it means a
  misconfigured primary credential doesn't fail — it silently runs on
  a *different* provider/model than you thought you were using. Now
  there's exactly one path, and it raises immediately if unconfigured.
- `regulatory.py`'s `_llm_resolve_market()` / `_llm_resolve_audience()`
  used to catch any exception from the API call and return a
  `MarketInfo`/`AudienceInfo` with `source="llm_error"` — structurally
  identical to a legitimate "unresolved" result. Downstream code (the
  grader, the generator prompt) couldn't tell "the AI said it doesn't
  know" apart from "the API call threw an exception." Those are very
  different situations — one is information, the other is an outage —
  and collapsing them into the same shape actively hid the second one.
- `soft_review.py` used to catch a failed call and return a
  `SoftReviewNote(concern="Soft review unavailable", ...)` — which,
  critically, still renders as a normal-looking advisory note in the
  UI. Someone skimming the output could easily read that as "the AI
  looked and found one minor thing," not "the AI never actually ran."
- `regulatory.py`'s cache read/write also lost its try/except. A
  corrupted `resolution_cache.json` or an unwritable disk used to
  silently degrade to "treat the cache as empty" — which means every
  future run silently pays for LLM calls it thinks it's caching but
  isn't, with no visible signal that caching stopped working at all.

**What deliberately did NOT change, because it isn't the same thing:**
`resolve_market(text, client=None)` — no client passed at all — still
returns an honest `known=False` result instead of raising, and a
*successful* LLM call that says `"confident": false` still resolves
the same way. Neither of those is a failure being papered over; both
are legitimate outcomes ("no AI lookup was requested" and "the AI
looked and genuinely doesn't know" are both real, valid answers). The
rule that ended up mattering: **degrading gracefully on an honest "I
don't know" is fine; degrading gracefully on "something broke" is
not** — the second one only ever looks safe, right up until it costs
you the ability to tell a real outage apart from normal operation.

**One exception that's a platform constraint, not a violation of this
rule:** `live-loop-demo.html` still calls the Anthropic API, because
the artifact sandbox it runs in only supports that — it's not part of
the actual Python pipeline, doesn't read your Azure credentials, and
isn't something this codebase chose. Everything under
`requirements.txt` / `pipeline_langgraph.py` / `app.py` is Azure-only
with no exceptions.
