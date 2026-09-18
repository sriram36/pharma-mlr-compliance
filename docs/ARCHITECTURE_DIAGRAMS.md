# Pharma Marketing MLR Compliance — Architecture Diagrams

These diagrams reflect the current repository architecture. The production runtime is the LangGraph pipeline used by both `app.py` and `api.py`; `pipeline/pipeline.py` remains a plain-Python reference implementation.

## 1. High-Level System Architecture

```mermaid
flowchart TB
    subgraph Clients["Clients / Entry Points"]
        UI["Streamlit Workspace\napp.py"]
        API["FastAPI REST API\napi.py"]
        WH["CRM / CMS Webhook\n/api/webhook/campaign"]
        DEMO["Standalone Browser Demo\ndocs/live-loop-demo.html"]
    end

    subgraph App["Application Layer"]
        SIDEBAR["Brief Configurator\nui/sidebar.py"]
        REVIEW["Human MLR Review\nui/review.py"]
        DASH["Verification Dashboard\nui/dashboard.py"]
        HISTORY["Archive / Audit Table\nui/history.py"]
    end

    subgraph Engine["LangGraph Pipeline"]
        RESOLVE["Resolve Market + Audience\ncore/regulatory.py"]
        GENERATE["Generate / Revise Draft\npipeline/generator.py"]
        GRADE["Deterministic Compliance Grader\npipeline/grader.py"]
        SOFT["Optional Soft Review\npipeline/soft_review.py"]
    end

    subgraph Core["Core Services"]
        SCHEMA["Pydantic Data Contracts\ncore/schema.py"]
        BRAND["Brand Tokens\ncore/brand_config.py"]
        LLM["Azure OpenAI Client\ncore/llm_client.py"]
        TRACE["Trace Logger\ncore/trace_logger.py"]
        CONFIG["Configuration / Logging / Errors\ncore/config.py / logger.py / exceptions.py"]
    end

    subgraph External["External / Persistent"]
        AZURE["Azure OpenAI"]
        CACHE["resolution_cache.json"]
        AUDIT["JSON Metadata Sidecars / Audit Archive"]
        EVAL["10-scenario Evaluation Harness\nscripts/eval_harness.py"]
    end

    UI --> SIDEBAR
    UI --> REVIEW
    UI --> DASH
    UI --> HISTORY
    SIDEBAR --> API
    API --> WH
    WH --> RESOLVE
    API --> RESOLVE

    RESOLVE --> GENERATE
    GENERATE --> GRADE
    GRADE -->|blocking failure| GENERATE
    GRADE -->|pass / stop condition| SOFT

    RESOLVE --> CACHE
    RESOLVE --> LLM
    GENERATE --> LLM
    SOFT --> LLM
    LLM --> AZURE

    BRAND --> GENERATE
    SCHEMA --> RESOLVE
    SCHEMA --> GRADE
    SCHEMA --> SOFT

    RESOLVE --> TRACE
    GRADE --> TRACE
    TRACE --> AUDIT

    SOFT --> REVIEW
    GRADE --> DASH
    AUDIT --> HISTORY

    EVAL --> RESOLVE
    EVAL --> GENERATE
    EVAL --> GRADE
```

## 2. LangGraph Processing / Revision Loop

```mermaid
flowchart LR
    A["CampaignBrief"] --> B["resolve"]
    B --> C["generate\nIteration 1"]
    C --> D["grade\nDeterministic rules"]

    D --> E{Decision}

    E -->|All blocking rules pass| F["soft_review\nOptional advisory LLM"]
    E -->|Blocking failure\niterations < MAX| C
    E -->|Same failures repeated\n(stuck)| F
    E -->|MAX_ITERATIONS reached| F

    F --> G["PipelineResult\napproved_for_production = false"]

    C -.->|"revision uses previous HTML + failed rules"| C
    D -.->|"log_iteration()"| H["Trace Log"]
    B -.->|"log_resolution()"| H
```

### Pipeline state

```mermaid
classDiagram
    class CampaignBrief {
        channel
        email_type
        market
        audience
        brand
        objective
        classification
    }

    class MarketInfo {
        body_name
        regulatory_tag
        known
        source
    }

    class AudienceInfo {
        is_hcp
        known
        source
    }

    class GradingContext {
        tokens
        market_info
        audience_info
        client
    }

    class GradeReport {
        items[]
        all_passed
        failed_items
    }

    class SoftReviewNote {
        concern
        detail
    }

    class PipelineResult {
        final_html
        grade_report
        iterations_used
        soft_review_notes[]
        approved_for_production
    }

    CampaignBrief --> GradingContext
    MarketInfo --> GradingContext
    AudienceInfo --> GradingContext
    GradingContext --> GradeReport
    GradeReport --> PipelineResult
    SoftReviewNote --> PipelineResult
    CampaignBrief --> PipelineResult
```

