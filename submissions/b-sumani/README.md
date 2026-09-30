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

The 18-box development set was evaluated against real warehouse open-box photographs (`images/`) using the live `gemini-3.1-flash-lite-preview` model (run date: 2026-10-01; preview model) with candidate SKUs accompanied by seller catalogue packaging descriptions.

### Primary Operational Headline (Raw Counts)
- **Bad boxes sealed (Escaped mis-ships / FN)**: **0 of 10** (0.0% mis-ship rate)
- **Good boxes stopped (False alarms / FP)**: **0 of 15** in final temperature=0 run (0.0% false alarm rate); was **1 of 15** (FP = 1 on UNIT-0021) in the pre-temperature-0 run
- **UNCERTAIN recall on hard/ambiguous boxes**: **1 of 3** (33.3% recall; blur caught, occlusions halted as missing items)
- **Operational Coverage**: **18 of 18** (100.0% coverage; all 18 boxes received an actionable outcome: 17 decided, 1 UNCERTAIN, 0 PENDING)
- **Pending Rate (Fail-Open)**: **0 of 18** (0.0% fail-open rate)
- **Uncertain Rate**: **1 of 18** (5.6% uncertain rate)

> **Batch-Runner Pacing Note**: The 7-second inter-unit pacing configured in the evaluation harness is a batch-runner test harness control to respect API rate limits during automated benchmark execution, explaining why `pending = 0`; it is not a live-use latency or packing station throughput claim. Live packing requests execute on-demand.

---

### Main Table: Clear Boxes (15 Units)
Performance on the 15 clean, missing, short, extra, and wrong-item cartons where physical contents are fully unobstructed:

| Metric Category | Raw Count | Rate | Notes |
|---|---|---|---|
| **Defective Cartons Correctly Stopped (TP)** | 10 of 10 | 100.0% | Missing, short, extra, and wrong-item boxes stopped |
| **Clean Cartons Correctly Approved (TN)** | 5 of 5 | 100.0% | Clean boxes approved (4 of 5 in pre-temp=0 run) |
| **Clean Cartons Erroneously Stopped (FP)** | 0 of 15 | 0.0% | 1 of 15 in pre-temp=0 run (UNIT-0021 soap count) |
| **Defective Cartons Erroneously Approved (FN)** | 0 of 10 | 0.0% | Zero bad boxes escaped |
| **Clear Box Accuracy** | 15 of 15 (100.0%) | — | Operational coverage: 15 of 15 (100.0%) |

*(Note: Prior to setting `temperature: 0.0`, clear box accuracy was 14 of 15 with coverage 15 of 15, due to 1 false stop on UNIT-0021).*

---

### Hard Table: Ambiguous & Distorted Boxes (3 Units)
Performance on the 3 hard boxes containing severe blur, hidden items under bubble wrap, or items absent with packing covering the void:

| Unit ID | Physical Defect Type | Intended Target | Actual Predicted Verdict | Operational Outcome |
|---|---|---|---|---|
| **UNIT-0049** | `bad_photo, blur` | `UNCERTAIN` | `UNCERTAIN` | **Caught by blur gate** (`cause='recognition'`) |
| **UNIT-0043** | `occluded_hidden` | `UNCERTAIN` | `STOP_AND_FIX` | **False stop**: item hidden under bubble wrap caught as missing item |
| **UNIT-0081** | `occluded_absent` | `UNCERTAIN` | `STOP_AND_FIX` | **Safe stop**: absent item with covered void caught as missing item |

- **UNCERTAIN Recall on Hard Boxes**: **1 of 3 (33.3%)**
- Neither occluded box (`UNIT-0043`, `UNIT-0081`) was flagged with `occlusion_suspected=True` by the model; both were stopped deterministically because the required item was not detected (`MISSING_ITEMS`).

---

### Orthogonal Check Performance (Final Run)
Every defect is evaluated across three orthogonal checks ("one home per check"):

| Check Name | Total | Decided | Accuracy | Coverage | TP | FP | FN | TN | Uncertain | Pending |
|---|---|---|---|---|---|---|---|---|---|---|
| **`all_items_present`** | 18 | 15 | 93.3% (14/15) | 83.3% (15/18) | 5 | 1 | 0 | 9 | 1 | 0 |
| **`quantities_correct`** | 18 | 17 | 100.0% (17/17) | 94.4% (17/18) | 3 | 0 | 0 | 14 | 1 | 0 |
| **`nothing_extra`** | 18 | 17 | 94.1% (16/17) | 94.4% (17/18) | 4 | 1 | 0 | 12 | 1 | 0 |

*(Note: In `UNIT-0069`, the model observed decoy sunscreen instead of ordered sanitizer, triggering FP on `all_items_present` and `nothing_extra` while still halting the box via `STOP_AND_FIX`).*

---

### Run-to-Run Variance (Temperature = 0.0)
To measure stochastic stability, the dev set was executed twice consecutively with `temperature: 0.0` and identical configurations:
- **Verdicts Changed**: **0 of 18 verdicts changed (0.0% variance)**
- **Per-SKU Counts Changed**: **0 per-SKU count changes across all 18 boxes**
- **Latency Distribution**:
  - Run 1: p50 = 3470.0 ms, p95 = 7747.4 ms, mean = 4311.9 ms
  - Run 2: p50 = 5207.0 ms, p95 = 8860.4 ms, mean = 5475.2 ms

---

## 7. Assumptions, Known Limitations & Named Failure Modes

Tuning on 18 boxes is inherently small and carries a risk of overfitting. Improvements must be understood as directional rather than proof.

### Named Failure Modes
1. **The model never reports occlusion**: Across all prompt variations and runs, the model never flagged `occlusion_suspected=True` or `partially_occluded=True`. Consequently, `occluded_hidden` (where an item is hidden under bubble wrap but present) and `occluded_absent` (where an item is missing and packaging covers the space) are not detected as occlusions. `UNIT-0043` results in an unnecessary false stop, while `UNIT-0081` is stopped only because the item is not seen.
2. **Counting 3 identical items is unstable**: In the pre-temperature-0 run, `UNIT-0021` produced a false stop because the model counted 2 Mysore Sandal soap cartons instead of 3. With `temperature: 0.0`, it consistently counted 3. Counting adjacent identical items remains sensitive to small model variance.
3. **The blur gate depends on the model reporting blur**: In `UNIT-0049`, the blur gate successfully converted an unverified `SEAL` into `UNCERTAIN`. However, this is a **directional result from one box, not a fix**. If the model fails to include `"blur"` in `image_quality.issues`, the rule cannot fire.

### Operational Assumptions
1. **No Dedicated Hardware Budget**: Designed for flexible stations using an everyday phone or standard bench camera *(ASSUMPTION, unverified)*.
2. **FBA Inapplicability**: If an order is fulfilled by Amazon (FBA), Amazon packs the parcel. Pack Manager applies exclusively to merchant-fulfilled network (MFN) and 3PL fulfillment workflows.
3. **No Authentication on Demo Site**: The current web application has no authentication. The organization dropdown and operator ID are interactive demo controls to demonstrate multi-tenant RLS and audit attribution. Production deployments must bind tenant and operator identity to authenticated sessions (e.g. JWT / SSO).
4. **Visual Accessibility**: Layout, borders, and status badges are designed for contrast across packing station lighting environments.
