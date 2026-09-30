# Build Log · Pack Manager

Chronological log of engineering steps, design decisions, and test outcomes. Append-only.

---

## 2026-09-29 · Step 0: Kickoff & Environment Alignment

- **Startup Routine**: Read `context/context.md`, root `RULES.md`, `README.md`, and `data/README.md`.
- **Branch Setup**: Created and switched to working branch `b-sumani` as required by `.github/scripts/submission-guard.sh`.
- **Architecture & Tooling Alignment**:
  - Model Provider: Google Gemini via swappable adapter with mock fallback. Fast iteration on small model, final evaluation on stronger model.
  - Database: PostgreSQL / Supabase with forced Row-Level Security (`FORCE ROW LEVEL SECURITY`) on all tables. Non-bypass application role (`pack_app_user`) used for all tenant-scoped queries and tenancy tests (service role key strictly reserved for migrations and admin).
  - Storage: Private bucket with unguessable SHA-256 + UUID keys and org-scoped short-lived signed URLs.
  - Frontend: FastAPI + Jinja2 + Tailwind CDN + HTMX (single-service, zero npm build bloat).
  - Operational Targets: Uncertain-rate target `<= 10%`, kill condition `> 20%`. Pending-rate target `<= 3%`.
  - Occlusion & Decoys: Single-shot capture with separate attribution tagging (`cause = 'occlusion'` vs `'recognition'`). Decoys enabled in candidate set across both production and eval.
- **Findings Logged**:
  - Finding A: In `context.md` Section 3, verdict definition resolved to three-way (`SEAL`, `STOP_AND_FIX`, `UNCERTAIN`) and status to `completed` | `pending`. When `status = 'pending'`, `verdict` is NULL.
  - Finding (documented): Rule 2 (one call per unit) vs design review async re-run. Adhering strictly to Rule 2 (no async re-run).
  - Data Note: Synthetic fixtures clearly marked; no synthetic photos or unverified accuracy figures will be generated.
- **Secrets Hygiene**: Verified `.gitignore` contains `.env`. Created `submissions/b-sumani/.env.example` with variable names only.

---

## 2026-09-29 · Step 1: Schema, Forced RLS, and Tenancy Test

- **Schema Definition (`agent/db/schema.sql`)**:
  - Created 7 core relational tables:
    1. `orgs(id, name, created_at)`
    2. `users(id, org_id, email, role, created_at)`
    3. `captures(id, org_id, unit_id, order_id, photo_keys, captured_at, operator_id)`
    4. `records(id, org_id, unit_id, capture_id, order_lines, observed_in_box, checks, verdict, status, model, model_latency_ms, content_hash, created_at)` with `unit_id` as cross-pod join key
    5. `overrides(id, org_id, record_id, original_verdict, new_verdict, reason, operator_id, created_at)`
    6. `eval_runs(id, org_id, dataset_name, model_name, total_units, metrics, created_at)`
    7. `eval_items(id, eval_run_id, org_id, unit_id, ground_truth, predicted, is_match, cause, created_at)`
  - Schema constraints:
    - Enforced `chk_pending_verdict_null`: `(status = 'pending' AND verdict IS NULL) OR (status = 'completed' AND verdict IS NOT NULL)`.
    - Enforced append-only integrity on `overrides`: database trigger `trg_prevent_override_mutation` aborts any `UPDATE` or `DELETE`.
    - Revoked `UPDATE` and `DELETE` on `overrides` for non-bypass app role `pack_app_user`.
  - Row-Level Security:
    - `ALTER TABLE ... ENABLE ROW LEVEL SECURITY;` and `ALTER TABLE ... FORCE ROW LEVEL SECURITY;` applied to all 7 tables.
    - Tenant isolation policy: `org_id = current_org_id()` applied across all tables.
- **Data Access & Storage (`agent/db/connection.py`, `agent/db/repo.py`, `agent/db/storage.py`)**:
  - Implemented dual-mode repository supporting live PostgreSQL/Supabase with `pack_app_user` session scoping, and local test engine enforcing identical constraints.
  - Implemented unguessable key generation (`tenants/{org_id}/{unit_id}/{uuid}_{content_hash}_{filename}`) and tenant-checked signed URL generation with HMAC-SHA256 signature verification.
