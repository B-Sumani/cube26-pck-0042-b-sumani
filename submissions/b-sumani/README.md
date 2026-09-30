# Pack Manager · Outbound Packaging Verification Agent

**Author:** Sumani (`b-sumani`)  
**Context:** Cube Buildathon · Round 2 Individual Build (Commerce Context Stream)  
**Submission Deadline:** 1 October 2026, 6:00 PM IST  
**Position in Commerce Chain:** Stage 3 of 5 (Receiving → Prep → **Pack** → Returns → Recovery)

---

## 1. What Pack Manager Does

Pack Manager verifies merchant-fulfilled and 3PL outbound orders at the pack station immediately before the parcel is taped and sealed. 

A warehouse operator captures a single photograph of the open box using an everyday phone or packing bench camera. Pack Manager evaluates the photograph against the order lines and the seller's catalog (including production decoys), executing three distinct checks:
1. **`all_items_present`**: Are all expected items in the box?
2. **`quantities_correct`**: Are the exact piece counts present for each ordered SKU?
3. **`nothing_extra`**: Are there any unrecognised items or unauthorized catalog decoys in the box?

The agent renders an immediate decision banner for the operator:
- **`GO` (SEAL)**: All checks pass. Safe to seal and affix shipping label.
- **`STOP` (STOP_AND_FIX)**: One or more conditions failed. Defect explanation and visual evidence provided to fix the box.
- **`STOP` (UNCERTAIN)**: Occlusion, excessive glare, or low vision confidence detected. Prominently instructs the operator: *"The agent could not verify this box. Please check the photo manually."*
- **`Fail-Open` (PENDING)**: External vision provider timeout or outage. Prominently displays: *"Agent unavailable: seal on your own judgment"*. The warehouse packing line is never held up.

Every verification persists a permanent evidence record anchored by `unit_id` (`UNIT-0001` through `UNIT-0100`), which downstream pods consume:
- **Returns Manager (Stage 4)**: Compares returned items against what was physically sealed into the box.
- **Recovery Manager (Stage 5)**: Evaluates buyer claims (empty box, wrong item, missing item) and compiles dispute evidence documentation.

---

## 2. Deliverables Index

| Deliverable | Location | Description |
|---|---|---|
| **System Architecture** | [`ARCHITECTURE.md`](./ARCHITECTURE.md) | Tenancy isolation, adapter contract, deterministic rules, failure boundaries |
| **Agent Working Memory** | [`MEMORY.md`](./MEMORY.md) | In-place snapshot of decisions, operational targets, voice, and current state |
| **Chronological Build Log** | [`build-log.md`](./build-log.md) | Verifiable step-by-step progress record across all build phases (v0–v4) |
| **Cross-Pod Contract** | [`contract/`](./contract/) | Formal JSON schema and documentation for Returns and Recovery pods |
| **Evaluation Report** | [`eval-report.md`](./eval-report.md) | Methodology, dev-set benchmark, metrics separation, and freeze protocol |
| **Customer Letter** | [`01-customer-letter.md`](./01-customer-letter.md) | Working-backwards narrative for merchant-fulfilled sellers and 3PL managers |
| **PR/FAQ** | [`02-prfaq.md`](./02-prfaq.md) | Press release and answers to difficult operational and financial questions |
| **One-Pager & Targets** | [`03-one-pager.md`](./03-one-pager.md) | Single-page brief, operational target scorecard, and kill conditions |
| **Engineering Constraints** | [`CLAUDE.md`](./CLAUDE.md) | Hard rules, non-negotiables, forbidden marketing language, dev commands |
| **Technical Brief** | [`build-brief.md`](./build-brief.md) | Domain brief, pack station physics, fee impact, and system design |
| **Interactive Web App** | [`agent/`](./agent/) | FastAPI backend, Jinja2 templates, HTMX dynamic views, Tailwind CDN |
| **Verification Test Suite** | [`tests/`](./tests/) | 54 comprehensive tests covering tenancy, fail-open, adapter, and rules |

---

## 3. Operational Rules & Non-Negotiables

