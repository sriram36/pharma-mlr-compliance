import json
import asyncio
import time
import enum
from typing import Optional
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from core.brand_config import BRAND_TOKENS
from core.schema import CampaignBrief, Channel, EmailType, ContentClassification, Severity, ImageMap
from core.llm_client import LLMClient
from core.config import settings
from core.logger import get_logger
from pipeline.pipeline_langgraph import build_graph
from ui.dashboard import highlight_flagged_claims

logger = get_logger(__name__)

# Initialize sliding-window IP rate limiter
limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("==================================================")
    logger.info(f"🚀 Starting MLR Pipeline API v0.2.0")
    logger.info(f"Loaded brand tokens for: {', '.join(BRAND_TOKENS.keys())}")
    logger.info("Application startup complete. Rate limiting active. Waiting for requests...")
    logger.info("==================================================")
    yield
    logger.info("Shutting down API...")

API_DESCRIPTION = """
### MLR Compliance Drafting Pipeline Backend
- **Security & Scoped Authentication**: Architected for internal pharmaceutical MLR workflow operations. Authentication is intentionally scoped out for prototype development and delegated to enterprise gateway / VPC reverse proxy (OAuth2/OIDC) in production.
- **Rate Limiting**: Enforced via SlowAPI sliding-window rate limiting to prevent token budget exhaustion and DoS.
- **Loop 3 Webhook**: Event-driven triggers supported via `/api/webhook/campaign` for asynchronous CRM/CMS automated drafting.
"""

