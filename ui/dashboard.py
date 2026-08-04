import re
import streamlit as st
from core.schema import Severity

def highlight_flagged_claims(html: str, report) -> str:
    highlighted = html
    for item in report.items:
        if item.passed:
            continue
        css_class = "mlr-flag-fail" if item.severity == Severity.BLOCKING else "mlr-flag-warn"
        quotes = re.findall(r'"([^"\n]{3,80})"', item.detail or "")
        for q in quotes:
            if q and q in highlighted:
                highlighted = highlighted.replace(
                    q, f'<mark class="{css_class}" title="{item.label}">{q}</mark>', 1
                )
    style_snippet = """
    <style>
    mark.mlr-flag-fail{background:rgba(244,63,94,0.25);color:#f43f5e;padding:0 2px;border-radius:3px;border-bottom:2px solid #f43f5e;}
    mark.mlr-flag-warn{background:rgba(245,158,11,0.25);color:#f59e0b;padding:0 2px;border-radius:3px;border-bottom:2px solid #f59e0b;}
    </style>
    """
    return style_snippet + highlighted

def render_verification_diff(snapshot: dict[str, list[str]]) -> None:
    if not snapshot:
        return
    rows = []
    if snapshot.get("rectified_rules"):
        rows.append(("Rectified", snapshot["rectified_rules"], "delta-pass"))
    if snapshot.get("still_failing"):
        rows.append(("Still failing", snapshot["still_failing"], "delta-warn"))
    if snapshot.get("new_failures"):
        rows.append(("New failures", snapshot["new_failures"], "delta-fail"))
    if not rows:
        st.markdown("*No rule changes detected in this iteration.*")
        return
    table_rows = "".join(
        f"<tr><th>{label}</th><td class='delta-cell {cls}'>{', '.join(values)}</td></tr>"
        for label, values, cls in rows
    )
    st.markdown(f"""
    <table class="delta-grid">
        {table_rows}
    </table>
    """, unsafe_allow_html=True)

def render_status_card(placeholder, title: str, status: str = "running", detail: str = ""):
    if status == "running":
        type_class = "status-info"
    elif status == "success":
        type_class = "status-pass"
    elif status == "warn":
        type_class = "status-warn"
    elif status == "error":
        type_class = "status-fail"
    else:
        type_class = "status-pass"
    placeholder.markdown(f"""
    <div class="status-card {type_class}" style="padding:1rem; margin-bottom:1rem;">
        <strong>{title}</strong>
        <div style="color:#8b949e; margin-top:0.35rem;">{detail}</div>
    </div>
    """, unsafe_allow_html=True)
