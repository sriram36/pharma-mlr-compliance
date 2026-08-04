"""
Human-in-the-Loop MLR Review Workspace.

Provides pharmaceutical regulatory officers, legal reviewers, and medical directors
with a dedicated interface to inspect, audit, annotate, approve, or request revisions
for generated campaign drafts.
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List

import streamlit as st
import streamlit.components.v1 as components

from core.schema import CampaignBrief, Channel, EmailType, ContentClassification, Severity
from pipeline.pipeline_langgraph import build_graph
from ui.dashboard import highlight_flagged_claims, render_status_card
from ui.history import load_draft_history


def update_draft_status(
    json_path: Path,
    new_status: str,
    reviewer_name: str,
    comment: str,
) -> Dict[str, Any]:
    """Updates the JSON sidecar with the human reviewer's verdict and audit trail."""
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["status"] = new_status
    data["reviewed_by"] = reviewer_name
    data["reviewer_comment"] = comment
    data["reviewed_at"] = datetime.now().strftime("%b %d, %Y %I:%M %p")
    data["history_log"] = data.get("history_log", [])
    data["history_log"].append({
        "timestamp": datetime.now().isoformat(),
        "action": new_status,
        "reviewer": reviewer_name,
        "comment": comment,
    })
    json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def render_review_panel():
    st.markdown("### ⚖️ Medical-Legal-Regulatory (MLR) Human Review Portal")
    st.caption("Inspect generated campaign assets, review compliance audit items, and execute formal sign-offs or revision requests.")

    out_dir = Path("outputs")
    if not out_dir.exists():
        st.info("No generated drafts found. Generate a draft in the Drafting tab to start review.")
        return

    json_files = sorted(list(out_dir.glob("*.json")), key=lambda p: p.stat().st_mtime, reverse=True)
    if not json_files:
        st.info("No draft metadata records found in `outputs/`.")
        return

    draft_options = {}
    for jf in json_files:
        try:
            d = json.loads(jf.read_text(encoding="utf-8"))
            draft_id = d.get("id", jf.stem)
            brand = d.get("brand", "Unknown")
            market = d.get("market", "")
            status = d.get("status", "Draft")
            draft_options[f"{draft_id} — {brand} ({market}) [{status}]"] = jf
        except Exception:
            continue

    if not draft_options:
        st.warning("Could not parse draft records.")
        return

    col_sel, col_stat = st.columns([3, 1])
    with col_sel:
        selected_label = st.selectbox("Select Draft for Review", list(draft_options.keys()))
    selected_json_path = draft_options[selected_label]
    draft_data = json.loads(selected_json_path.read_text(encoding="utf-8"))

    html_file = selected_json_path.with_suffix(".html")
    if not html_file.exists():
        # Fallback to html_file field in metadata
        html_name = draft_data.get("html_file")
        if html_name and (out_dir / html_name).exists():
            html_file = out_dir / html_name

    raw_html = html_file.read_text(encoding="utf-8") if html_file.exists() else "<!-- HTML file missing -->"

    # Status summary strip
    status = draft_data.get("status", "Draft")
    with col_stat:
        if status == "Approved":
            st.success(f"✅ Approved for Production\nBy: {draft_data.get('reviewed_by', 'MLR Officer')}")
        elif status == "Rejected":
            st.error(f"❌ Rejected\nBy: {draft_data.get('reviewed_by', 'MLR Officer')}")
        elif status == "Under Revision":
            st.warning("🔄 Revision Requested")
        else:
            st.info(f"⏳ Pending Review\nCompliance: {draft_data.get('compliance', 'N/A')}")

    st.markdown("---")

    # Dual Column: Left Preview, Right Audit & Decision
    left_col, right_col = st.columns([1, 1], gap="large")

    with left_col:
        st.markdown("#### 📱 Rendered Asset Preview")
        components.html(raw_html, height=650, scrolling=True)

    with right_col:
        st.markdown("#### 📋 Regulatory Audit & Metadata")
        
        # Meta chips
        st.markdown(
            f"""
            <div style="display:flex; gap:10px; flex-wrap:wrap; margin-bottom:15px;">
                <span style="background:#2a2d3d; padding:4px 8px; border-radius:4px;">🏷️ <b>Brand:</b> {draft_data.get('brand')}</span>
                <span style="background:#2a2d3d; padding:4px 8px; border-radius:4px;">🌍 <b>Market:</b> {draft_data.get('market')}</span>
                <span style="background:#2a2d3d; padding:4px 8px; border-radius:4px;">👥 <b>Audience:</b> {draft_data.get('audience')}</span>
                <span style="background:#2a2d3d; padding:4px 8px; border-radius:4px;">🔄 <b>Iterations:</b> {draft_data.get('iterations', 1)}</span>
            </div>
            """,
            unsafe_allow_html=True
        )

        st.markdown(f"**Campaign Objective:** {draft_data.get('objective', 'N/A')}")

        if draft_data.get("reviewer_comment"):
            st.markdown(f"**Previous Reviewer Comment:** *\"{draft_data.get('reviewer_comment')}\"*")

        st.markdown("---")
        st.markdown("#### ✍️ Human Decision Panel")

        with st.form(key=f"review_form_{draft_data.get('id')}"):
            reviewer_name = st.text_input("Reviewer Full Name & Credentials", value=draft_data.get("reviewed_by", "Dr. Regulatory Reviewer, PharmD"))
            decision = st.radio(
                "Compliance Verdict",
                options=["Approve for Production", "Reject with Feedback", "Request Revision"],
                index=0 if status != "Rejected" else 1,
            )
            review_comment = st.text_area(
                "Reviewer Audit Log / Justification Notes",
                placeholder="Enter mandatory MLR rationale, fair-balance verification notes, or revision instructions...",
                height=100,
            )
            submit_btn = st.form_submit_button("Record MLR Decision")

            if submit_btn:
                if not reviewer_name.strip():
                    st.error("Reviewer name is required for formal compliance sign-off.")
                else:
                    new_st = "Approved" if decision == "Approve for Production" else ("Rejected" if decision == "Reject with Feedback" else "Under Revision")
                    updated = update_draft_status(selected_json_path, new_st, reviewer_name, review_comment)
                    st.success(f"Audit decision recorded: **{new_st}** by {reviewer_name}")
                    st.rerun()

        # Display history audit log if available
        if draft_data.get("history_log"):
            with st.expander("📜 Audit Trail History", expanded=False):
                for entry in draft_data.get("history_log", []):
                    st.caption(f"**{entry.get('timestamp')}** — `{entry.get('action')}` by *{entry.get('reviewer')}*: {entry.get('comment')}")
