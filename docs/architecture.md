# Architecture

This document contains detailed architectural explanations for the core components of the MLR Draft Pipeline.

## Generator
The generator produces a single self-contained HTML file that mocks up an email preview or web page. It uses an LLM to generate the initial draft and subsequently revise it based on grading feedback.

When generating, it incorporates the market regulations, the target audience, and brand-specific tokens.

## Grader
The grader is a deterministic, regex-based validation engine. It evaluates the generated HTML against a set of strict rules:
- **Brand Rules:** Ensure product names appear correctly.
- **Structural Rules:** Ensure required elements (unsubscribe links, footnotes, PI links) are present.
- **Compliance Rules:** Enforce blacklisted/whitelisted phrases based on market (e.g., UK vs US) and audience (HCP vs Consumer).

It produces a detailed `GradeReport` indicating whether the draft passed or failed, with line-item justifications for every rule checked.

## Regulatory Engine
The regulatory engine resolves ambiguous market and audience inputs into concrete configuration objects (`MarketInfo` and `AudienceInfo`). If the user provides free-text inputs (like "Ireland" or "Payers"), it queries an LLM to classify them into the correct region and audience type (HCP or Consumer).

This ensures the Grader can operate deterministically against well-defined regional profiles.
