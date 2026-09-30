"""FastAPI Web Application for Pack Manager (Stage 3).

Follows context.md Section 11 (v0) & Section 14 (Website scope & frontend design):
- Single-page application serving Hero, Check Box, Result, Records, and Footer.
- Upload validation: JPEG/PNG only, <= 10MB limit, no path traversal tricks.
- Keys never reach browser; images served strictly through org-scoped signed URLs.
- Fail open: On timeout or provider/parsing error, saves capture and writes PENDING record without blocking operator.
- Deterministic rules layer decides PASS/FAIL/UNCERTAIN.
- Append-only overrides stored with full audit trail.
"""

from __future__ import annotations
import os
import re
import uuid
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from fastapi import FastAPI, Request, Form, File, UploadFile, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

from agent.db.repo import PackRepository
from agent.db.storage import (
    generate_storage_key,
    create_signed_url,
    verify_signed_token,
    save_file_bytes,
    get_file_bytes,
    TenancyStorageError,
)
from agent.models.base import (
    VisionModelAdapter,
    ModelObservation,
    ModelTimeoutError,
    ModelProviderError,
    ModelParsingError,
)
from agent.models.gemini import GeminiVisionAdapter
from agent.models.mock import MockVisionAdapter
from agent.rules.evaluator import evaluate_pack_box, parse_order_lines
from agent.rules.config import DEFAULT_CONFIG

load_dotenv()

PROMPT_VERSION = "pack-prompt-v1.0"

app = FastAPI(
    title="Pack Manager",
    description="Pre-seal box verification and evidence recording agent",
    version="0.1.0"
)

# Template setup
TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

import time
from collections import defaultdict

# Allowed MIME types and max upload size (10 MB)
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/jpg"}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB

# In-memory sliding window rate limiter per client IP
_rate_limit_history: Dict[str, List[float]] = defaultdict(list)
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_PER_MINUTE = int(os.getenv("PACK_RATE_LIMIT_PER_MINUTE", "60"))


def apply_rate_limit(client_ip: str, max_requests: int = RATE_LIMIT_MAX_PER_MINUTE, window: int = RATE_LIMIT_WINDOW_SECONDS) -> None:
    """Enforces per-IP rate limiting to guard against denial-of-service and quota exhaustion."""
    now = time.time()
    recent = [t for t in _rate_limit_history[client_ip] if now - t < window]
    if len(recent) >= max_requests:
        raise HTTPException(
            status_code=429,
            detail=f"Too Many Requests: Rate limit exceeded ({max_requests} requests/minute). Please wait before retrying."
        )
    recent.append(now)
    _rate_limit_history[client_ip] = recent

# Active model adapter instance (singleton or injectable for testing)
_adapter_instance: Optional[VisionModelAdapter] = None


def get_adapter() -> VisionModelAdapter:
    """Returns the configured vision model adapter."""
    global _adapter_instance
    if _adapter_instance is not None:
        return _adapter_instance

    provider = os.getenv("MODEL_PROVIDER", "gemini").lower()
    api_key = os.getenv("GEMINI_API_KEY")

    if provider == "gemini" and api_key and not api_key.startswith("your_"):
        _adapter_instance = GeminiVisionAdapter(api_key=api_key)
    else:
        _adapter_instance = MockVisionAdapter()
    return _adapter_instance


def set_adapter(adapter: VisionModelAdapter) -> None:
    """Helper for testing to inject a custom adapter."""
    global _adapter_instance
    _adapter_instance = adapter


def parse_candidate_skus(raw_text: str) -> List[str]:
    """Parses candidates string into clean list of unique SKUs."""
    tokens = re.split(r"[;,\n\r]+", raw_text.strip())
    skus = []
    for t in tokens:
        clean = t.strip()
        if clean and clean not in skus:
            skus.append(clean)
    return skus


@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request, org_id: str = "org_demo_alpha"):
    """Renders single-page application with 5 sections."""
    adapter = get_adapter()
    repo = PackRepository(org_id=org_id)
    repo.create_org(org_id, "Demo Merchant")
    recent_records = repo.list_records()

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "selected_org": org_id,
            "is_mock": getattr(adapter, "IS_MOCK", False),
            "recent_records": recent_records,
        }
    )