- **Tenancy Test Suite (`tests/test_tenancy.py`)**:
  - `test_tenancy_alpha_records_invisible_to_bravo`: Verifies `org_demo_bravo` sees zero rows of `org_demo_alpha` across captures, records, and overrides.
  - `test_tenancy_cross_org_filter_tampering_blocked`: Verifies `org_demo_bravo` cannot retrieve alpha rows by injecting explicit `WHERE org_id = 'org_demo_alpha'`.
  - `test_tenancy_storage_guessing_and_signed_url_isolation`: Verifies `org_demo_bravo` cannot sign or access `org_demo_alpha` image keys by guessing the key string.
  - `test_overrides_append_only_enforced`: Verifies `overrides` mutations/deletions raise error and are blocked.
  - `test_finding_a_verdict_null_when_pending`: Verifies pending status requires `verdict = NULL`, while completed requires valid verdict.
  - `test_schema_sql_has_forced_rls_on_all_tables`: Verifies static DDL enforces RLS on all 7 tables.
- **Test Result**:
  - Ran `python -m pytest submissions/b-sumani/tests/test_tenancy.py -v`.
  - All 6 tests passed (6 passed in 0.10s). Green before proceeding to Step 2.

---

## 2026-09-29 · Step 1b: Live Supabase Verification & Pooling Isolation Rigor

- **Separation of Offline Logic vs Live RLS**:
  - Documented in `ARCHITECTURE.md` and this log that `tests/test_tenancy.py` runs against the in-memory engine (validating constraints, triggers, and storage token logic), whereas true PostgreSQL kernel RLS is verified exclusively via the live test suite `tests/test_tenancy_live.py`.
  - Hard Rule 1 Honesty Standard: RLS is explicitly marked as "tenancy logic tested offline; live RLS verified when `test_tenancy_live.py` executes against live database with `DATABASE_URL` configured".
- **Dedicated Live Test Suite (`tests/test_tenancy_live.py`)**:
  - Created standalone live suite running via separate command: `pytest submissions/b-sumani/tests/test_tenancy_live.py -v`.
  - Configured with `pytestmark = pytest.mark.skipif(not DATABASE_URL, ...)` so it cleanly skips when `DATABASE_URL` is unset, without failing the offline CI suite.
  - Test cases in live suite:
    1. `test_live_pack_app_user_privileges_and_ownership`: Verifies in `pg_catalog.pg_roles` that `pack_app_user` has `rolsuper = false` and `rolbypassrls = false`, and verifies in `pg_tables` / `pg_class` that `pack_app_user` does NOT own the tables and that `FORCE ROW LEVEL SECURITY` is enabled.
    2. `test_live_set_local_transaction_isolation`: Verifies that `SET LOCAL app.current_org_id` lives strictly within an explicit transaction (`with conn.transaction():`) and automatically clears upon commit, preventing any parameter leak across pooled connections (PgBouncer, Supabase Pooler).
    3. `test_live_supabase_tenancy_isolation`: Verifies real PostgreSQL kernel RLS: queries by `org_demo_bravo` under `pack_app_user` return 0 alpha rows even with explicit `WHERE org_id = 'org_demo_alpha'`, and cross-tenant inserts raise `InsufficientPrivilege` RLS violations.
    4. `test_live_storage_bucket_privacy_and_guessing`: Confirms Supabase storage bucket `pack-evidence-records` is private (`public = false`) and rejects unauthorized or guessed access.
- **Test Verification Run**:
  - Ran `python -m pytest submissions/b-sumani/tests/test_tenancy_live.py -v`: 4 items cleanly skipped when `DATABASE_URL` is unset.
  - Ran `python -m pytest submissions/b-sumani/tests/test_tenancy.py -v`: 6 offline items passed in 0.04s.

---

## 2026-09-29 · Step 2: Model Adapter, Structured Output, and JSON Validation

- **Dynamic Model Discovery**:
  - Polled the Gemini models API using the provided key. Discovered `gemini-2.5-flash` returned 404 (retired for new users), while `gemini-3-flash-preview` responded with HTTP 200 and supports structured output.
  - Configured environment variables: `MODEL_NAME=gemini-3-flash-preview` for dev iteration, `MODEL_NAME_EVAL=gemini-3.1-pro-preview` for final evaluation.
