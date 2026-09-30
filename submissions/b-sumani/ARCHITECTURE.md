# Architecture · Pack Manager

Pack Manager is Stage 3 of 5 in the Cube Buildathon commerce pipeline (Receiving → Prep → **Pack** → Returns → Recovery).
It receives an open-box photograph before sealing along with the customer order lines, performs three distinct checks (`all_items_present`, `quantities_correct`, `nothing_extra`), issues a verdict (`SEAL`, `STOP_AND_FIX`, or `UNCERTAIN`), and creates an evidence record anchored by `unit_id` (`UNIT-0001` to `UNIT-0100`) that downstream pods (Returns and Recovery) consume.

---

## 1. Tenancy Isolation & Database Architecture

Every table is multi-tenant and strictly isolated by `org_id` (e.g. `org_demo_alpha` vs `org_demo_bravo`).

### Core Tables (`schema.sql`)
1. `orgs(id, name, created_at)`
2. `users(id, org_id, email, role, created_at)`
3. `captures(id, org_id, unit_id, order_id, photo_keys, captured_at, operator_id)`
4. `records(id, org_id, unit_id, capture_id, order_lines, observed_in_box, checks, verdict, status, model, model_latency_ms, content_hash, created_at)`
   - `unit_id`: cross-pod join key
   - `id`: prefixed with `PCK-`
   - `status`: `completed` | `pending`
   - `verdict`: `SEAL` | `STOP_AND_FIX` | `UNCERTAIN`
   - Constraint `chk_pending_verdict_null`: When `status = 'pending'`, `verdict` is `NULL`.
5. `overrides(id, org_id, record_id, original_verdict, new_verdict, reason, operator_id, created_at)`
   - Append-only: database trigger `trg_prevent_override_mutation` aborts any `UPDATE` or `DELETE`.
6. `eval_runs(id, org_id, dataset_name, model_name, total_units, metrics, created_at)`
7. `eval_items(id, eval_run_id, org_id, unit_id, ground_truth, predicted, is_match, cause, created_at)`

### Forced Row-Level Security (RLS)
- Every table has both `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY`.
- `FORCE ROW LEVEL SECURITY` ensures policies apply even to table owners (only superusers can bypass).
- **Application Role (`pack_app_user`)**:
  - `rolsuper = false` (never superuser)
  - `rolbypassrls = false` (never has BYPASSRLS)
  - Is NOT the owner of the tables.
  - Does NOT have `UPDATE` or `DELETE` privileges on `overrides`.
  - Service role / admin key is strictly reserved for migrations and administrative setup, never used for tenant queries.

### Transaction-Scoped Parameter Isolation
- Tenant context is passed via `SET LOCAL app.current_org_id = %s;`.
- **Pooling Hygiene**: `SET LOCAL` is executed strictly inside an explicit transaction block (`with conn.transaction():`).
- Upon transaction `COMMIT` or `ROLLBACK`, the setting is automatically discarded by PostgreSQL. It cannot leak across pooled connections (such as PgBouncer or Supabase connection pooling).

---

## 2. Storage & Image Access Architecture

- Images are stored in a private bucket (`public = false`).
- Keys are unguessable, incorporating tenant prefix, unit ID, 128-bit UUID entropy, and a SHA-256 content hash:
  `tenants/{org_id}/{unit_id}/{uuid}_{content_hash[:16]}_{filename}`
- Access is strictly via short-lived signed URLs.
- Before generating or validating a signed URL, the server verifies that the requesting tenant matches the tenant encoded in the storage key. Cross-tenant access is rejected with a `TenancyStorageError`.

---

## 3. Test Suites: Offline vs Live Verification

To maintain strict engineering honesty, the test suites are split into offline logic tests and live PostgreSQL/Supabase verification:

| Test Suite | File | Execution Command | Target Environment | Status / Scope |
|---|---|---|---|---|
| **Offline Tenancy & Logic** | `tests/test_tenancy.py` | `pytest tests/test_tenancy.py` | In-memory engine | Passes offline. Validates schema constraints (`chk_pending_verdict_null`), append-only trigger logic, unguessable storage key format, signed token validation, and static DDL RLS rules. Does **not** verify live PostgreSQL kernel RLS. |
| **Live Database Tenancy** | `tests/test_tenancy_live.py` | `pytest tests/test_tenancy_live.py` | Live PostgreSQL / Supabase | Skips if `DATABASE_URL` is unset. Verifies live `pg_roles` (`rolsuper=false`, `rolbypassrls=false`), table ownership, transaction isolation of `SET LOCAL`, real PostgreSQL kernel RLS enforcement where Bravo cannot read Alpha rows, and private storage bucket isolation. |

> [!IMPORTANT]
> **Tenancy Status: Tenancy logic tested offline.** Live RLS is NOT yet verified until `tests/test_tenancy_live.py` executes against a live Supabase/PostgreSQL instance with `DATABASE_URL` configured and passes.

---

## 4. Vision Model Adapter Architecture (`agent/models/`)

The model adapter follows strict operational constraints designed for warehouse pack stations:

### Single Call Contract (Rule 2)
- Exactly **ONE** model call per unit carrying all checks. Never one call per check, and no secondary LLM calls.
- **Inputs Sent to Model**:
  - Open box photograph bytes.
  - Candidate SKU set: Order SKUs + seller's other SKUs (decoys).
  - **Zero Quantity Leaks**: Order quantities are NEVER sent to the model. The model is asked only what it observes in the box per SKU. The deterministic rules layer compares counts to the order lines.
- **Provider & Active Models**:
  - Development / Iteration: `MODEL_NAME` (configured via env, active: `gemini-3-flash-preview`).
  - Final Evaluation: `MODEL_NAME_EVAL` (configured via env, active: `gemini-3.1-pro-preview` / `gemini-pro-latest`).
  - Native Gemini JSON mode with strict `response_schema` enforced at generation time.

### Transport Retries & Local String Repair
- **Transport Retries**: At most 2 retries for transient HTTP 429 (rate limits) or 5xx (server errors), bound strictly within a total timeout budget (default: 15.0 seconds). Every attempt is logged with timestamp, duration, and status code.
- **Local String Repair (No Second LLM Call)**: If JSON response arrives with markdown code fences (```json ... ```) or trailing commas, a local deterministic regex repair cleans the string before Pydantic parsing. No LLM repair call is permitted.
- **Fail-Open Signal**: If the model times out (`ModelTimeoutError`) or returns corrupt JSON after local repair (`ModelParsingError`), the pipeline catches the error and writes a `status = 'pending'`, `verdict = NULL` record without blocking the warehouse operator.

### Schema Tightening & Candidate Boundary Enforcement
- Confidences are strictly bounded to `[0.0, 1.0]`.
- Count is bounded to `count >= 0`.
- Bounding box is strictly validated to exactly 4 numbers `[ymin, xmin, ymax, xmax]`. (Evidence only, never used in verdict decisions).
- **Candidate Set Enforcement**: Any SKU reported by the model that is outside the candidate set is automatically stripped from `observed_items` and demoted to `unrecognised_items`.

### Evaluation Harness Guard
- The mock adapter has `IS_MOCK = True`.
- `validate_eval_adapter()` strictly rejects mock adapters: the evaluation harness refuses to run with mock adapters to guarantee evaluation numbers are computed exclusively on real vision models.
