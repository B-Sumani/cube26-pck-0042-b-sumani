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
Every defect is evaluated across three orthogonal checks ("one home per check"). All three checks cover all 18 boxes (Decided + Uncertain = 18):

| Check Name | Total | Decided | Accuracy | Coverage | TP | FP | FN | TN | Uncertain | Pending |
|---|---|---|---|---|---|---|---|---|---|---|
| **`all_items_present`** | 18 | 17 | 88.2% (15/17) | 94.4% (17/18) | 6 | 2 | 0 | 9 | 1 | 0 |
| **`quantities_correct`** | 18 | 17 | 100.0% (17/17) | 94.4% (17/18) | 3 | 0 | 0 | 14 | 1 | 0 |
| **`nothing_extra`** | 18 | 17 | 94.1% (16/17) | 94.4% (17/18) | 4 | 1 | 0 | 12 | 1 | 0 |

- **`all_items_present` Details**: Includes `UNIT-0043` as an FP (false FAIL: item physically packed but hidden under bubble wrap, causing model to declare missing) and `UNIT-0081` as a TP (item physically absent with space covered, caught as missing).
- **`UNIT-0069` ("Right Verdict, Wrong Reason")**: The model identified a decoy sunscreen in place of the sanitizer, producing false fails on both `all_items_present` and `nothing_extra`, alongside a legitimate fail on `quantities_correct` (3 soaps packed vs 2 expected). The box stopped as `STOP_AND_FIX` (right verdict), but with erroneous defect attribution.
- **Physical Ground Truth Breakdown on Clean Boxes**: Of the **7 dev boxes that were actually packed correctly** (5 clear boxes + `UNIT-0043` + `UNIT-0049`):
  - **5 were sealed** (`UNIT-0017`, `UNIT-0019`, `UNIT-0021`, `UNIT-0048`, `UNIT-0084`)
  - **1 was a false stop** (`UNIT-0043`, item hidden under bubble wrap)
  - **1 went to manual check** (`UNIT-0049`, blurry photo caught by blur gate)

---

### Run-to-Run Variance (Temperature = 0.0)
To measure stochastic stability, the dev set was executed twice consecutively with `temperature: 0.0` and identical configurations:
- **Verdicts Changed**: **0 of 18 verdicts changed (0.0% variance)**
- **Per-SKU Counts Changed**: **0 per-SKU count changes across all 18 boxes**
- **Latency Distribution**:
  - Run 1: p50 = 3470.0 ms, p95 = 7747.4 ms, mean = 4311.9 ms
  - Run 2: p50 = 5207.0 ms, p95 = 8860.4 ms, mean = 5475.2 ms

> **Important Caveat on Temperature 0**: Temperature 0 was chosen after seeing a dev failure (`UNIT-0021` under default temperature counted 2 soaps instead of 3). Two back-to-back runs do not prove stability over time on a preview model (`gemini-3.1-flash-lite-preview`), as upstream model updates or infrastructure changes can alter outputs even with sampling temperature set to 0.

---

## 7. Assumptions, Known Limitations & Named Failure Modes

Tuning on 18 boxes is inherently small and carries a risk of overfitting. Improvements must be understood as directional rather than proof.

### Named Failure Modes
1. **The model never reports occlusion**: Across all prompt variations and runs, the model never flagged `occlusion_suspected=True` or `partially_occluded=True`. Consequently, `occluded_hidden` (where an item is hidden under bubble wrap but present) and `occluded_absent` (where an item is missing and packaging covers the space) are not detected as occlusions. `UNIT-0043` results in an unnecessary false stop, while `UNIT-0081` is stopped only because the item is not seen.
2. **Counting 3 identical items is unstable**: In the pre-temperature-0 run, `UNIT-0021` produced a false stop because the model counted 2 Mysore Sandal soap cartons instead of 3. With `temperature: 0.0`, it consistently counted 3. Counting adjacent identical items remains sensitive to small model variance.
3. **The blur gate depends on the model reporting blur**: In `UNIT-0049`, the blur gate successfully converted an unverified `SEAL` into `UNCERTAIN`. However, this is a **directional result from one box, not a fix**. If the model fails to include `"blur"` in `image_quality.issues`, the rule cannot fire.
4. **Uncalibrated Model Confidence (Inactive Thresholds)**: model-reported confidence was near-constant on the dev set and is not a reliable signal (all 50 observed item instances across all 18 dev boxes returned exactly 1.00 count_confidence and 1.00 identity_confidence, including on blurry and occluded boxes). Consequently, the confidence thresholds (0.70 identity, 0.65 count) are inactive in practice. Verdict decisions on ambiguous or degraded photos are guarded by the deterministic image quality and defect rules, not by raw confidence scores.

### Operational Assumptions
1. **No Dedicated Hardware Budget**: Designed for flexible stations using an everyday phone or standard bench camera *(ASSUMPTION, unverified)*.
2. **FBA Inapplicability**: If an order is fulfilled by Amazon (FBA), Amazon packs the parcel. Pack Manager applies exclusively to merchant-fulfilled network (MFN) and 3PL fulfillment workflows.
3. **Demo Organisation Switch (Not Secure Authentication)**: The login page at `/login` provides a demo organisation switch with two one-click buttons ("Enter as Alpha Demo Merchant" and "Enter as Bravo Demo Merchant") with no credentials or passwords. It sets a signed session cookie (`pack_session`) holding `org_id` strictly to demonstrate multi-tenant database row-level security and tenant separation. It is NOT authentication or a secure login system. Production deployments must bind tenant and operator identity to enterprise SSO/OIDC/SAML.
4. **Per-Organisation Seller Catalogue & Future OMS Work**: Product catalogue items (SKU, title, description) are stored per organisation in the `catalogue_items` table under forced RLS. The packing verification form uses an interactive product picker built from the seller's active catalogue. Pulling customer orders and order lines directly from an Order Management System (OMS/WMS) via API or scanner is future work.
5. **Visual Accessibility**: Layout, borders, and status badges are designed for contrast across packing station lighting environments.

---

## 8. Changes After Scoring

- **Official Exam Score**: The official held-out exam score comes from the frozen commit `b5c04f3` ("Final prompt v2.2-occlusion-narrow, frozen before held-out exam"), with results stored in `exam_final/`. The exam was not rerun.
- **Post-Scoring Prompt Adjustments**: After inspecting the exam failures, two prompt-wording changes were made and tested on the dev set only (detailed breakdown and metrics are in [`post_scoring_changes.md`](./post_scoring_changes.md)):
  1. Image-quality wording for cut-off frames and glare (commit `1e52743`).
  2. Strict printed-title matching for look-alike items (commit `0350436`).
- **Validation Scope**: Both changes are post-scoring and not validated on held-out data; the dev set contains no glare, cut-off, or look-alike-swap cases, so their effect on those cases is untested.
- **Known Model Limitations**: Named cases that need a stronger model, not a prompt change:
  - `UNIT-0093`: extra item (Nivea Body Milk) not detected; the model did not see the extra item.
  - `UNIT-0046`: partially hidden item not detected; the model reported no occlusion.
- **Own-Photo Test Set**: A separate own-photo test set (18 boxes) was planned but not run, for lack of time.

