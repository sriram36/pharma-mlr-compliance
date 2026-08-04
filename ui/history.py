import json
from pathlib import Path
from datetime import datetime
import pandas as pd
import streamlit as st

def load_draft_history():
    out_dir = Path("outputs")
    if not out_dir.exists():
        return []
    records = []
    for jf in sorted(out_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            records.append(json.loads(jf.read_text(encoding="utf-8")))
        except Exception:
            continue
    return records

def render_recent_drafts():
    st.markdown('<div class="history-heading">📋 Recent Drafts</div>', unsafe_allow_html=True)
    records = load_draft_history()
    if not records:
        st.caption("No drafts generated yet — your history will appear here after your first run.")
        return
    df = pd.DataFrame(records)
    df = df.rename(columns={
        "id": "ID", "channel": "Channel", "type": "Type", "market": "Market",
        "audience": "Audience", "objective": "Objective", "compliance": "Compliance",
        "status": "Status", "iterations": "Iterations", "created_at": "Created At",
    })
    display_cols = ["ID", "Channel", "Type", "Market", "Audience", "Objective",
                     "Compliance", "Status", "Iterations", "Created At"]
    display_cols = [c for c in display_cols if c in df.columns]
    st.dataframe(df[display_cols].head(10), use_container_width=True, hide_index=True)

def save_draft_metadata(brief, report, iteration, elapsed, output_filename, passed, failed, warned, total):
    out_dir = Path("outputs")
    out_dir.mkdir(exist_ok=True)
    existing = list(out_dir.glob("*.json"))
    draft_id = f"#{1200 + len(existing) + 1}"
    meta = {
        "id": draft_id,
        "channel": brief.channel.value if hasattr(brief.channel, "value") else brief.channel,
        "type": brief.email_type.value if brief.email_type and hasattr(brief.email_type, "value") else (brief.email_type or "-"),
        "market": brief.market,
        "audience": brief.audience,
        "brand": brief.brand,
        "objective": brief.objective,
        "classification": brief.classification.value if hasattr(brief.classification, "value") else brief.classification,
        "status": "Draft" if report.all_passed else "Blocked",
        "compliance": f"{passed}/{total}",
        "iterations": iteration,
        "time_taken": f"{elapsed:.1f}s",
        "created_at": datetime.now().strftime("%b %d, %Y %I:%M %p"),
        "html_file": output_filename,
    }
    meta_path = out_dir / f"{Path(output_filename).stem}.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta
