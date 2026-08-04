import base64
import streamlit as st
from core.schema import CampaignBrief, Channel, EmailType, ContentClassification

def render_sidebar() -> tuple[CampaignBrief | None, bool]:
    with st.sidebar:
        st.markdown("## ⚙️ Campaign Configuration")

        with st.form("brief_form"):
            channel = st.selectbox("📡 Channel", [c.value for c in Channel], help="Structural switch — changes layout target.")
            email_type = st.selectbox("✉️ Email type", [e.value for e in EmailType]) if channel == "email" else None

            st.divider()
            market = st.text_input("🌍 Market", "UK", help="E.g., UK, US, EU. Unknowns fall back to AI classification.")
            audience = st.text_input("👥 Audience", "HCP", help="E.g., HCP, Patient.")
            brand = st.text_input("💊 Brand", "Dovato", help="Known: Dovato, Nucala, Trelegy, Shingrix.")
            classification = st.selectbox("🏷️ Classification", [c.value for c in ContentClassification])

            st.divider()
            objective = st.text_area("🎯 Objective", "Pre-launch HIV treatment awareness", height=80)
            uploaded_files = st.file_uploader("📎 Upload images (optional)", accept_multiple_files=True, type=["png", "jpg", "jpeg", "gif"])
            run_soft = st.checkbox("🔍 Run soft review (AI)", value=True, help="Runs 1 extra subjective AI call if structural checks pass.")

            submitted = st.form_submit_button("Generate Draft 🚀", use_container_width=True)

    if submitted:
        image_map = {}
        if uploaded_files:
            for f in uploaded_files:
                b64 = base64.b64encode(f.read()).decode("utf-8")
                image_map[f.name] = f"data:{f.type};base64,{b64}"

        brief = CampaignBrief(
            channel=Channel(channel),
            email_type=EmailType(email_type) if email_type else None,
            market=market,
            audience=audience,
            brand=brand,
            objective=objective,
            classification=ContentClassification(classification),
            uploaded_images=image_map
        )
        return brief, run_soft
        
    return None, False