app = FastAPI(
    title="MLR Pipeline API",
    version="0.2.0",
    description=API_DESCRIPTION,
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_allow_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

file_lock = asyncio.Lock()

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def serve_frontend():
    return HTMLResponse(Path("static/index.html").read_text(encoding="utf-8"))


# --- Request / Response models ---

class GenerateRequest(BaseModel):
    channel: Channel
    email_type: Optional[EmailType] = None
    market: str
    audience: str
    brand: str
    objective: str
    classification: ContentClassification
    run_soft_review: bool = True
    images: ImageMap = {}


class ReviewRequest(BaseModel):
    status: str
    comment: Optional[str] = None


class ReviseRequest(BaseModel):
    human_feedback: str


# --- Shared helpers ---

from dateutil import parser as date_parser


def custom_encoder(obj):
    if isinstance(obj, set):
        return list(obj)
    if isinstance(obj, enum.Enum):
        return obj.value
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    if hasattr(obj, "__dict__"):
        # Don't try to serialize deep complex objects like AzureOpenAI clients
        if obj.__class__.__name__ in ("AzureOpenAI", "AsyncAzureOpenAI", "Client", "LLMClient"):
            return f"<{obj.__class__.__name__}>"
        return obj.__dict__
    return str(obj)


def filter_update(update: dict) -> dict:
    """Remove backend-only objects that the frontend doesn't need and can't be cleanly serialized."""
    return {k: v for k, v in update.items() if k not in ("client", "brief")}


def get_recent_drafts():
    records = []
    outputs_dir = Path("outputs")
    if not outputs_dir.exists():
        return records
    for json_file in outputs_dir.glob("*.json"):
        try:
            records.append(json.loads(json_file.read_text(encoding="utf-8")))
        except Exception:
            continue

    def parse_date(record):
        date_str = record.get("created_at", "")
        try:
            return date_parser.parse(date_str)
        except Exception:
            return datetime.min

    records.sort(key=parse_date, reverse=True)
    return records


async def stream_pipeline(brief: CampaignBrief, run_soft_review: bool,
                          initial_html: str | None = None,
                          human_feedback: str | None = None,
                          existing_meta: dict | None = None,
                          existing_json_path: Path | None = None,
                          existing_html_path: Path | None = None):
    """Shared SSE streaming logic for both generate and revise endpoints."""
    logger.info(f"Starting pipeline stream for brand '{brief.brand}' (Market: {brief.market}, Audience: {brief.audience})")
    t0 = time.time()
    try:
        client = LLMClient()
    except Exception as e:
        yield f"data: {json.dumps({'error': f'LLM client init failed: {e}'})}\n\n"
        return

    try:
        graph = build_graph()
        final_state = {}
        prev_failed_ids = []
        iteration_history = []

        init_state = {
            "brief": brief,
            "client": client,
            "run_soft_review": run_soft_review,
            "iteration": 0,
            "prev_failed_ids": None,
        }
        if initial_html is not None:
            init_state["html"] = initial_html
        if human_feedback is not None:
            init_state["human_feedback"] = human_feedback

        for step in graph.stream(init_state):
            node_name = list(step.keys())[0]
            update = step[node_name]
            final_state.update(update)

            delta_info = {}
            if node_name == "grade" and "grade_report" in update:
                report = update["grade_report"]
                current_iteration = final_state.get("iteration", 0)
                warn_count = sum(1 for i in report.items if not i.passed and i.severity.value == "warning")
                passed_count = sum(1 for i in report.items if i.passed)

                failed_rules = [i.rule_id for i in report.items if not i.passed and i.severity.value == "blocking"]
                rectified = [r for r in prev_failed_ids if r not in failed_rules]
                still_failing = [r for r in failed_rules if r in prev_failed_ids]
                new_failures = [r for r in failed_rules if r not in prev_failed_ids]

                if prev_failed_ids:
                    delta_info = {
                        "rectified": rectified,
                        "still_failing": still_failing,
                        "new_failures": new_failures,
                    }

                iteration_history.append({
                    "attempt": current_iteration,
                    "passed": passed_count,
                    "failed": len(failed_rules),
                    "warned": warn_count,
                    "rectified": rectified,
                    "still_failing": still_failing,
                    "new_failures": new_failures,
                })

                prev_failed_ids = failed_rules

            payload = {
                "node": node_name,
                "update": filter_update(update),
                "delta": delta_info,
            }
            yield f"data: {json.dumps(payload, default=custom_encoder)}\n\n"
            await asyncio.sleep(0.01)

        elapsed = time.time() - t0
        html_raw = final_state.get("html", "")
        report = final_state.get("grade_report")

        html_preview = html_raw
        if brief.uploaded_images:
            for fname, data_uri in brief.uploaded_images.items():
                html_preview = html_preview.replace(f"uploaded:{fname}", data_uri)

        if report and not report.all_passed:
            html_preview = highlight_flagged_claims(html_preview, report)

        meta = existing_meta or {}
        if report:
            passed_count = sum(1 for i in report.items if i.passed)
            failed_count = sum(1 for i in report.items if not i.passed and i.severity.value == "blocking")
            warn_count = sum(1 for i in report.items if not i.passed and i.severity.value == "warning")

            async with file_lock:
                out_dir = Path("outputs")
                out_dir.mkdir(exist_ok=True)

                if existing_meta and existing_json_path and existing_html_path:
                    # Revise path: update existing files
                    existing_html_path.write_text(html_raw, encoding="utf-8")
                    meta["iterations"] = meta.get("iterations", 0) + final_state.get("iteration", 0)
                    meta["passed"] = passed_count
                    meta["failed"] = failed_count
                    meta["warned"] = warn_count
                    meta["all_passed"] = report.all_passed
                    meta["last_revised"] = datetime.now().isoformat()
                    existing_json_path.write_text(json.dumps(meta, default=custom_encoder), encoding="utf-8")
                    logger.info(f"Revised draft {meta.get('id')} for {brief.brand} in {elapsed:.1f}s (Total iterations: {meta['iterations']})")
                else:
                    # Generate path: create new files
                    existing = list(out_dir.glob("*.json"))
                    draft_id = f"#{1200 + len(existing) + 1}"

                    output_filename = f"{brief.market}_{brief.audience}_{brief.brand}_{brief.channel}_{brief.classification}.html".replace(" ", "_").lower()
                    if (out_dir / output_filename).exists():
                        output_filename = output_filename.replace(".html", f"_{int(time.time())}.html")

                    output_path = out_dir / output_filename
                    output_path.write_text(html_raw, encoding="utf-8")

                    meta = {
                        "id": draft_id,
                        "channel": brief.channel.value if isinstance(brief.channel, enum.Enum) else brief.channel,
                        "type": brief.email_type.value if isinstance(brief.email_type, enum.Enum) else brief.email_type,
                        "market": brief.market,
                        "audience": brief.audience,
                        "brand": brief.brand,
                        "objective": brief.objective,
                        "iterations": final_state.get("iteration", 0),
                        "passed": passed_count,
                        "failed": failed_count,
                        "warned": warn_count,
                        "all_passed": report.all_passed,
                        "elapsed": f"{elapsed:.1f}",
                        "created_at": datetime.now().isoformat(),
                    }
                    json_filename = output_filename.replace(".html", "") + ".json"
                    (out_dir / json_filename).write_text(json.dumps(meta, default=custom_encoder), encoding="utf-8")
                    logger.info(f"Generated draft {draft_id} for {brief.brand} in {elapsed:.1f}s (Iterations: {final_state.get('iteration', 0)})")

        soft_review_notes_raw = final_state.get("soft_review_notes", []) or []
        soft_notes_serializable = [
            {"concern": n.concern, "detail": n.detail} if hasattr(n, "concern") else n
            for n in soft_review_notes_raw
        ]
        yield f"data: {json.dumps({'done': True, 'html': html_raw, 'html_preview': html_preview, 'report': report, 'meta': meta, 'iteration_history': iteration_history, 'soft_review_notes': soft_notes_serializable}, default=custom_encoder)}\n\n"

    except Exception as e:
        logger.error(f"Pipeline streaming error: {e}")
        yield f"data: {json.dumps({'error': str(e)})}\n\n"


# --- Endpoints ---

@app.get("/health")
async def health_check():
    return {"status": "ok", "version": app.version}


@app.get("/api/history")
async def get_history():
    return get_recent_drafts()


@app.get("/api/analytics")
async def get_analytics():
    drafts = get_recent_drafts()
    if not drafts:
        return {"total_drafts": 0, "overall_pass_rate": 0, "avg_iterations": 0, "by_brand": {}}

    total = len(drafts)
    passed = sum(1 for d in drafts if d.get("all_passed", False))
    iterations = sum(d.get("iterations", 1) for d in drafts)

    by_brand = {}
    for d in drafts:
        b = d.get("brand") or "Unbranded"
        if b not in by_brand:
            by_brand[b] = {"total": 0, "passed": 0}
        by_brand[b]["total"] += 1
        if d.get("all_passed", False):
            by_brand[b]["passed"] += 1

    for b in by_brand:
        by_brand[b]["pass_rate"] = round((by_brand[b]["passed"] / by_brand[b]["total"]) * 100, 1)

    return {
        "total_drafts": total,
        "overall_pass_rate": round((passed / total) * 100, 1),
        "avg_iterations": round(iterations / total, 1),
        "by_brand": by_brand,
    }


from pipeline.pipeline_langgraph import build_graph, run_pipeline_langgraph

class WebhookCampaignPayload(BaseModel):
    channel: Channel = Channel.EMAIL
    email_type: Optional[EmailType] = EmailType.MASS
    market: str
    audience: str
    brand: str
    objective: str
    classification: ContentClassification = ContentClassification.UNBRANDED_DISEASE_AWARENESS
    run_soft_review: bool = True
    images: ImageMap = {}
    callback_url: Optional[str] = None


@app.post("/api/drafts/{draft_id}/review")
@limiter.limit("60/minute")
async def review_draft(request: Request, draft_id: str, req: ReviewRequest):
    draft_id_clean = draft_id.replace("%23", "#")
    outputs_dir = Path("outputs")
    for json_file in outputs_dir.glob("*.json"):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            if data.get("id") == draft_id_clean:
                data["status"] = req.status
                data["reviewer_comment"] = req.comment
                data["reviewed_at"] = datetime.now().isoformat()
                json_file.write_text(json.dumps(data, default=custom_encoder), encoding="utf-8")
                return {"success": True, "draft": data}
        except Exception:
            continue
    raise HTTPException(status_code=404, detail="Draft not found")


@app.post("/api/generate")
@limiter.limit("20/minute")
async def generate(request: Request, req: GenerateRequest):
    logger.info(f"Received /api/generate request for {req.brand} in {req.market}")
    brief = CampaignBrief(
        channel=Channel(req.channel),
        email_type=EmailType(req.email_type) if req.email_type else None,
        market=req.market,
        audience=req.audience,
        brand=req.brand,
        objective=req.objective,
        classification=ContentClassification(req.classification),
        uploaded_images=req.images,
    )
    return StreamingResponse(
        stream_pipeline(brief, req.run_soft_review),
        media_type="text/event-stream",
    )


@app.post("/api/drafts/{draft_id}/revise")
@limiter.limit("20/minute")
async def revise_draft(request: Request, draft_id: str, req: ReviseRequest):
    logger.info(f"Received /api/drafts/{draft_id}/revise request")
    draft_id_clean = draft_id.replace("%23", "#")
    outputs_dir = Path("outputs")

    target_meta = None
    target_json_path = None
    for json_file in outputs_dir.glob("*.json"):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            if data.get("id") == draft_id_clean:
                target_meta = data
                target_json_path = json_file
                break
        except Exception:
            continue

    if not target_meta:
        raise HTTPException(status_code=404, detail="Draft not found")

    html_path = target_json_path.with_suffix(".html")
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="HTML for draft not found")

    existing_html = html_path.read_text(encoding="utf-8")

    brief = CampaignBrief(
        channel=Channel(target_meta.get("channel", "email")),
        email_type=EmailType(target_meta.get("type")) if target_meta.get("type") else None,
        market=target_meta.get("market", ""),
        audience=target_meta.get("audience", ""),
        brand=target_meta.get("brand", ""),
        objective=target_meta.get("objective", ""),
        classification=ContentClassification("unbranded"),
    )
    if "branded" in html_path.name.lower() and "unbranded" not in html_path.name.lower():
        brief.classification = ContentClassification("branded")

    return StreamingResponse(
        stream_pipeline(
            brief, run_soft_review=True,
            initial_html=existing_html,
            human_feedback=req.human_feedback,
            existing_meta=target_meta,
            existing_json_path=target_json_path,
            existing_html_path=html_path,
        ),
        media_type="text/event-stream",
    )


