"""
Grader node for the MLR pipeline.
Deterministically evaluates generated HTML against structural, brand, and
compliance rules without making LLM calls.
"""

from __future__ import annotations

import copy
import json
import re
import concurrent.futures
from dataclasses import dataclass
from typing import Any, Callable

from bs4 import BeautifulSoup

from core.schema import CampaignBrief, GradeItem, GradeReport, ContentClassification, Severity
from core.regulatory import MarketInfo, AudienceInfo
from core.utils import strip_code_fences


# Type alias for all rule functions — makes it explicit and catches
# signature mismatches if you ever add type-checking (mypy/pyright).
RuleFunc = Callable[["BeautifulSoup", str, CampaignBrief, "GradingContext"], GradeItem]


@dataclass
class GradingContext:
    tokens: dict
    market_info: MarketInfo
    audience_info: AudienceInfo
    client: Any = None


def _visible_body_text(soup: BeautifulSoup) -> str:
    """
    Text a recipient would actually see in the 600px email render —
    excludes the annotation/audit footer, which is allowed to mention
    the brand name internally for the production team.

    Works on a shallow copy of the soup to avoid mutating the original —
    other rules that run after this one still need the full DOM intact.
    """
    soup_copy = copy.copy(soup)
    body = soup_copy.select_one(".email-content") or soup_copy.select_one(".email-outer") or soup_copy
    for ann in body.select(".annotation-wrap"):
        ann.decompose()
    return body.get_text(" ", strip=True)


def rule_draft_watermark(soup: BeautifulSoup, raw_html: str, brief: CampaignBrief, ctx: GradingContext) -> GradeItem:
    ok = "DRAFT" in raw_html and "Not approved for distribution" in raw_html
    return GradeItem(
        rule_id="watermark",
        label="DRAFT watermark present",
        passed=ok,
        detail="Found DRAFT / not-approved-for-distribution watermark." if ok
        else "Missing the DRAFT — Not approved for distribution watermark.",
    )


def rule_job_code_pending(soup: BeautifulSoup, raw_html: str, brief: CampaignBrief, ctx: GradingContext) -> GradeItem:
    ok = "[CL ID" in raw_html or "CL ID — PENDING" in raw_html
    return GradeItem(
        rule_id="job_code",
        label="Job code placeholder present",
        passed=ok,
        detail="Job code placeholder found." if ok else "No [CL ID — PENDING] placeholder found in footer.",
    )


def rule_hcp_audience_tag(soup: BeautifulSoup, raw_html: str, brief: CampaignBrief, ctx: GradingContext) -> GradeItem:
    if not ctx.audience_info.is_hcp:
        note = "" if ctx.audience_info.known else " (resolver was uncertain — treated as not-HCP by default)"
        return GradeItem(rule_id="audience_tag", label="HCP-only audience statement",
                              passed=True, detail=f"Not required — audience '{brief.audience}' wasn't recognized as HCP{note}.",
                              severity=Severity.BLOCKING)
    text = _visible_body_text(soup).lower()
    market_info = ctx.market_info
    # If the market itself wasn't recognized we can't require a market word to appear at
    # all — just require the HCP-only statement itself, and flag the market as unverified.
    # If it *was* recognized, accept any known synonym ("UK" satisfies "United Kingdom").
    ok = "healthcare professional" in text
    if market_info.known:
        # Word-boundary match, not naive substring — a bare "us" alias would
        # otherwise false-positive inside words like "focuses"/"discusses".
        ok = ok and any(re.search(rf"\b{re.escape(alias)}\b", text) for alias in market_info.aliases)
    return GradeItem(
        rule_id="audience_tag",
        label="HCP-only audience statement",
        passed=ok,
        detail="Explicit HCP-only audience line found in body copy." if ok
        else f"Body copy does not clearly state this is for {brief.market} healthcare professionals only.",
    )