@app.post("/pack/verify", response_class=HTMLResponse)
async def verify_pack_box(
    request: Request,
    org_id: str = Form(...),
    order_id: str = Form(...),
    unit_id: str = Form(...),
    order_lines: str = Form(...),
    candidate_skus: str = Form(...),
    operator_id: str = Form("op_default"),
    photo: UploadFile = File(...)
):
    """Core pack verification endpoint.
    
    1. Validates upload format and size.
    2. Stores photo under unguessable key in private storage.
    3. Calls model (ONE call per unit).
    4. Evaluates deterministic rules.
    5. Saves record in DB (or PENDING on failure).
    6. Swaps result_partial into #result-container.
    """
    adapter = get_adapter()
    repo = PackRepository(org_id=org_id)
    repo.create_org(org_id, "Demo Organization")

    # 0. Enforce Rate Limiting and Content-Length Upload Cap
    client_ip = request.client.host if request.client else "127.0.0.1"
    apply_rate_limit(client_ip)

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_FILE_SIZE_BYTES:
                raise HTTPException(status_code=400, detail="File too large. Maximum size is 10 MB.")
        except ValueError:
            pass

    # 1. Upload Validation
    raw_filename = photo.filename or "box.jpg"
    if ".." in raw_filename or "/" in raw_filename or "\\" in raw_filename:
        raise HTTPException(status_code=400, detail="Invalid filename: path traversal tricks forbidden.")
    filename = os.path.basename(raw_filename)

    # Read photo bytes and check size
    photo_bytes = await photo.read()
    if len(photo_bytes) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 10 MB.")
    if len(photo_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # Validate header magic bytes for JPEG / PNG
    is_jpeg = photo_bytes.startswith(b"\xff\xd8")
    is_png = photo_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    if not (is_jpeg or is_png):
        raise HTTPException(status_code=400, detail="Invalid image format. Only JPEG and PNG are allowed.")

    # 2. Store photo under unguessable key
    storage_key = generate_storage_key(
        org_id=org_id,
        unit_id=unit_id,
        filename=filename,
        content_bytes=photo_bytes
    )
    save_file_bytes(storage_key, photo_bytes)
    signed_image_url = create_signed_url(org_id=org_id, storage_key=storage_key)

    # 3. Create Capture Record
    capture_id = f"CAP-{uuid.uuid4().hex[:8].upper()}"
    repo.insert_capture(
        capture_id=capture_id,
        unit_id=unit_id,
        order_id=order_id,
        photo_keys=[storage_key],
        operator_id=operator_id
    )

    # 4. Parse candidate SKUs (Candidates = Order SKUs + Decoys)
    candidates_list = parse_candidate_skus(candidate_skus)
    order_dict = parse_order_lines(order_lines)
    for expected_sku in order_dict.keys():
        if expected_sku not in candidates_list:
            candidates_list.append(expected_sku)

    # 5. Model Execution with Fail-Open Safeguard
    record_id = f"PCK-{uuid.uuid4().hex[:8].upper()}"
    status = "completed"
    verdict: Optional[str] = None
    checks: Dict[str, Any] = {}
    latency_ms = 0
    model_name = getattr(adapter, "model_name", "mock-adapter")
    observation = None

    try:
        # ONE call per unit carrying candidate SKUs only (Zero order quantities sent!)
        observation, latency_ms = adapter.analyze_box(
            image_bytes=photo_bytes,
            candidate_skus=candidates_list
        )
        # 6. Deterministic Rules Layer
        checks, verdict, operator_action = evaluate_pack_box(
            order_lines_str=order_lines,
            observation=observation,
            candidate_skus=candidates_list
        )

    except (ModelTimeoutError, ModelProviderError, ModelParsingError, Exception) as err:
        # FAIL OPEN: Model error or timeout saves capture, produces PENDING record, does not block operator
        status = "pending"
        verdict = None
        checks = {}
        latency_ms = latency_ms or 0

    # 7. Save Record to Database (with forced RLS)
    observed_str = None
    if observation and status == "completed":
        observed_tokens = [f"{item.sku}:{item.count}" for item in observation.observed_items if item.count > 0]
        observed_str = ";".join(observed_tokens) if observed_tokens else "NONE"

    hash_input = f"{org_id}:{unit_id}:{order_lines}:{observed_str}:{status}:{verdict}"
    content_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()

    checks_payload = {
        **checks,
        "_audit": {
            "prompt_version": PROMPT_VERSION,
            "threshold_config_version": DEFAULT_CONFIG.version,
            "observations": [item.model_dump() for item in observation.observed_items] if observation else [],
            "image_quality": observation.image_quality.model_dump() if observation else {"usable": False, "issues": []},
            "occlusion_suspected": observation.occlusion_suspected if observation else False,
        }
    }

    repo.insert_record(
        record_id=record_id,
        unit_id=unit_id,
        capture_id=capture_id,
        order_lines=order_lines,
        observed_in_box=observed_str,
        checks=checks_payload,
        verdict=verdict,
        status=status,
        model=model_name,
        model_latency_ms=latency_ms,
        content_hash=content_hash
    )

    # 8. Build Evidence Comparison Table and Bounding Boxes
    comparison_table = []
    observed_map = {}
    if observation:
        for item in observation.observed_items:
            observed_map[item.sku] = item

    for sku, exp_qty in order_dict.items():
        obs_item = observed_map.get(sku)
        obs_count = obs_item.count if obs_item else 0
        comparison_table.append({
            "sku": sku,
            "expected_qty": exp_qty,
            "observed_count": obs_count,
            "count_conf": obs_item.count_confidence if obs_item else None,
            "ident_conf": obs_item.identity_confidence if obs_item else None,
            "occluded": obs_item.partially_occluded if obs_item else False,
            "mismatch": obs_count != exp_qty
        })

    # Check for surplus or decoy items seen
    if observation:
        for item in observation.observed_items:
            if item.sku not in order_dict and item.count > 0:
                comparison_table.append({
                    "sku": f"{item.sku} (DECOY/EXTRA)",
                    "expected_qty": 0,
                    "observed_count": item.count,
                    "count_conf": item.count_confidence,
                    "ident_conf": item.identity_confidence,
                    "occluded": item.partially_occluded,
                    "mismatch": True
                })

    bboxes = []
    if observation:
        for item in observation.observed_items:
            if item.bbox and len(item.bbox) == 4 and any(v > 0 for v in item.bbox):
                bboxes.append({
                    "ymin": item.bbox[0],
                    "xmin": item.bbox[1],
                    "ymax": item.bbox[2],
                    "xmax": item.bbox[3],
                    "label": f"{item.sku} ({item.count})"
                })

    return templates.TemplateResponse(
        request=request,
        name="result_partial.html",
        context={
            "org_id": org_id,
            "unit_id": unit_id,
            "record_id": record_id,
            "status": status,
            "verdict": verdict,
            "checks": checks,
            "model_name": model_name,
            "model_latency_ms": latency_ms,
            "content_hash": content_hash,
            "comparison_table": comparison_table,
            "signed_image_url": signed_image_url,
            "bboxes": bboxes,
        }
    )


@app.get("/pack/records", response_class=HTMLResponse)
async def filter_records_table(
    request: Request,
    org_id: str = Query("org_demo_alpha"),
    verdict: Optional[str] = Query(None),
    cause: Optional[str] = Query(None),
    date: Optional[str] = Query(None),
    unit_id: Optional[str] = Query(None)
):
    """Filters audit log records for the active tenant under RLS."""
    repo = PackRepository(org_id=org_id)
    records = repo.list_records(
        unit_id=unit_id if unit_id and unit_id.strip() else None,
        verdict=verdict if verdict and verdict.strip() else None,
        cause=cause if cause and cause.strip() else None,
        date_str=date if date and date.strip() else None,
    )
    return templates.TemplateResponse(
        request=request,
        name="records_table_partial.html",
        context={
            "recent_records": records,
            "selected_org": org_id,
        }
    )


@app.get("/pack/record/{record_id}", response_class=HTMLResponse)
async def get_record_detail(
    request: Request,
    record_id: str,
    org_id: str = Query("org_demo_alpha")
):
    """Renders dedicated permalink evidence record page for downstream pods."""
    repo = PackRepository(org_id=org_id)
    record = repo.get_record(record_id)
    if not record:
        raise HTTPException(
            status_code=404,
            detail=f"Evidence record '{record_id}' not found for organization '{org_id}'."
        )

    capture = repo.get_capture(record["capture_id"]) if record.get("capture_id") else None
    overrides = repo.list_overrides(record_id)

    # Generate signed URL for photo if available
    signed_image_url = None
    if capture and capture.get("photo_keys"):
        first_key = capture["photo_keys"][0]
        signed_image_url = create_signed_url(org_id=org_id, storage_key=first_key)

    checks_dict = record.get("checks", {})
    audit_meta = checks_dict.get("_audit", {
        "prompt_version": PROMPT_VERSION,
        "threshold_config_version": DEFAULT_CONFIG.version,
        "observations": [],
        "image_quality": {"usable": True, "issues": []}
    })

    # Build comparison table and bboxes
    order_dict = parse_order_lines(record["order_lines"])
    observations_list = audit_meta.get("observations", [])
    observed_map = {item.get("sku"): item for item in observations_list if isinstance(item, dict)}

    comparison_table = []
    for sku, exp_qty in order_dict.items():
        obs_item = observed_map.get(sku)
        obs_count = obs_item.get("count", 0) if obs_item else 0
        comparison_table.append({
            "sku": sku,
            "expected_qty": exp_qty,
            "observed_count": obs_count,
            "count_conf": obs_item.get("count_confidence") if obs_item else None,
            "ident_conf": obs_item.get("identity_confidence") if obs_item else None,
            "occluded": obs_item.get("partially_occluded", False) if obs_item else False,
            "mismatch": obs_count != exp_qty
        })

    for item in observations_list:
        if isinstance(item, dict):
            sku = item.get("sku")
            count = item.get("count", 0)
            if sku and sku not in order_dict and count > 0:
                comparison_table.append({
                    "sku": f"{sku} (DECOY/EXTRA)",
                    "expected_qty": 0,
                    "observed_count": count,
                    "count_conf": item.get("count_confidence"),
                    "ident_conf": item.get("identity_confidence"),
                    "occluded": item.get("partially_occluded", False),
                    "mismatch": True
                })

    bboxes = []
    for item in observations_list:
        if isinstance(item, dict):
            sku = item.get("sku")
            count = item.get("count", 0)
            bbox = item.get("bbox")
            if bbox and len(bbox) == 4 and any(v > 0 for v in bbox):
                bboxes.append({
                    "ymin": bbox[0],
                    "xmin": bbox[1],
                    "ymax": bbox[2],
                    "xmax": bbox[3],
                    "label": f"{sku} ({count})"
                })

    return templates.TemplateResponse(
        request=request,
        name="record_detail.html",
        context={
            "record": record,
            "capture": capture,
            "overrides": overrides,
            "signed_image_url": signed_image_url,
            "comparison_table": comparison_table,
            "bboxes": bboxes,
            "audit_metadata": audit_meta,
        }
    )


@app.post("/pack/override", response_class=HTMLResponse)
async def submit_override(
    request: Request,
    record_id: str = Form(...),
    org_id: str = Form(...),
    original_verdict: str = Form(...),
    new_verdict: str = Form(...),
    reason: str = Form(...),
    operator_id: str = Form("op_default")
):
    """Records an append-only human operator override via database trigger."""
    client_ip = request.client.host if request.client else "127.0.0.1"
    apply_rate_limit(client_ip)

    repo = PackRepository(org_id=org_id)
    override_id = f"OVR-{uuid.uuid4().hex[:8].upper()}"
    
    repo.insert_override(
        override_id=override_id,
        record_id=record_id,
        original_verdict=original_verdict,
        new_verdict=new_verdict,
        reason=reason,
        operator_id=operator_id
    )

    overrides = repo.list_overrides(record_id)

    return HTMLResponse(
        f"""<div class="bg-white border border-[var(--stone)] p-4 rounded-lg shadow mt-4 text-xs font-mono">
            <div class="font-bold text-[var(--pass)]">✓ Override Recorded ({override_id}):</div>
            <div class="mt-1">{record_id} changed from <span class="line-through">{original_verdict}</span> to <strong class="text-[var(--pass)]">{new_verdict}</strong> by {operator_id}.</div>
            <div class="text-[11px] text-[var(--taupe)] mt-1">Reason: "{reason}"</div>
            <div class="text-[11px] text-[var(--taupe)] mt-2 font-sans font-semibold">Total Overrides on Record: {len(overrides)}</div>
        </div>"""
    )


@app.get("/api/storage/{storage_key:path}")
async def serve_signed_image(
    storage_key: str,
    org: str = Query(...),
    expires: int = Query(...),
    sig: str = Query(...)
):
    """Serves images strictly via org-scoped, unexpired signed URLs.
    
    Hard Rule 1: A second organization guessing an image key cannot fetch it.
    """
    is_valid = verify_signed_token(
        storage_key=storage_key,
        requesting_org=org,
        expires_at=expires,
        signature=sig
    )
    if not is_valid:
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Invalid, expired, or cross-tenant signed URL."
        )

    file_bytes = get_file_bytes(storage_key)
    if not file_bytes:
        raise HTTPException(status_code=404, detail="Image not found in storage.")

    media_type = "image/png" if storage_key.endswith(".png") else "image/jpeg"
    return Response(content=file_bytes, media_type=media_type)
