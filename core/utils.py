"""
Shared text-processing utilities.

Kept intentionally small — only things genuinely used by ≥2 modules
belong here. Module-specific helpers stay in their own module.
"""

from __future__ import annotations

import re
from bs4 import BeautifulSoup, Comment

REDACTION_PATTERNS = [
    (re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"), "[REDACTED_EMAIL]"),
    (re.compile(r"\b(?:\+?44|0044|1|001)?[-.\s]?(?:\(?\d{3,4}\)?[-.\s]?)?\d{3,4}[-.\s]?\d{3,4}\b"), "[REDACTED_PHONE]"),
    (re.compile(r"\b(?:\d[ -]*?){13,19}\b"), "[REDACTED_NUMBER]"),
]


def strip_code_fences(text: str) -> str:
    """Strip markdown code fences (```…```) that LLMs sometimes wrap
    around JSON or HTML responses, returning the inner content.

    Handles both bare ``` and language-tagged fences (```json, ```html).
    Safe to call on text that doesn't have fences — returns it unchanged.
    """
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Drop the opening fence line (```json, ```html, or bare ```)
        lines = lines[1:]
        # Drop the closing fence line if present
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


def sanitize_html_input(html: str) -> str:
    """Remove executable or hidden content from generated HTML before reuse."""
    if not html:
        return html

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["script", "noscript"]):
        tag.decompose()
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    for element in soup.find_all():
        # Remove inline event handlers and javascript: hrefs
        for attr in list(element.attrs):
            if attr.startswith("on") or (attr == "href" and isinstance(element[attr], str) and element[attr].strip().lower().startswith("javascript:")):
                del element[attr]
    return str(soup)


def redact_text(text: str) -> str:
    """Redact obvious sensitive-looking strings from traceable text."""
    if not text:
        return text
    safe = text
    for pattern, replacement in REDACTION_PATTERNS:
        safe = pattern.sub(replacement, safe)
    return safe