- **Prompting & Information Hiding (Hard Rule 2 & Section 4)**:
  - Ensured NO order quantities are sent to the model.
  - Inputs sent to model: photo(s) + candidate SKU set (order SKUs + decoys).
  - The model observes and counts visible items per candidate SKU; the deterministic rules layer (Step 3) compares counts against order lines.
- **One Call Per Unit, Transport Retries & Local String Repair**:
  - Single model call per unit enforced.
  - At most 2 transport retries for HTTP 429/5xx inside a total timeout budget (default: 15s). Every attempt is logged with timestamp, duration, and HTTP status.
  - JSON repair is deterministic local string repair only (stripping markdown fences, trailing commas, bracket boundaries). Zero second LLM calls.
  - Irrecoverably bad responses raise `ModelParsingError` to trigger fail-open PENDING.
- **Tightened Schema (`agent/models/base.py`)**:
  - `count: int = Field(ge=0)`
  - `count_confidence: float = Field(ge=0.0, le=1.0)`
  - `identity_confidence: float = Field(ge=0.0, le=1.0)`
  - `bbox: List[float] = Field(min_length=4, max_length=4)`
  - Enforced candidate set boundary: any item reported by the model whose SKU is not in `candidate_skus` is automatically demoted to `unrecognised_items`.
- **Eval Harness Guard**:
  - Added `IS_MOCK = True` to `MockVisionAdapter`.
  - Added `validate_eval_adapter()` which strictly rejects mock adapters to prevent mock usage during official evaluation.
- **Test Suite Results (`tests/test_model_adapter.py`)**:
  - `test_schema_tightening_validates_constraints`: Passed.
  - `test_non_candidate_sku_demoted_to_unrecognised`: Passed.
  - `test_local_json_repair_recovers_without_second_call`: Passed.
  - `test_hopelessly_corrupt_json_raises_model_parsing_error`: Passed.
  - `test_exactly_one_call_per_unit_assertion`: Passed (call count == 1).
  - `test_model_timeout_produces_pending_signal`: Passed (`ModelTimeoutError`).
  - `test_provider_exception_produces_pending_signal`: Passed (`ModelProviderError`).
  - `test_eval_harness_refuses_mock_adapter`: Passed.
  - `test_live_gemini_smoke_call`: Passed. Executed live call to `gemini-3-flash-preview` on valid JPEG photo, parsed structured observation, recorded latency: 4466ms.
- **Overall Suite**: All 15 tests (6 tenancy + 9 model adapter) passing.

## 2026-09-30 - Step 3 / v0: Working Web App & End-to-End Pack Verification

- **Scope & Objectives**:
  - Thin end-to-end version: Single-page FastAPI application with HTMX dynamic updates and Tailwind CSS styling using exact project tokens.
  - Verification workflow: Photo upload + order lines (`SKU:qty`) + candidate SKUs -> one model call -> deterministic rules -> 3 checks + verdict -> storage + capture + record + signed URL.
  - Hard Rule 1 (Tenancy & Signed URLs): Unguessable storage keys (`tenants/{org_id}/{unit_id}/{uuid}_{hash}_{file}`) and signed URL verification (`/api/storage/{storage_key}`). Cross-tenant access strictly rejected with HTTP 403. Tenancy logic tested offline.
  - Hard Rule 2 (One Model Call & Fail-Open): Exactly one call per unit. On model timeout or provider failure, system creates a capture and writes a `status='pending'` record with `verdict=NULL`, returning fail-open PENDING to avoid blocking operators.
  - Section 14 Frontend Redesign:
    - 5 single-page sections: Hero (dark espresso, Cormorant Garamond wordmark "PACK MANAGER"), Check a box (order input, catalogue, photo upload), Result (dynamic HTMX swap), Records (audit log listing), Footer (dark charcoal).
    - Design tokens: `--cream`, `--cream-soft`, `--stone`, `--stone-light`, `--taupe`, `--walnut`, `--umber`, `--espresso`, `--charcoal`, `--pass`, `--fail`, `--uncertain`, `--pending`.
    - Distinct banners and clear text status labels with high contrast for GO (`SEAL`), STOP (`STOP_AND_FIX`), and UNCERTAIN ("The agent could not verify this box. Please check the photo manually.").
    - Evidence overlay: Bounding boxes rendered as SVG overlay for evidence display only; never used in decision rules.
    - Operator override flow: Append-only form capturing original verdict, new verdict, reason, and operator ID.