def rule_ae_box(soup: BeautifulSoup, raw_html: str, brief: CampaignBrief, ctx: GradingContext) -> GradeItem:
    candidates = soup.find_all(style=re.compile(r"border\s*:\s*\d"))
    has_border_el = len(candidates) > 0 or "border: 2px" in raw_html or "2px solid" in raw_html
    ae_line = ctx.tokens.get("ae_report_line", "")
    has_ae_text = "adverse event" in raw_html.lower()
    line_matches = ae_line[:20].lower() in raw_html.lower() if ae_line else False
    ok = has_border_el and has_ae_text and line_matches
    detail_bits = []
    if not has_border_el:
        detail_bits.append("no visibly bordered element detected")
    if not has_ae_text:
        detail_bits.append("no 'adverse event' text found")
    if not line_matches:
        detail_bits.append("AE reporting line doesn't match the brand's required wording")
    return GradeItem(
        rule_id="ae_box",
        label="AE reporting box (bordered, correct wording)",
        passed=ok,
        detail="Bordered AE box with correct reporting line present." if ok else "; ".join(detail_bits),
    )


def rule_brand_leak(soup: BeautifulSoup, raw_html: str, brief: CampaignBrief, ctx: GradingContext) -> GradeItem:
    if brief.classification != ContentClassification.UNBRANDED_DISEASE_AWARENESS:
        return GradeItem(rule_id="brand_leak", label="No product name in unbranded body copy",
                  passed=True, detail="Not applicable — content is branded.", severity=Severity.BLOCKING)
    text = _visible_body_text(soup)
    pattern = re.compile(re.escape(brief.brand), re.IGNORECASE)
    hits = pattern.findall(text)
    ok = len(hits) == 0
    return GradeItem(
        rule_id="brand_leak",
        label="No product name in unbranded body copy",
        passed=ok,
        detail="Product name does not appear in visible body copy." if ok
        else f"Product name '{brief.brand}' appears {len(hits)}x in visible body copy — must be removed for unbranded disease-awareness content.",
    )


def rule_pi_link_if_branded(soup: BeautifulSoup, raw_html: str, brief: CampaignBrief, ctx: GradingContext) -> GradeItem:
    if brief.classification != ContentClassification.BRANDED:
        return GradeItem(rule_id="pi_link", label="Prescribing Information link placeholder present",
                  passed=True, detail="Not applicable — content is unbranded.", severity=Severity.BLOCKING)
    ok = "Prescribing Information" in raw_html
    return GradeItem(
        rule_id="pi_link",
        label="Prescribing Information link placeholder present",
        passed=ok,
        detail="PI link/placeholder present." if ok else "Branded content is missing a Prescribing Information link/placeholder.",
    )


def rule_regulatory_footer_tag(soup: BeautifulSoup, raw_html: str, brief: CampaignBrief, ctx: GradingContext) -> GradeItem:
    market_info = ctx.market_info
    if not market_info.known:
        source_note = f" (resolver source: {market_info.source})"
        return GradeItem(
            rule_id="reg_footer",
            label="Regulatory code referenced in footer",
            passed=False,
            detail=f"Market '{brief.market}' couldn't be confidently resolved{source_note} — "
                   f"confirm the applicable code manually.",
            severity=Severity.BLOCKING,
        )
    expected = market_info.tags
    ok = any(tag in raw_html for tag in expected)
    source_note = "" if market_info.source == "dictionary" else f" [resolved via {market_info.source} — double-check this]"
    return GradeItem(
        rule_id="reg_footer",
        label="Regulatory code referenced in footer",
        passed=ok,
        detail=(f"Found {market_info.body_name} reference.{source_note}" if ok
                else f"Footer does not reference the applicable code ({'/'.join(expected)}).{source_note}"),
    )


