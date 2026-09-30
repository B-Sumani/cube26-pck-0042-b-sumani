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