## 3. Regulatory Resolution Strategy

```mermaid
flowchart TD
    IN["Free-text Market / Audience"] --> D["Dictionary / Alias Match"]
    D -->|recognized| R["Resolved Info"]
    D -->|not recognized| C["Disk Cache"]
    C -->|cached| R
    C -->|cache miss + LLM client| L["Azure OpenAI Classification"]
    L --> S["Store Resolution in Cache"]
    S --> R
    C -->|cache miss + no client| U["known = false\nhonest unresolved state"]
```

## 4. Compliance Grading Architecture

```mermaid
flowchart TB
    HTML["Generated HTML Draft"] --> PARSE["BeautifulSoup / HTML Parsing"]
    PARSE --> RULES["Deterministic Rule Engine"]

    RULES --> R1["Watermark"]
    RULES --> R2["Job Code"]
    RULES --> R3["Audience Tag"]
    RULES --> R4["AE Box"]
    RULES --> R5["Brand Leak"]
    RULES --> R6["PI Link"]
    RULES --> R7["Regulatory Footer"]
    RULES --> R8["CTA Placeholder"]
    RULES --> R9["Logo Placeholder"]
    RULES --> R10["UK/EU Black Triangle"]
    RULES --> R11["US Boxed Warning"]

    R1 --> REPORT["GradeReport"]
    R2 --> REPORT
    R3 --> REPORT
    R4 --> REPORT
    R5 --> REPORT
    R6 --> REPORT
    R7 --> REPORT
    R8 --> REPORT
    R9 --> REPORT
    R10 --> REPORT
    R11 --> REPORT

    REPORT --> DECIDE{Blocking failures?}
    DECIDE -->|Yes| PATCH["Send only failed-rule feedback"]
    DECIDE -->|No| ADVISORY["Optional Soft Review"]
    PATCH --> GENERATOR["Generator revise()"]
    GENERATOR --> HTML
```

## 5. Human Review, Audit and Evaluation

```mermaid
flowchart LR
    RESULT["PipelineResult\nstructurally checked draft"] --> REVIEW["Human MLR Review & Sign-Off"]
    REVIEW -->|approve / reject / edit| HUMAN["Qualified Human Decision"]
    RESULT --> ARCHIVE["Audit Metadata / Draft Archive"]
    ARCHIVE --> HISTORY["ui/history.py"]
    RESULT --> TRACE["Append-only Trace"]
    TRACE --> ANALYZE["analyze_traces.py"]
    ANALYZE --> INSIGHT["Rule Failure Frequencies / Iteration Metrics"]

    EVAL["scripts/eval_harness.py"] --> SCENARIOS["10 Global Regulatory Scenarios"]
    SCENARIOS --> RESULT_EVAL["Pass-rate Matrix"]
    RESULT_EVAL --> REPORT["docs/eval_report.md"]
```

## 6. Deployment / Runtime View

```mermaid
flowchart TB
    USER["Marketing / Compliance User"] --> WEB["Browser"]

    WEB --> STREAMLIT["Streamlit App"]
    WEB --> REST["FastAPI"]

    STREAMLIT --> PIPE["LangGraph Pipeline"]
    REST --> PIPE

    PIPE --> AZ["Azure OpenAI"]
    PIPE --> FS["Local Filesystem\nresolution cache + audit sidecars + generated HTML"]

    subgraph Runtime["Python Runtime"]
        STREAMLIT
        REST
        PIPE
    end
```

## Architecture Notes

- `pipeline/pipeline_langgraph.py` is the runtime orchestrator. Its graph is `resolve → generate → grade → conditional generate/soft_review → END`.
- `pipeline/grader.py` is intentionally deterministic; the soft-review LLM is advisory and runs only after blocking checks pass.
- `PipelineResult.approved_for_production` is always `False`; the final regulatory decision remains human.
- Azure OpenAI is the only configured LLM provider.
- The plain-Python `pipeline/pipeline.py` mirrors the same core logic and is retained as a simpler reference implementation.