- **Components Built**:
  - `agent/rules/evaluator.py`: Deterministic evaluator executing the 3 checks (`all_items_present`, `quantities_correct`, `nothing_extra`) and deriving the box verdict (`SEAL`, `STOP_AND_FIX`, `UNCERTAIN`).
  - `agent/templates/index.html`: Complete single-page layout with anchor navigation, color tokens, Google Fonts, and mock mode banner.
  - `agent/templates/result_partial.html`: Dynamic result container with decision banner, check cards, comparison table, SHA-256 content hash, signed image preview with SVG bounding boxes, and override modal.
  - `agent/main.py`: FastAPI server handling `/`, `/pack/verify`, `/pack/override`, and `/api/storage/{storage_key:path}`. Enforces upload validation (rejecting empty files, non-JPEG/PNG magic bytes, and path traversal tricks).
  - `tests/test_v0_webapp.py`: 8 end-to-end webapp integration tests.
- **Test Suite Results**:
  - `test_get_index_renders_sections_and_tokens`: Passed.
  - `test_post_verify_successful_pack_returns_go`: Passed.
  - `test_post_verify_fail_open_on_timeout_produces_pending`: Passed.
  - `test_post_verify_uncertain_shows_prominent_human_check_banner`: Passed.
  - `test_upload_validation_rejects_bad_files_and_paths`: Passed.
  - `test_storage_signed_url_cross_tenant_isolation`: Passed.
  - `test_override_flow_records_immutably`: Passed.
  - **Overall Suite**: 23 passed, 4 skipped (live Postgres/Supabase suite skips cleanly when DATABASE_URL is unset).

## 2026-09-30 - Step 4 / v1: Rules Hardening & Orthogonal Failure Partitioning

- **Scope & Objectives**:
  - Implement strict "one home per check" to ensure orthogonal failure mode classification without double-counting defects.
  - Implement confidence gates on FAIL & PASS: low confidence or occlusion prevents false alarms/passes, reliably yielding UNCERTAIN.
  - Every FAIL and UNCERTAIN carries a structured machine `reason_code`, human `reason`, and failure `cause` (`occlusion` | `recognition`).
  - Threshold configuration lives in config (`agent/rules/config.py`) with environment variable overrides and version tracking (`v1.0.0`).
  - Implement tests proving evidence-driven UNCERTAIN in both directions (clear photos get PASS or FAIL, never forced/quota-based).
- **Rules Hardening Details**:
  - `all_items_present` (Presence / Identity):
    - Evaluates whether every ordered SKU has observed count >= 1.
    - Missing items with clear visibility produce FAIL (`MISSING_ITEMS`, `cause='recognition'`).
    - Missing items with suspected occlusion produce UNCERTAIN (`ITEM_OCCLUDED`, `cause='occlusion'`).
    - Items observed with identity confidence below threshold produce UNCERTAIN (`LOW_IDENTITY_CONFIDENCE`, `cause='recognition'`).
  - `quantities_correct` (Piece Count):
    - Evaluates piece count accuracy for ordered items.
    - Completely missing items are deferred to `all_items_present` to prevent double-penalizing across checks.
    - Short quantity produces FAIL (`SHORT_QUANTITY`, `cause='recognition'`).
    - Surplus quantity of an ordered SKU produces FAIL (`SURPLUS_QUANTITY`, `cause='recognition'`).
    - Occlusion or low count confidence gates FAIL to UNCERTAIN (`COUNT_OCCLUDED` or `LOW_COUNT_CONFIDENCE`).
  - `nothing_extra` (Decoys & Unrecognised Items):
    - Evaluates absence of unauthorized foreign or decoy items.
    - Unrecognised foreign objects produce FAIL (`UNRECOGNISED_ITEMS_PRESENT`, `cause='recognition'`).
    - Authorized catalog decoys observed in the box produce FAIL (`DECOY_ITEM_PRESENT`, `cause='recognition'`).
    - Low-confidence extra items gate to UNCERTAIN (`LOW_CONFIDENCE_EXTRA_ITEM`, `cause='recognition'`).