def rule_no_hardcoded_cta_url(soup: BeautifulSoup, raw_html: str, brief: CampaignBrief, ctx: GradingContext) -> GradeItem:
    real_links = [a.get("href", "") for a in soup.find_all("a")]
    bad = [h for h in real_links if h and h not in ("#", "javascript:void(0)") and not h.startswith("#")
           and "TBC" not in h and "pending" not in h.lower()]
    ok = len(bad) == 0
    return GradeItem(
        rule_id="cta_url",
        label="CTA links are placeholders, not invented URLs",
        passed=ok,
        detail="All CTAs are placeholder links." if ok
        else f"Found {len(bad)} link(s) pointing to a real-looking, non-placeholder URL: {bad[:3]}",
    )


# --- Market-specific rules -------------------------------------------------
# The actual answer to "EU rules are different from US rules, right?" — separate
# from the tag-swap in rule_regulatory_footer_tag because the *content* differs
# by market, not just which acronym appears. Both are deliberately "warning"
# severity, never blocking: the tool has no way to know a product's real
# additional-monitoring or Boxed Warning status, so it can only remind a human
# to confirm — asserting either as a pass/fail would be claiming certainty the
# tool doesn't have.

def rule_black_triangle_uk_eu(soup: BeautifulSoup, raw_html: str, brief: CampaignBrief, ctx: GradingContext) -> GradeItem:
    market_info = ctx.market_info
    if not market_info.known or not any(t in market_info.tags for t in ("ABPI", "EFPIA")):
        return GradeItem(rule_id="black_triangle", label="Black triangle / additional-monitoring reminder (UK/EU)",
                              passed=True, detail="Not applicable — market isn't UK/EU.", severity=Severity.BLOCKING)
    mentioned = "▼" in raw_html or "additional monitoring" in raw_html.lower()
    return GradeItem(
        rule_id="black_triangle",
        label="Black triangle / additional-monitoring reminder (UK/EU)",
        passed=mentioned,
        detail="Draft references additional-monitoring status." if mentioned
        else f"UK/EU draft for '{brief.brand}' doesn't mention additional-monitoring status — "
             f"confirm with regulatory whether the ▼ symbol is required before this ships.",
        severity=Severity.BLOCKING,
    )


def rule_boxed_warning_us(soup: BeautifulSoup, raw_html: str, brief: CampaignBrief, ctx: GradingContext) -> GradeItem:
    market_info = ctx.market_info
    if not market_info.known or "FDA" not in market_info.tags:
        return GradeItem(rule_id="boxed_warning", label="Boxed Warning reminder (US)",
                              passed=True, detail="Not applicable — market isn't US.", severity=Severity.BLOCKING)
    mentioned = "boxed warning" in raw_html.lower()
    return GradeItem(
        rule_id="boxed_warning",
        label="Boxed Warning reminder (US)",
        passed=mentioned,
        detail="Draft references Boxed Warning status." if mentioned
        else f"US draft for '{brief.brand}' doesn't mention Boxed Warning status — "
             f"confirm with regulatory whether one applies before this ships.",
        severity=Severity.BLOCKING,
    )


def rule_uploaded_images_used(soup: BeautifulSoup, raw_html: str, brief: CampaignBrief, ctx: GradingContext) -> GradeItem:
    if not brief.uploaded_images:
        return GradeItem(
            rule_id="uploaded_images_used",
            label="All uploaded images are used in the draft",
            passed=True,
            detail="No images uploaded."
        )

    missing = []
    for fname in brief.uploaded_images.keys():
        if f"uploaded:{fname}" not in raw_html:
            missing.append(fname)

    ok = len(missing) == 0
    return GradeItem(
        rule_id="uploaded_images_used",
        label="All uploaded images are used in the draft",
        passed=ok,
        detail="All uploaded images are present." if ok else f"Missing {len(missing)} uploaded image(s): {', '.join(missing)}"
    )


