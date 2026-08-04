"""
Streamlit UI — runs on pipeline_langgraph.py's graph, not the plain
pipeline.py loop. Uses graph.stream() to get a live update after every
node (resolve / generate / grade / soft_review) with zero manual
ui_log() plumbing inside the loop logic itself — that per-step
visibility is what LangGraph gives you for free versus the plain
version, and this file is where that actually gets used, not just
demonstrated in a CLI print statement.

Features:
1. Multi-tab workflow: Drafting Studio, Human MLR Review & Sign-Off, Archive & Analytics.
2. Draft preview with inline-highlighting for flagged/warned claims.
3. Audit results grouped by severity: Blocking Failures / Warnings / Passed checks.
4. Iteration History visualizer with pass/fail deltas across retries.
5. JSON sidecar metadata persistence for comprehensive audit trails.
"""

import textwrap
import time
from datetime import datetime
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from core.llm_client import LLMClient
from core.schema import Severity
from pipeline.pipeline_langgraph import build_graph
from ui.dashboard import highlight_flagged_claims, render_status_card, render_verification_diff
from ui.history import render_recent_drafts, save_draft_metadata
from ui.review import render_review_panel
from ui.sidebar import render_sidebar

st.set_page_config(
    page_title="Pharma MLR Compliance & Drafting Suite",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Premium Dark-Mode CSS ---
def load_css(file_path: Path) -> None:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except FileNotFoundError:
        st.warning(f"CSS file not found: {file_path}")

load_css(Path(__file__).parent / "assets/style.css")


# --- Hero Header ---
st.markdown("""
<div class="hero-header">
    <h1>🧬 Pharma MLR Compliance & Drafting Suite</h1>
    <p>
        Generates draft multi-channel campaign assets with deterministic compliance grading,
        advisory soft review, and integrated Human-in-the-Loop MLR regulatory sign-off.
    </p>
</div>
""", unsafe_allow_html=True)


tab_draft, tab_review, tab_archive = st.tabs([
    "✍️ Campaign Drafting & Generation",
    "⚖️ Human MLR Review & Sign-Off",
    "📋 Compliance Archive & Analytics",
])

with tab_review:
    render_review_panel()

with tab_archive:
    render_recent_drafts()

with tab_draft:
    brief, run_soft = render_sidebar()

    if brief is None:
        st.info("👈 Configure your campaign parameters in the sidebar and click **Generate Draft** to begin.")
    else:
        status_card = st.empty()
        pipeline_log = st.empty()
        node_icons = {"resolve": "🔍", "generate": "✨", "grade": "🛡️", "soft_review": "💬"}

        render_status_card(status_card, "🧠 Running LangGraph pipeline...", "running")
        pipeline_steps = []
        iteration_history = []  # tracks pass/fail/warn counts across retries
        prev_failed_items = []
        current_iteration = 0

        def render_pipeline_log() -> None:
            rendered = [
                "<div style='margin-bottom:0.75rem; font-weight:700; color:#e6edf3;'>🔁 Verification Loop</div>"
            ]
            for node, msg, timestamp in pipeline_steps:
                icon = node_icons.get(node, "→")
                time_label = datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")
                rendered.append(textwrap.dedent(f"""<div class="pipeline-step step-{node}">
                    <div class="step-icon">{icon}</div>
                    <div class="step-content">
                        <span>{msg}</span>
                        <span class="log-timestamp">{time_label}</span>
                    </div>
                </div>""").strip())
            pipeline_log.markdown("".join(rendered), unsafe_allow_html=True)

        def ui_log(msg: str, node: str = ""):
            """Log a pipeline step with styled output."""
            pipeline_steps.append((node, msg, time.time()))
            render_pipeline_log()

        try:
            client = LLMClient()
        except RuntimeError as e:
            render_status_card(status_card, "❌ Configuration Error", "error", "Missing Azure OpenAI credentials or incorrect configuration.")
            st.error(str(e))
            st.stop()

        t0 = time.time()
        graph = build_graph()
        final_state = {}

        ui_log(f"Soft review: {'**ON**' if run_soft else '**OFF**'}", "resolve")

        try:
            for step in graph.stream({
                "brief": brief, "client": client, "run_soft_review": run_soft,
                "iteration": 0, "prev_failed_ids": None,
            }):
                node_name = list(step.keys())[0]
                update = step[node_name]
                final_state.update(update)

                if node_name == "resolve":
                    mi, ai = update["market_info"], update["audience_info"]
                    ui_log(f"Market → **{mi.body_name}** (source: {mi.source})", "resolve")
                    ui_log(f"Audience → **{'HCP' if ai.is_hcp else 'not HCP'}** (source: {ai.source})", "resolve")
                    render_status_card(status_card, "🧠 Resolution complete", "running", "Resolved market and audience parameters.")

                elif node_name == "generate":
                    current_iteration = update.get("iteration", final_state.get("iteration", 0) + 1)
                    usage = client.last_usage or {}
                    if current_iteration == 1:
                        render_status_card(status_card, f"✨ Generation {current_iteration} complete", "running", "Now verifying the first draft against compliance rules.")
                        ui_log(f"First draft generated (attempt {current_iteration}) — {usage.get('input_tokens','?')} in / {usage.get('output_tokens','?')} out tokens", "generate")
                    else:
                        failed_ids = [item.rule_id for item in prev_failed_items]
                        render_status_card(status_card, f"✨ Revision {current_iteration} complete", "running", f"Draft revised to address {len(failed_ids)} previously failed rule(s). Verifying again.")
                        ui_log(f"Revised draft generated (attempt {current_iteration}) — fixing {', '.join(failed_ids)}", "generate")

                elif node_name == "grade":
                    report = update["grade_report"]
                    current_iteration = final_state.get("iteration", 0)
                    failed_items = [i for i in report.failed_items if i.severity == Severity.BLOCKING]
                    warn_items = [i for i in report.items if not i.passed and i.severity == Severity.WARNING]
                    failed_rules = [i.rule_id for i in failed_items]
                    warn_rules = [i.rule_id for i in warn_items]
                    snap_passed = sum(1 for i in report.items if i.passed)
                    snap_failed = len(failed_rules)
                    snap_warned = len(warn_rules)
                    prior_failed_ids = [item.rule_id for item in prev_failed_items]
                    rectified_rules = [rule for rule in prior_failed_ids if rule not in failed_rules]
                    still_failing = [rule for rule in failed_rules if rule in prior_failed_ids]
                    new_failures = [rule for rule in failed_rules if rule not in prior_failed_ids]
                    iteration_history.append({
                        "attempt": current_iteration,
                        "passed": snap_passed, "failed": snap_failed, "warned": snap_warned,
                        "failed_rules": failed_rules,
                        "new_failures": new_failures,
                        "still_failing": still_failing,
                        "rectified_rules": rectified_rules,
                        "concepts": [
                            {"rule_id": it.rule_id, "passed": it.passed, "label": it.label, "detail": it.detail}
                            for it in report.items
                        ],
                    })
                    prev_failed_items = failed_items
                    if report.all_passed:
                        render_status_card(status_card, f"✅ Generation {current_iteration} passed", "success", "All deterministic blocking checks passed. Soft review will run if enabled.")
                        ui_log(f"Generation {current_iteration} passed all blocking checks.", "grade")
                    else:
                        render_status_card(status_card, f"❌ Generation {current_iteration} failed", "error", f"Failed rules: {', '.join(failed_rules)}")
                        ui_log(f"Generation {current_iteration} failed {snap_failed} blocking rule(s) and {snap_warned} warning(s).", "grade")
                        if rectified_rules or still_failing or new_failures:
                            sections = []
                            if rectified_rules:
                                sections.append(f"<div><strong>Rectified from prior attempt:</strong> {', '.join(rectified_rules)}</div>")
                            if still_failing:
                                sections.append(f"<div><strong>Still failing:</strong> {', '.join(still_failing)}</div>")
                            if new_failures:
                                sections.append(f"<div><strong>New failures this iteration:</strong> {', '.join(new_failures)}</div>")
                            pipeline_log.markdown(textwrap.dedent(f"""<div style='padding:0.65rem 1rem; border-radius:10px; background:#0f172a; margin:0.5rem 0;'>
                                {''.join(sections)}
                            </div>""").strip(), unsafe_allow_html=True)
                    if update.get("stuck"):
                        ui_log("⚠️ Repeated failure detected — stopping iteration early.", "grade")

                elif node_name == "soft_review":
                    notes = update.get("soft_review_notes", [])
                    ui_log(f"**{len(notes)}** advisory note(s)" if notes else "No concerns flagged ✓", "soft_review")
                    render_status_card(status_card, "💬 Soft review complete", "running", f"Soft review produced {len(notes)} advisory note(s).")

        except Exception as e:
            render_status_card(status_card, "❌ Pipeline Error", "error", "Pipeline failed with an error. See the message below.")
            st.error(f"Pipeline failed with an error:\n\n```\n{type(e).__name__}: {e}\n```\n\nCheck your Azure credentials, network connection, and API quota.")
            st.stop()

        elapsed = time.time() - t0
        report = final_state.get("grade_report")
        if not report:
            st.error("No grade report returned by pipeline.")
            st.stop()

        summary_title = f"{'✅' if report.all_passed else '⚠️'} Done — {final_state.get('iteration', 1)} iteration(s), {elapsed:.1f}s"
        summary_detail = "This draft passed all blocking checks." if report.all_passed else "This draft has blocking/warning issues and is not ready for distribution."
        render_status_card(status_card, summary_title, "success" if report.all_passed else "error", summary_detail)

        # --- Metrics Summary ---
        passed_count = sum(1 for i in report.items if i.passed)
        failed_count = sum(1 for i in report.items if not i.passed and i.severity == Severity.BLOCKING)
        warn_count = sum(1 for i in report.items if not i.passed and i.severity == Severity.WARNING)
        total = len(report.items) if report.items else 1

        st.markdown(f"""
        <div class="metric-row">
            <div class="metric-card metric-pass">
                <div class="metric-value">{passed_count}</div>
                <div class="metric-label">Passed</div>
            </div>
            <div class="metric-card metric-fail">
                <div class="metric-value">{failed_count}</div>
                <div class="metric-label">Failed</div>
            </div>
            <div class="metric-card metric-warn">
                <div class="metric-value">{warn_count}</div>
                <div class="metric-label">Warnings</div>
            </div>
            <div class="metric-card metric-iter">
                <div class="metric-value">{final_state.get('iteration', 1)}</div>
                <div class="metric-label">Iterations</div>
            </div>
            <div class="metric-card metric-time">
                <div class="metric-value">{elapsed:.1f}s</div>
                <div class="metric-label">Total Time</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # --- Display Results in Tabs ---
        tab_preview, tab_audit, tab_code = st.tabs(["👁️ Live Preview", "🛡️ Audit & Grades", "💻 Raw Source"])

        html_raw = final_state.get("html", "")
        html_preview = html_raw
        for fname, data_uri in brief.uploaded_images.items():
            html_preview = html_preview.replace(f"uploaded:{fname}", data_uri)

        with tab_preview:
            st.subheader("Rendered HTML Draft")
            if not report.all_passed:
                st.error("⚠️ This draft failed blocking compliance checks. It is **NOT** ready for distribution.")

            preview_with_flags = highlight_flagged_claims(html_preview, report)
            components.html(preview_with_flags, height=800, scrolling=True)

            # Auto-save to outputs directory
            output_filename = f"{brief.market}_{brief.audience}_{brief.brand}_{brief.channel}_{brief.classification}.html".replace(" ", "_").lower()
            output_path = Path("outputs") / output_filename
            output_path.parent.mkdir(exist_ok=True)
            output_path.write_text(html_raw, encoding="utf-8")

            # Persist metadata sidecar
            meta = save_draft_metadata(
                brief, report, final_state.get("iteration", 1), elapsed, output_filename,
                passed_count, failed_count, warn_count, total,
            )
            st.success(f"💾 Saved to `{output_path}` (ID {meta['id']})")
            st.download_button("📥 Download HTML", data=html_preview, file_name=output_filename, mime="text/html")

        with tab_audit:
            st.subheader(f"Compliance Audit Report — Attempt {final_state.get('iteration', 1)}")

            if len(iteration_history) > 1:
                st.markdown("##### 🔁 Iteration History")
                cols = st.columns(len(iteration_history))
                for idx, snap in enumerate(iteration_history):
                    with cols[idx]:
                        st.metric(f"Attempt {snap['attempt']}", f"{snap['passed']} ✓ {snap['failed']} ✗ {snap['warned']} ⚠")
                st.caption("Each attempt regenerates the draft and re-runs the deterministic grader until it passes or the retry limit is hit.")

                for snap in iteration_history:
                    with st.expander(f"Attempt {snap['attempt']} — {snap['passed']} ✓ {snap['failed']} ✗ {snap['warned']} ⚠", expanded=False):
                        if snap["rectified_rules"] or snap["still_failing"] or snap["new_failures"]:
                            render_verification_diff(snap)

                        checklist_html = []
                        for c in snap.get("concepts", []):
                            icon = "✅" if c["passed"] else "❌"
                            cls = "delta-pass" if c["passed"] else "delta-fail"
                            checklist_html.append(f"<div style='margin:0.25rem 0;'><strong>{icon} {c['rule_id']}</strong> — <span class='delta-cell {cls}'>{c['label']}</span><div style='color:#94a3b8;margin-left:1rem;font-size:0.9rem'>{c['detail']}</div></div>")
                        st.markdown("".join(checklist_html), unsafe_allow_html=True)

            progress_val = passed_count / total if total else 0
            st.progress(progress_val, text=f"{passed_count} / {total} Checks Passed")

            def render_item(item):
                icon = "✅" if item.passed else ("⚠️" if item.severity == Severity.WARNING else "❌")
                status_class = "status-pass" if item.passed else ("status-warn" if item.severity == Severity.WARNING else "status-fail")
                st.markdown(f"""
                <div class="status-card {status_class}">
                    <strong>{icon} {item.label}</strong>
                    <span class="card-detail">{item.detail}</span>
                </div>
                """, unsafe_allow_html=True)

            blocking_items = [i for i in report.items if not i.passed and i.severity == Severity.BLOCKING]
            warning_items = [i for i in report.items if not i.passed and i.severity == Severity.WARNING]
            passed_items = [i for i in report.items if i.passed]

            if blocking_items:
                with st.expander(f"❌ Blocking Failures ({len(blocking_items)})", expanded=True):
                    for item in blocking_items:
                        render_item(item)

            if warning_items:
                with st.expander(f"⚠️ Warnings ({len(warning_items)})", expanded=True):
                    for item in warning_items:
                        render_item(item)

            with st.expander(f"✅ Passed Checks ({len(passed_items)})", expanded=False):
                for item in passed_items:
                    render_item(item)

            notes = final_state.get("soft_review_notes", [])
            if notes:
                st.markdown("---")
                st.subheader("💬 Soft Review Advisory (AI)")
                st.caption("These are a second AI's opinion — advisory only, never verified findings.")
                for n in notes:
                    st.markdown(f"""
                    <div class="advisory-note">
                        <strong>{n.concern}</strong>
                        <div class="advisory-detail">{n.detail}</div>
                    </div>
                    """, unsafe_allow_html=True)

        with tab_code:
            st.subheader("Raw Generated Code")
            st.code(html_raw, language="html")