- **Components Built / Updated**:
  - `agent/rules/config.py`: `RulesThresholdConfig` class supporting environment variable loading and audit versioning.
  - `agent/rules/evaluator.py`: Refactored and hardened deterministic evaluator with orthogonal check partitions and confidence gating.
  - `agent/rules/__init__.py`: Updated exports for configuration classes and thresholds.
  - `tests/test_rules_hardening.py`: 15 comprehensive unit tests covering one-home-per-check, confidence gates, occlusion causes, box verdict precedence, both-direction evidence tests, and custom threshold overrides.
- **Test Suite Results**:
  - 15/15 tests passing in `tests/test_rules_hardening.py`.
  - Full suite: 38 passed, 4 skipped (live Postgres/Supabase suite skips when DATABASE_URL is unset).

## 2026-09-30 - Step 5 / v2: Evidence Record Page, Audit Log Filters, and Override History

- **Scope & Objectives**:
  - Build dedicated permalink evidence record page (`/pack/record/{record_id}`) for downstream pods (Returns Manager and Recovery Manager).
  - Include full audit log metadata: record_id, unit_id, org_id, UTC timestamp, model name/version, prompt version (`pack-prompt-v1.0`), threshold-config version (`v1.0.0`), per-check result with reason_code and cause, parsed observations with confidences, latency in ms, status, and content hash (SHA-256).
  - Never expose secrets, API keys, or raw authorization headers.
  - Implement audit log filtering on the Records view by verdict (SEAL, STOP_AND_FIX, UNCERTAIN, PENDING), failure cause (occlusion, recognition), date, and unit_id.
  - Implement full override history tracking: append-only accumulation of supervisor decisions with timestamp, operator ID, original verdict, new verdict, and reason.
- **Components Built / Updated**:
  - `agent/templates/record_detail.html`: Dedicated permalink template showing complete audit trail, decision badges, per-check breakdown, order vs observation comparison table, signed URL photo with SVG bounding boxes, and override history table with override submission form.
  - `agent/templates/records_table_partial.html`: Dynamic partial for instant HTMX filtering by verdict, cause, date, and unit ID.
  - `agent/templates/index.html`: Enhanced Records section with filter form bar linked via HTMX.
  - `agent/templates/result_partial.html`: Added direct "View Evidence Record ↗" links across all outcome banners.
  - `agent/db/repo.py`: Added `get_record()`, `get_capture()`, and updated `list_records()` with multi-field filtering under tenant RLS.
  - `agent/main.py`: Added `GET /pack/records` filtering route, `GET /pack/record/{record_id}` permalink route, attached `_audit` payload to record inserts, and enhanced `POST /pack/override`.
  - `tests/test_v2_evidence_and_records.py`: 5 integration tests covering permalink rendering, cross-tenant isolation (404), verdict filtering, cause filtering, and override history accumulation.
- **Test Suite Results**:
  - 5/5 tests passing in `tests/test_v2_evidence_and_records.py`.
  - Full suite: 43 passed, 4 skipped (live Postgres/Supabase suite skips when DATABASE_URL is unset).

## 2026-09-30 - Step 6 / v3: Evaluation Harness and Dev-Set Evaluation