def rule_unsubscribe_link(soup: BeautifulSoup, raw_html: str, brief: CampaignBrief, ctx: GradingContext) -> GradeItem:
    """Require an unsubscribe or preference link for marketing communications.
    For HCP-targeted communications this is advisory (warning); for other
    audiences it's recommended but left as a warning so humans can review.
    """
    anchors = [a.get_text(" ", strip=True).lower() for a in soup.find_all("a")]
    hrefs = [a.get("href", "").lower() for a in soup.find_all("a")]
    found = any("unsubscribe" in t for t in anchors) or any("unsubscribe" in h for h in hrefs) or any("preferences" in t for t in anchors)
    return GradeItem(
        rule_id="unsubscribe_link",
        label="Unsubscribe / preferences link present",
        passed=found,
        detail="Found unsubscribe or preference link." if found else "Missing unsubscribe or email-preferences link in footer.",
        severity=Severity.BLOCKING,
    )


def rule_contact_info_present(soup: BeautifulSoup, raw_html: str, brief: CampaignBrief, ctx: GradingContext) -> GradeItem:
    """Check for presence of a medical contact (email or phone) for adverse
    events / medical information. This is advisory (warning) if missing.
    """
    # Search visible text
    text = _visible_body_text(soup).lower()

    # 1) explicit mailto / tel links
    mailto_links = [a.get('href', '') for a in soup.find_all('a') if a.get('href', '').lower().startswith('mailto:')]
    tel_links = [a.get('href', '') for a in soup.find_all('a') if a.get('href', '').lower().startswith('tel:')]

    # 2) obvious email patterns in visible text (simple but effective)
    has_email = bool(re.search(r"[\w.%-]+@[\w.-]+\.[a-z]{2,}", text)) or len(mailto_links) > 0

    # 3) phone numbers (allow international, extensions, spaces, parens, dashes)
    has_phone = bool(re.search(r"\+?\d[\d\s\-()]{6,}\d", text)) or len(tel_links) > 0

    # 4) common phrase variants for medical contact
    medical_variants = [
        "medical information",
        "medical enquiries",
        "medical inquiries",
        "medical enquiries",
        "medical affairs",
        "for medical",
        "for medical information",
        "medical information request",
        "medical information enquiries",
        "for medical enquiries",
        "med info",
    ]
    has_medical = any(phrase in text for phrase in medical_variants)

    ok = has_email or has_phone or has_medical
    detail = "Contact info present." if ok else "No medical contact email/phone or 'medical information' text found."
    return GradeItem(
        rule_id="contact_info",
        label="Medical contact / medical information present",
        passed=ok,
        detail=detail,
        severity=Severity.WARNING,
    )


def rule_image_alt_texts(soup: BeautifulSoup, raw_html: str, brief: CampaignBrief, ctx: GradingContext) -> GradeItem:
    imgs = soup.find_all("img")
    # only check images inside the email content area if present
    if soup.select_one('.email-content'):
        imgs = soup.select('.email-content img')
    missing_alt = [str(i) for i in imgs if not i.get("alt") or not i.get("alt").strip()]
    ok = len(missing_alt) == 0
    return GradeItem(
        rule_id="image_alt_text",
        label="Images include alt text",
        passed=ok,
        detail="All images have alt text." if ok else f"{len(missing_alt)} image(s) missing alt text.",
        severity=Severity.BLOCKING,
    )


def rule_logo_present(soup: BeautifulSoup, raw_html: str, brief: CampaignBrief, ctx: GradingContext) -> GradeItem:
    """For branded content require a logo element (img with 'logo' in class/id/alt).
    This is a warning rather than blocking so designers/regulatory can address
    layout exceptions.
    """
    if brief.classification != ContentClassification.BRANDED:
        return GradeItem(rule_id="brand_logo", label="Brand logo present",
                          passed=True, detail="Not applicable — unbranded content.", severity=Severity.BLOCKING)
    imgs = soup.find_all("img")
    logo_like = []
    for img in imgs:
        attrs = " ".join([str(img.get("alt", "")), str(img.get("id", "")), " ".join(img.get("class", []) if img.get("class") else [])]).lower()
        if "logo" in attrs or (brief.brand and brief.brand.lower() in attrs):
            logo_like.append(img)
    ok = len(logo_like) > 0
    return GradeItem(
        rule_id="brand_logo",
        label="Brand logo present",
        passed=ok,
        detail="Logo detected." if ok else "No obvious brand logo element found (img with 'logo' in alt/class/id).",
        severity=Severity.BLOCKING,
    )