1. **Forced Multi-Tenant Row-Level Security**: Every table enforces Postgres RLS (`ENABLE` + `FORCE ROW LEVEL SECURITY`). The application runs under a non-bypass role (`pack_app_user`). Tenant context is passed via `SET LOCAL app.current_org_id` strictly inside explicit transaction blocks, preventing cross-tenant leakage across pooled connections.
2. **One Model Call Per Unit**: Exactly one vision model call evaluates the open box carrying all three checks. Secondary LLM calls are prohibited. Transport retries for 429/5xx are capped at 2 attempts inside a strict timeout budget. JSON formatting issues are repaired deterministically via local string routines.
3. **Fail-Open Operational Safety**: If the vision model times out or encounters provider exceptions, the pack line never stops. The system saves the capture, emits a `PENDING` record with `verdict = NULL`, and prompts the operator to seal using their own judgment.
4. **Deterministic Rules Layer**: The vision model never receives order quantities or makes gating decisions. The model reports observed counts and confidences; the deterministic rules engine applies orthogonal checks ("one home per check") and threshold gates.
5. **Separation of Evaluation Metrics**: `UNCERTAIN` and `PENDING` outcomes are tracked as first-class operational categories. They are never counted as correct or classified as false positives/negatives.
6. **Strict Dev-Set / Eval-Set Boundary**: Prompt iterations and threshold calibration are performed exclusively on the 15-unit development set. The 50-unit evaluation set remains frozen and untouched until explicit owner authorization.

---

## 4. Setup and Quickstart

### Prerequisites
- Python 3.11+
- Google Gemini API Key (or offline test mode via `IS_MOCK=true`)
- PostgreSQL / Supabase instance (optional for live tests; in-memory engine runs offline)

### Installation
```bash
# Clone repository and switch to branch
git checkout b-sumani

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Or on Windows: .venv\Scripts\activate

# Install dependencies
pip install -r submissions/b-sumani/requirements.txt

# Configure environment variables
cp submissions/b-sumani/.env.example submissions/b-sumani/.env
# Edit submissions/b-sumani/.env to configure GEMINI_API_KEY and DATABASE_URL
```

### Running the Web Application
```bash
# Start FastAPI application with auto-reload
uvicorn submissions.b-sumani.agent.main:app --reload --port 8000
```
Open [http://localhost:8000](http://localhost:8000) in your browser.

---

## 5. Running the Test Suites

Engineering honesty requires distinguishing offline logic tests from live infrastructure tests:

```bash
# 1. Run all unit and integration tests (Offline suite: 50 passing, 4 live skipped)
python -m pytest submissions/b-sumani/tests/ -v

# 2. Run rules hardening and orthogonal check tests
python -m pytest submissions/b-sumani/tests/test_rules_hardening.py -v

# 3. Run model adapter and single-call tests
python -m pytest submissions/b-sumani/tests/test_model_adapter.py -v

# 4. Run web app and evidence permalink tests
python -m pytest submissions/b-sumani/tests/test_v0_webapp.py submissions/b-sumani/tests/test_v2_evidence_and_records.py -v

# 5. Run evaluation harness tests (Enforces mock rejection and metric math)
python -m pytest submissions/b-sumani/tests/test_eval_harness.py -v

# 6. Run live Supabase tenancy suite (Requires live DATABASE_URL)
DATABASE_URL="postgresql://pack_app_user:secret@db.supabase.co:5432/postgres" \
python -m pytest submissions/b-sumani/tests/test_tenancy_live.py -v
```

> **Note on Tenancy Status**: In-memory tenancy tests pass completely. Per project protocol, documentation states *"tenancy logic tested offline"* until live Supabase tests execute against live PostgreSQL with `DATABASE_URL` configured.

---

## 6. Development Set Benchmark Results

The 18-box development set evaluation runs against real warehouse open-box photographs (`images/`) using the live Gemini vision adapter. Official metrics will be updated upon completion of the real-photo dev run. Only numbers from real-photo runs appear in project documentation.

---

## 7. Assumptions, Known Limitations & Failure Modes

1. **Occlusion Physics**: A top-down single photograph cannot penetrate dunnage, bubble wrap, or items packed in layers. Pack Manager does not attempt to guess hidden items; it routes occluded boxes to `UNCERTAIN` (`cause='occlusion'`).
2. **Catalog Decoys & Vision Discrimination**: When candidate SKUs include decoys with similar visual features, vision models may misidentify items, requiring clear catalogue descriptions to minimize false stoppages.
3. **No Dedicated Hardware Budget**: Designed for flexible stations using an everyday phone or standard bench camera *(ASSUMPTION, unverified)*.
4. **FBA Inapplicability**: If an order is fulfilled by Amazon (FBA), Amazon packs the parcel. Pack Manager applies exclusively to merchant-fulfilled network (MFN) and 3PL fulfillment workflows.
5. **No Authentication on Demo Site**: The current web application has no authentication. The organization dropdown and operator ID are interactive demo controls to demonstrate multi-tenant RLS and audit attribution. Production deployments must bind tenant and operator identity to authenticated sessions (e.g. JWT / SSO).
6. **Visual Accessibility**: Layout, borders, and status badges are designed for contrast across packing station lighting environments.