@app.post("/api/webhook/campaign")
@limiter.limit("30/minute")
async def trigger_campaign_webhook(request: Request, payload: WebhookCampaignPayload):
    """
    Loop 3 (Event-Driven Trigger):
    Accepts campaign events from external CRM, CMS, or scheduled cron workflows.
    Executes the LangGraph generation and grading pipeline synchronously and stores the compliant draft.
    """
    logger.info(f"Loop 3 event-driven webhook triggered for {payload.brand} ({payload.market} / {payload.audience})")
    t0 = time.time()

    brief = CampaignBrief(
        channel=payload.channel,
        email_type=payload.email_type,
        market=payload.market,
        audience=payload.audience,
        brand=payload.brand,
        objective=payload.objective,
        classification=payload.classification,
        uploaded_images=payload.images,
    )

    try:
        # Run pipeline in worker thread to prevent blocking the async event loop
        loop = asyncio.get_running_loop()
        result: PipelineResult = await loop.run_in_executor(
            None,
            lambda: run_pipeline_langgraph(brief, run_soft_review=payload.run_soft_review)
        )
    except Exception as e:
        logger.error(f"Loop 3 Webhook execution failed: {e}")
        raise HTTPException(status_code=500, detail=f"Pipeline generation failed: {str(e)}")

    elapsed = time.time() - t0
    report = result.grade_report
    passed_count = sum(1 for i in report.items if i.passed)
    failed_count = sum(1 for i in report.items if not i.passed and i.severity == Severity.BLOCKING)
    warn_count = sum(1 for i in report.items if not i.passed and i.severity == Severity.WARNING)

    async with file_lock:
        out_dir = Path("outputs")
        out_dir.mkdir(exist_ok=True)
        existing = list(out_dir.glob("*.json"))
        draft_id = f"#{1200 + len(existing) + 1}"

        output_filename = f"webhook_{brief.market}_{brief.audience}_{brief.brand}_{brief.channel}_{brief.classification}.html".replace(" ", "_").lower()
        if (out_dir / output_filename).exists():
            output_filename = output_filename.replace(".html", f"_{int(time.time())}.html")

        (out_dir / output_filename).write_text(result.final_html, encoding="utf-8")

        meta = {
            "id": draft_id,
            "channel": brief.channel.value if isinstance(brief.channel, enum.Enum) else brief.channel,
            "type": brief.email_type.value if isinstance(brief.email_type, enum.Enum) else brief.email_type,
            "market": brief.market,
            "audience": brief.audience,
            "brand": brief.brand,
            "objective": brief.objective,
            "iterations": result.iterations_used,
            "passed": passed_count,
            "failed": failed_count,
            "warned": warn_count,
            "all_passed": report.all_passed,
            "elapsed": f"{elapsed:.1f}",
            "created_at": datetime.now().isoformat(),
            "trigger_source": "loop3_webhook",
            "callback_url": payload.callback_url,
        }
        json_filename = output_filename.replace(".html", "") + ".json"
        (out_dir / json_filename).write_text(json.dumps(meta, default=custom_encoder), encoding="utf-8")

    return {
        "status": "success",
        "draft_id": draft_id,
        "all_passed": report.all_passed,
        "iterations_used": result.iterations_used,
        "passed_checks": passed_count,
        "failed_checks": failed_count,
        "warning_checks": warn_count,
        "elapsed_seconds": round(elapsed, 2),
        "html_file": str(output_filename),
        "soft_review_notes": [
            {"concern": n.concern, "detail": n.detail} for n in result.soft_review_notes
        ],
    }