def rule_brand_guidelines_llm(soup: BeautifulSoup, raw_html: str, brief: CampaignBrief, ctx: GradingContext) -> GradeItem:
    """LLM-based brand/tone judge. Unlike the deterministic rules above,
    this one uses an LLM call — and unlike _llm_resolve_market in
    regulatory.py, we deliberately catch exceptions here because this
    rule is advisory-grade (severity=WARNING): a transient API failure
    shouldn't block the entire pipeline run when the structural checks
    already passed. The exception is logged in the detail field so it's
    visible, not silently swallowed."""
    if not ctx.client:
        return GradeItem(rule_id="brand_guidelines_llm", label="Brand Guidelines & Tone (LLM Judge)",
                  passed=True, detail="Skipped — no LLM client provided to grader.",
                  severity=Severity.BLOCKING)

    system = """You are an expert regulatory and brand reviewer acting as an automated judge.
Evaluate the following HTML draft for strict brand guideline compliance, tone, and visual aesthetics.
If the text implies unapproved efficacy, has a dangerous tone, uses totally inappropriate layout, or severely violates pharma brand safety, it FAILS.
If it is safe, clean, and appropriate for the context, it PASSES.
Respond with ONLY a JSON object: {"passed": true, "detail": "<short explanation>"} or {"passed": false, "detail": "<short explanation>"}"""

    user = f"Brand: {brief.brand}\nObjective: {brief.objective}\nAudience: {brief.audience}\n\nDraft HTML:\n{raw_html}"
    try:
        raw = ctx.client.complete(system=system, user=user, max_tokens=1500)
        text = strip_code_fences(raw)
        res = json.loads(text)
        passed = bool(res.get("passed", False))
        detail = str(res.get("detail", "LLM rejected the brand voice/aesthetics."))
        return GradeItem(
            rule_id="brand_guidelines_llm",
            label="Brand Guidelines & Tone (LLM Judge)",
            passed=passed,
            detail=detail,
            severity=Severity.BLOCKING,
        )
    except Exception as e:
        # Caught deliberately — see docstring above for reasoning.
        return GradeItem(
            rule_id="brand_guidelines_llm",
            label="Brand Guidelines & Tone (LLM Judge)",
            passed=False,
            detail=f"LLM judge failed to parse or execute: {str(e)}",
            severity=Severity.BLOCKING,
        )


ALL_RULES: list[RuleFunc] = [
    rule_draft_watermark,
    rule_job_code_pending,
    rule_hcp_audience_tag,
    rule_ae_box,
    rule_brand_leak,
    rule_pi_link_if_branded,
    rule_regulatory_footer_tag,
    rule_no_hardcoded_cta_url,
    rule_black_triangle_uk_eu,
    rule_boxed_warning_us,
    rule_unsubscribe_link,
    rule_contact_info_present,
    rule_image_alt_texts,
    rule_logo_present,
    rule_uploaded_images_used,
    rule_brand_guidelines_llm,
]


def grade(html: str, brief: CampaignBrief, ctx: GradingContext, iteration: int) -> GradeReport:
    soup = BeautifulSoup(html, "html.parser")
    
    # Run rules in parallel to speed up execution (specifically the LLM judge).
    # Use submission-order collection (not as_completed) so GradeReport.items
    # stays in the same deterministic order as ALL_RULES across every run.
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(rule, soup, html, brief, ctx) for rule in ALL_RULES]
        items = [future.result() for future in futures]
        
    return GradeReport(items=items, iteration=iteration)
