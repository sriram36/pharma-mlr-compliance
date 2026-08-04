"""
Brand visual tokens.

These are placeholder design tokens for prototyping layout only —
NOT pulled from any brand guideline PDF. Before this touches a real
deck or a real MLR reviewer, swap these for the actual values in the
brand's approved style guide. Logos are never embedded as real image
assets here; the generator always leaves a labeled placeholder slot
(see prompts/generator_system.md), same as your uploaded templates.
"""

BRAND_TOKENS = {
    "Dovato": {
        "company": "ViiV Healthcare, a company of GSK",
        "primary": "#D4007A",     # magenta accent used in your DOVATO-006 sample
        "secondary": "#1A1A2E",   # navy gradient used in your DOVATO-004 sample
        "ae_report_line": "Report adverse events at yellowcard.mhra.gov.uk or via the GSK Reporting Tool / 0800 221 441.",
        "pi_link_placeholder": "[INSERT PI LINK — pending confirmed URL]",
    },
    "Nucala": {
        "company": "GSK",
        "primary": "#C8102E",     # red, consistent with your NUCALA samples
        "secondary": "#1A1A2E",
        "ae_report_line": "Report adverse events to the FDA MedWatch at 1-800-FDA-1088 or www.fda.gov/medwatch, or to GSK at 1-888-825-5249.",
        "pi_link_placeholder": "[INSERT Full Prescribing Information + Boxed Warning link — pending confirmed URL]",
    },
    "Trelegy": {
        "company": "GSK",
        "primary": "#5B2C6F",
        "secondary": "#1A1A2E",
        "ae_report_line": "Report adverse events to the FDA MedWatch at 1-800-FDA-1088 or www.fda.gov/medwatch, or to GSK at 1-888-825-5249.",
        "pi_link_placeholder": "[INSERT Full Prescribing Information link — pending confirmed URL]",
    },
    "Shingrix": {
        "company": "GSK",
        "primary": "#E87722",
        "secondary": "#1A1A2E",
        "ae_report_line": "Report adverse events to the FDA MedWatch at 1-800-FDA-1088 or www.fda.gov/medwatch, or to GSK at 1-888-825-5249.",
        "pi_link_placeholder": "[INSERT Prescribing Information link — pending confirmed URL]",
    },
}

DEFAULT_TOKENS = {
    "company": "[SPONSOR COMPANY — TBC]",
    "primary": "#1A1A2E",
    "secondary": "#5f6368",
    "ae_report_line": "[INSERT market-appropriate adverse event reporting line — TBC with local regulatory team]",
    "pi_link_placeholder": "[INSERT Prescribing Information link — pending confirmed URL]",
}


def get_brand_tokens(brand: str) -> dict:
    return BRAND_TOKENS.get(brand, DEFAULT_TOKENS)
