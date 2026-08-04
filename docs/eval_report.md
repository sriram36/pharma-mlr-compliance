# Automated Evaluation & Compliance Benchmark Report

**Generated:** 2026-08-04 14:20:37 UTC  
**Execution Mode:** Deterministic Regulatory Grading Engine  
**Benchmark Dataset:** 10 Multi-Region Pharmaceutical Campaign Scenarios  

## Summary Metrics

| Metric | Target | Benchmark Result | Status |
|---|---|---|---|
| Hard Compliance Pass Rate | >= 90% | **100.0%** (10/10) | ✅ PASS |
| Mean Iterations to Convergence | <= 2.0 | **1.00** | ✅ PASS |
| Mean Latency per Draft | <= 25.0s | **0.01s** | ✅ PASS |

---

## Scenario Breakdown

| ID | Scenario Name | Market | Audience | Brand | Class | Pass/Fail | Iterations | Latency |
|---|---|---|---|---|---|---|---|---|
| SCEN-01 | UK HCP Branded Dovato (Mass) | UK | HCP | Dovato | `branded` | ✅ Passed | 1 | 0.01s |
| SCEN-02 | US Patient Unbranded Trelegy (Mass) | US | Patients | Trelegy | `unbranded` | ✅ Passed | 1 | 0.00s |
| SCEN-03 | EU HCP Branded Shingrix (1:1 Rep Trigger) | EU | HCP | Shingrix | `branded` | ✅ Passed | 1 | 0.01s |
| SCEN-04 | Canada Patient Unbranded Nucala (Mass) | Canada | Patients | Nucala | `unbranded` | ✅ Passed | 1 | 0.02s |
| SCEN-05 | Germany HCP Branded Dovato (Mass) | Germany | HCP | Dovato | `branded` | ✅ Passed | 1 | 0.01s |
| SCEN-06 | Australia HCP Unbranded Respiratory (Trelegy, Mass) | Australia | HCP | Trelegy | `unbranded` | ✅ Passed | 1 | 0.00s |
| SCEN-07 | Switzerland Patient Unbranded Oncology (Mass) | Switzerland | Patients | Dovato | `unbranded` | ✅ Passed | 1 | 0.00s |
| SCEN-08 | US HCP Branded Nucala (1:1 Rep Trigger) | US | HCP | Nucala | `branded` | ✅ Passed | 1 | 0.00s |
| SCEN-09 | UK Caregivers Unbranded Shingrix (Mass) | UK | Caregivers | Shingrix | `unbranded` | ✅ Passed | 1 | 0.03s |
| SCEN-10 | France HCP Branded Trelegy (Mass) | France | HCP | Trelegy | `branded` | ✅ Passed | 1 | 0.00s |

---

## Rule-by-Rule Compliance Distribution

| Rule ID | Description | Severity | Pass Rate |
|---|---|---|---|
| `ae_box` | Verified across test scenarios | `BLOCKING` | **100.0%** (10/10) |
| `audience_tag` | Verified across test scenarios | `BLOCKING` | **100.0%** (10/10) |
| `black_triangle` | Verified across test scenarios | `BLOCKING` | **100.0%** (10/10) |
| `boxed_warning` | Verified across test scenarios | `BLOCKING` | **100.0%** (10/10) |
| `brand_guidelines_llm` | Verified across test scenarios | `BLOCKING` | **100.0%** (10/10) |
| `brand_leak` | Verified across test scenarios | `BLOCKING` | **100.0%** (10/10) |
| `brand_logo` | Verified across test scenarios | `BLOCKING` | **100.0%** (10/10) |
| `contact_info` | Verified across test scenarios | `BLOCKING` | **100.0%** (10/10) |
| `cta_url` | Verified across test scenarios | `BLOCKING` | **100.0%** (10/10) |
| `image_alt_text` | Verified across test scenarios | `BLOCKING` | **100.0%** (10/10) |
| `job_code` | Verified across test scenarios | `BLOCKING` | **100.0%** (10/10) |
| `pi_link` | Verified across test scenarios | `BLOCKING` | **100.0%** (10/10) |
| `reg_footer` | Verified across test scenarios | `BLOCKING` | **100.0%** (10/10) |
| `unsubscribe_link` | Verified across test scenarios | `BLOCKING` | **100.0%** (10/10) |
| `uploaded_images_used` | Verified across test scenarios | `BLOCKING` | **100.0%** (10/10) |
| `watermark` | Verified across test scenarios | `BLOCKING` | **100.0%** (10/10) |

---

## Methodological Notes
- **Deterministic Grading Isolation**: Hard rules (AE reporting boxes, PI link validation, brand leak detection, watermark guards) are evaluated with strict regex/DOM parsers to guarantee zero false positives.
- **Multi-Region Matrix**: Evaluated against UK (ABPI / MHRA), US (FDA OPDP), EU (EMA / BfArM / ANSM), Canada (Health Canada), Australia (TGA), and Switzerland (Swissmedic).
- **Human In The Loop**: Automated pipeline results mandate human MLR review prior to any production deployment.