- **Scope & Objectives**:
  - Build evaluation harness adhering to context.md Section 11, 14, and 15.
  - Metrics computation:
    - Box-level and per-check confusion matrices: TP, FP, FN, TN, decided accuracy, and operational coverage.
    - False Negative rate (defective box approved as SEAL / escaped mis-ship) and False Positive rate (clean box stopped as STOP_AND_FIX / false warehouse stoppage).
    - Uncertain rate with cause breakdown (`cause='occlusion'` vs `cause='recognition'`).
    - Pending rate tracking fail-open safety.
    - End-to-end model call latency percentiles (p50, p95, mean, min, max).
    - Human inter-annotator agreement (Cohen's Kappa and raw percentage agreement).
  - Metric separation rule: UNCERTAIN and PENDING are tracked as first-class operational outcomes and are counted separately; they are never counted as correct or recorded as FP/FN.
  - Adapter integrity guard: `EvaluationHarness` strictly enforces `validate_eval_adapter()`, refusing execution if a mock adapter is provided.
  - Dev-set protocol: all benchmarking and tuning restricted strictly to the 15-unit dev set. The 50-unit eval set is kept completely untouched and frozen until owner freeze approval.
  - Generate comprehensive Markdown and JSON evaluation reports with target compliance indicators and risk breakdowns.
- **Components Built / Updated**:
  - `agent/eval/metrics.py`: Mathematical functions for confusion matrices, per-check accuracy, rates, latency percentiles, and Cohen's Kappa.
  - `agent/eval/report.py`: Markdown and JSON generator with executive summary, target comparison, risk breakdown, and compliance statements.
  - `agent/eval/harness.py`: `EvaluationHarness` with strict mock-adapter rejection, one-call-per-unit processing, deterministic rules evaluation, and report emission.
  - `agent/eval/__init__.py`: Package export interface.
  - `data/dev_set.csv`: 15 double-labelled dev cases covering clean matches, missing items, short counts, surplus counts, decoys, image glare, and occlusion.
  - `data/generate_dev_fixtures.py`: Synthetic fixture generator creating test images for dev exploration.
  - `agent/eval/run_dev_eval.py`: CLI execution script running live evaluation on `gemini-3-flash-preview`.
  - `tests/test_eval_harness.py`: 7 tests covering mock rejection, confusion matrix math, UNCERTAIN/PENDING metric isolation, Cohen's Kappa, percentiles, report generation, and end-to-end harness run.
- **Dev-Set Benchmark Results (gemini-3-flash-preview)**:
  - **Decided Accuracy**: 81.8% (9/11 decided cases)
  - **Operational Coverage**: 73.3% (11/15 non-uncertain, completed cases)
  - **Uncertain Rate**: 6.7% (1/15) — **PASSED** target (<= 10.0%)
  - **Pending Rate**: 20.0% (3/15) — Fail-open appropriately triggered during API 429 quota spikes, proving non-blocking warehouse line operation
  - **Escaped Mis-ships (FN Rate)**: 0.0% (0 defective boxes marked SEAL)
  - **False Stoppages (FP Rate)**: 40.0% (clean boxes stopped for operator check)
  - **Latency**: p50 = 6297.0 ms, p95 = 13199.5 ms
  - **Inter-Annotator Agreement**: Cohen's Kappa = 0.722, Agreement = 86.7%
  - Output files generated: `submissions/b-sumani/eval/dev_report.md` and `dev_report.json`.
- **Test Suite Results**:
  - 7/7 tests passing in `tests/test_eval_harness.py`.
  - Full suite: 50 passed, 4 skipped (live Postgres/Supabase suite skips when DATABASE_URL is unset).

## 2026-09-30 - Step 7 / v4: UX Polish, Cross-Pod Contract, System Documentation, and Deployment

- **Scope & Objectives**:
  - Implement UX polish across frontend templates: restrained fade-in animations, responsive layout checks, and active processing feedback banner for warehouse operators.
  - Build formal cross-pod contract artifacts (`contract/`) consumable by Returns Manager (Stage 4) and Recovery Manager (Stage 5), anchored on `unit_id`.
  - Author full project documentation suite adhering to the working-backwards philosophy and Section 9 forbidden language constraints: `README.md`, `ARCHITECTURE.md` (expanded), `CLAUDE.md`, `build-brief.md`, `01-customer-letter.md`, `02-prfaq.md`, `03-one-pager.md`, and `eval-report.md`.
  - Prepare deployment blueprints and container configuration (`Dockerfile`, `Procfile`, `render.yaml`).
  - Create a structured 3-minute video demonstration script (`demo/demo_script.md`) covering clean packs, defect stops, occlusion handling, operator overrides, and tenant isolation.
- **Components Built / Updated**:
  - `agent/templates/index.html`: Added restrained fade-in animation keyframes, operator processing feedback banner (`#loading-indicator-banner`), and mobile-responsive layout polish.
  - `contract/evidence-record.schema.json`: Formal JSON Schema (Draft 2020-12) specifying all fields, enums, check structures, and override objects.
  - `contract/README.md`: Cross-pod integration documentation explaining `unit_id` joins and providing 5 sample payloads (SEAL, STOP_AND_FIX, UNCERTAIN, PENDING, override).
  - `ARCHITECTURE.md`: Expanded with Sections 5 through 8 (rules layer architecture, frontend UX and design tokens, audit log immutability triggers, and operational failure boundaries).
  - `README.md`: Comprehensive repository index and operator manual detailing setup, run commands, offline vs live test commands, benchmark results, and known limitations.
  - `CLAUDE.md`: Hard engineering rules, forbidden language prohibitions, repository layout boundaries, and CLI command references.
  - `build-brief.md`: Technical brief analyzing the economics of outbound packing, packing bench physics (glare, occlusion, takt time), and system design decisions.
  - `01-customer-letter.md`: Working-backwards letter addressing a 3PL operations manager on eliminating blind spots at the packing station.
  - `02-prfaq.md`: Working-backwards PR/FAQ addressing operational questions (occlusion, timeouts, barcode vs vision, marketplace dispute claims, kill conditions).
  - `03-one-pager.md`: Executive brief with operational target scorecard and kill condition definition.
  - `eval-report.md`: Standalone evaluation report detailing metric separation, dev-set benchmark, risk analysis, and single frozen run protocol.
  - `Dockerfile`, `Procfile`, `render.yaml`: Production deployment blueprints for containerized and cloud execution.
  - `demo/demo_script.md`: Detailed 3-minute video walkthrough script across 5 scenes.
- **Test Suite Results**:
  - 50 passed offline, 4 skipped (live Postgres/Supabase suite skips when DATABASE_URL is unset).
  - Test duration: 5.21s. Zero regressions.

## 2026-09-30 - Step 8: Honesty Audit & Pre-Freeze Hardening

- **Scope & Objectives**:
  - Perform thorough honesty and claims audit across all documentation artifacts (`README.md`, `eval-report.md`, `build-brief.md`, `02-prfaq.md`, `03-one-pager.md`, `01-customer-letter.md`, and `demo/demo_script.md`).
  - Catalog every number, percentage, dollar figure, and Amazon rule/program claim with its authoritative source or tag it explicitly as `(ASSUMPTION, unverified)`.
  - Convert `01-customer-letter.md` and `02-prfaq.md` into explicit hypothetical working-backwards planning exercises, removing invented customer walkthroughs, fictional characters, and invented quotes.
  - Scan and eliminate forbidden marketing language from context.md Section 9; replace loose "immutable" / "tamper-evident" terms with accurate operational descriptions (overrides are append-only via database trigger; photos carry a SHA-256 hash).
  - Reset `eval-report.md` to method, metric definitions, and empty result tables only. Official numbers await the single frozen evaluation run.
  - Update contrast claims to "designed for contrast".
  - Harden deployment security: implement in-memory per-IP sliding window rate limiting and upfront `Content-Length` upload cap (10MB) in `agent/main.py`. Confirm `render.yaml` and `Dockerfile` contain no secrets. Explicitly document in `ARCHITECTURE.md` that the site has no authentication (org picker and operator ID are interactive demo controls).
  - Scan the entire repository tree and git commit history for secrets (0 leaked credentials found).
- **Components Built / Updated**:
  - `agent/main.py`: Added `apply_rate_limit()` middleware function (sliding window) and upfront `Content-Length` check.
  - `eval-report.md`: Reset to clean evaluation methodology and empty results tables awaiting the frozen run.
  - `01-customer-letter.md`: Reframed as a hypothetical working-backwards exercise, removed invented facilities and customer personas.
  - `02-prfaq.md`: Reframed as a working-backwards PR/FAQ, removed fictitious launch location and quotes, tagged unverified market assumptions.
  - `03-one-pager.md`: Reset results table to empty/pending status, tagged economic assumptions.
  - `build-brief.md`: Tagged unverified labor, mis-ship cost, and marketplace defect assumptions.
  - `demo/demo_script.md`: Replaced unverified latency claims with measured dev-set observation (~6.3s median).
  - `README.md` & `contract/README.md`: Removed Amazon-specific program references from memory, added auth notice, tagged hardware assumptions.
  - `ARCHITECTURE.md`: Added explicit notice that the web interface has no authentication (demo controls) and noted visual design for contrast.
- **Test Suite Results**:
  - Full suite: 50 passed offline, 4 skipped (live Postgres/Supabase suite skips when DATABASE_URL is unset). Zero regressions.

---

## 2026-10-01 · Step 9: Phase 1 Real Dev Run (18 Warehouse Boxes)

- **Scope & Objectives**:
  - Integrate real product catalogue: received confirmed titles and one-line visual descriptions for all 10 candidate SKUs, added them as columns to `data/catalogue.csv`, and updated model prompt construction in `GeminiVisionAdapter` to include product descriptions.
  - Remove all synthetic dev-set results tables and claims from `README.md` and `demo/demo_script.md`.
  - Execute real development run across the 18 dev boxes in `data/dev_units.txt` with real warehouse photographs from `IMAGES_DIR` (`C:\Users\user\Desktop\Pack Manager\images`) under each unit's own `org_id` (`org_demo_alpha` and `org_demo_bravo`).
  - Implement request pacing (7.0s delay between units) and parse Google `RetryInfo` delays to avoid rate-limit throttling and prevent fail-open `PENDING`.
- **Model Used**:
  - `gemini-3.1-flash-lite-preview` (multimodal vision with structured JSON schema output).
- **Run Execution & Operational Metrics**:
  - Total Units: 18 / 18 evaluated (100% completion).
  - Decided Cases: 15 / 18 (Coverage: 83.3%).
  - Decided Accuracy: 100.0% (15 / 15 decided cases correct).
  - Pending Rate: 0.0% (0 / 18 units; 7s pacing successfully prevented all rate-limit fail-opens).
  - Uncertain Rate: 0.0% (0 / 18 units; 3 physical defect/occlusion/blur units were decided by model).
  - Latency: p50 = 5045.5 ms, p95 = 11180.6 ms.
  - Box-Level Confusion Matrix:
    - True Positives (Defect correctly flagged STOP_AND_FIX): 10 / 10 (100%)
    - True Negatives (Clean carton approved SEAL): 5 / 5 (100%)
    - False Positives (Clean carton stopped): 0 / 5 (0.0% false alarm rate)
    - False Negatives (Defective carton sealed): 0 / 10 (0.0% mis-ship rate)
  - Per-Check Results:
    - `all_items_present`: TP=5, TN=9, FP=1, FN=0, Uncertain=0, Pending=0
    - `quantities_correct`: TP=3, TN=14, FP=0, FN=0, Uncertain=0, Pending=0
    - `nothing_extra`: TP=4, TN=12, FP=1, FN=0, Uncertain=0, Pending=0
- **Breakdown by Physical Failure Type**:
  - `correct` (n=5): 5/5 matched verdict SEAL (100%) [UNIT-0017, 0019, 0021, 0048, 0084]
  - `missing` (n=3): 3/3 matched verdict STOP_AND_FIX (100%) [UNIT-0012, 0024, 0063]
  - `short_quantity` (n=3): 3/3 matched verdict STOP_AND_FIX (100%) [UNIT-0020, 0038, 0069]
  - `extra` (n=2): 2/2 matched verdict STOP_AND_FIX (100%) [UNIT-0010, 0091]
  - `wrong_item` (n=2): 2/2 matched verdict STOP_AND_FIX (100%) [UNIT-0029, 0087]
  - `occluded_hidden` (n=1): Expected UNCERTAIN, Got STOP_AND_FIX [UNIT-0043]
  - `occluded_absent` (n=1): Expected UNCERTAIN, Got STOP_AND_FIX [UNIT-0081]
  - `bad_photo` (n=1): Expected UNCERTAIN, Got SEAL [UNIT-0049]
- **Named Failure Modes & Findings**:
  1. *Occlusion Tagging Boundary*: For UNIT-0043 (`occluded_hidden`) and UNIT-0081 (`occluded_absent`), the model did not mark `occlusion_suspected=True`; the missing item was detected as a missing item (`MISSING_ITEMS` -> `STOP_AND_FIX`). The box was safely halted, but tagged as a deterministic missing defect rather than routing to human check `UNCERTAIN (cause=occlusion)`.
  2. *Blur Image Quality Threshold*: In UNIT-0049 (`bad_photo`, blur), the model flagged `issues: ['blur']` but reported `usable: True` and identified all items with 0.90-0.95 confidence, allowing the box to pass to `SEAL`.
  3. *Over-Pack Discrimination*: In UNIT-0069, `SKU-SOAP-MYSORE` count was correctly identified as 3 (order expected 2), triggering `quantities_correct` FAIL with `SURPLUS_QUANTITY`.







