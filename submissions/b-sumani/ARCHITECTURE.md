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

---

## 5. Deterministic Rules Layer Architecture (`agent/rules/`)

The rules layer sits between raw model observations and database persistence. It is completely deterministic and decoupled from the vision provider.

### Orthogonal Check Partitioning ("One Home Per Check")
Every packaging defect is assigned to exactly one check to prevent cascading or ambiguous failures:
1. `all_items_present` (Presence / Identity):
   - Evaluates whether every ordered SKU has an observed count $\ge 1$.
   - Missing item with clear visibility $\to$ `FAIL` (`MISSING_ITEMS`, `cause='recognition'`).
   - Missing item with occlusion detected $\to$ `UNCERTAIN` (`ITEM_OCCLUDED`, `cause='occlusion'`).
   - Observed SKU with identity confidence below threshold $\to$ `UNCERTAIN` (`LOW_IDENTITY_CONFIDENCE`, `cause='recognition'`).
2. `quantities_correct` (Piece Count Accuracy):
   - Evaluates count accuracy for ordered items present in the box.
   - Completely missing items are deferred to `all_items_present` (no double-counting).
   - Short count $\to$ `FAIL` (`SHORT_QUANTITY`, `cause='recognition'`).
   - Surplus count $\to$ `FAIL` (`SURPLUS_QUANTITY`, `cause='recognition'`).
   - Count confidence below threshold or count occlusion $\to$ `UNCERTAIN` (`COUNT_OCCLUDED` or `LOW_COUNT_CONFIDENCE`).
3. `nothing_extra` (Decoys & Foreign Items):
   - Evaluates absence of unauthorized items in the box.
   - Unrecognised foreign objects $\to$ `FAIL` (`UNRECOGNISED_ITEMS_PRESENT`, `cause='recognition'`).
   - Authorized seller catalog decoys present $\to$ `FAIL` (`DECOY_ITEM_PRESENT`, `cause='recognition'`).
   - Extra item with low confidence $\to$ `UNCERTAIN` (`LOW_CONFIDENCE_EXTRA_ITEM`, `cause='recognition'`).

### Decision Precedence Hierarchy
When combining the three checks into a box-level verdict:
$$\text{FAIL} \succ \text{UNCERTAIN} \succ \text{PASS}$$
- If ANY check is `FAIL`, the box verdict is `STOP_AND_FIX`.
- Else if ANY check is `UNCERTAIN`, the box verdict is `UNCERTAIN` (operator sees `STOP`).
- If ALL three checks are `PASS`, the box verdict is `SEAL` (operator sees `GO`).

### Configurable Threshold Module (`RulesThresholdConfig`)
- Thresholds live in configuration (`agent/rules/config.py`), never hardcoded in logic.
- Default settings: `min_identity_confidence = 0.75`, `min_count_confidence = 0.70`, `audit_version = "v1.0.0"`.
- Values can be modified via environment variables (`PACK_RULES_MIN_IDENTITY_CONF`, `PACK_RULES_MIN_COUNT_CONF`).
- Version is saved into every record's audit metadata for reproducibility.

---

## 6. Frontend & User Experience Architecture (`agent/templates/`)

The user interface serves warehouse packing operators working on desktop stations or mobile phones.

- **Stack**: FastAPI + Jinja2 + HTMX + Tailwind CSS CDN (no Node.js build step or client-side npm dependencies).
- **Single Page Architecture**:
  1. **Hero**: Dark espresso block with light serif wordmark `PACK MANAGER`.
  2. **Check a Box**: Form accepting active tenant, order ID, unit ID, order lines, candidate SKUs, and photograph upload.
  3. **Result**: Dynamic HTMX partial swap (`#result-container`) displaying decision banner (`GO` / `STOP`), the three checks with plain-language explanations, order vs model comparison table, and photo with SVG bounding boxes.
  4. **Records**: Filterable audit log with multi-field search (verdict, failure cause, date, unit ID).
  5. **Footer**: Dark charcoal status block.
- **Fail-Open & Uncertainty Presentation**:
  - `UNCERTAIN`: Displays prominent banner: *"The agent could not verify this box. Please check the photo manually."* Operator sees `STOP`; database record preserves true `UNCERTAIN` outcome.
  - `PENDING`: Displays *"Agent unavailable: seal on your own judgment"*. Line is not stalled.
- **Design Token Palette**:
  - Backgrounds: `--cream #f7f1ec`, `--cream-soft #fbf9f7`
  - Typography: Cormorant Garamond (headings/wordmark), Inter (body)
  - Status Indicators: `--pass #4f6a4a`, `--fail #9c3a2b`, `--uncertain #8a5a00`, `--pending #5b5f66`
  - Visual Accessibility: The layout, borders, and status labels are designed for contrast across packing station lighting environments.
- **Authentication Notice (Demo Controls)**:
  - **The current website has no authentication.**
  - The organization selector dropdown (`org_id`) and the operator input field (`operator_id`) are demo controls designed to showcase database multi-tenancy and audit trail attribution without requiring login overhead.
  - In a production distribution center, tenant identity and operator credentials must be supplied via authenticated session headers (e.g. OIDC / SAML / JWT) rather than browser form controls.

---

## 7. Audit Log, Immutability & Downstream Integration

- **Evidence Record Permalinks**: Every verification produces a permanent permalink at `/pack/record/{record_id}` containing complete audit metadata (`_audit`), SVG evidence overlay, and override history.
- **Cryptographic Content Digest**: Each uploaded photograph is hashed via SHA-256 upon receipt. The 64-character hexadecimal digest is recorded in `records.content_hash`.
- **Append-Only Override History**: Operators or supervisors can submit verdict overrides. The database table `overrides` enforces immutability via trigger `trg_prevent_override_mutation`. Records of prior decisions are never modified in place.
- **Cross-Pod Foreign Key**: Downstream pods (Returns Manager and Recovery Manager) join on `unit_id` (`UNIT-0001` through `UNIT-0100`). Schema contract is formally defined in `contract/evidence-record.schema.json`.

---

## 8. Operational Boundaries and Failure Modes

1. **Hardware & Budget Constraints**: Pack Manager requires zero specialized warehouse ceiling cameras or fixed conveyors. Any phone or handheld camera capturing an open-box photograph functions as the capture device.
2. **Fail-Open Guarantee**: In the event of network disruption, Gemini API rate limits (HTTP 429), or 5xx outages, the system times out within the transport budget and emits a `PENDING` record. Outbound fulfillment lines are never held up waiting for an AI response.
3. **Occlusion Realism**: Single-shot top-down photos cannot see beneath tissue paper, dunnage, or items stacked under larger boxes. Instead of returning false positives or false negatives, the system flags occlusion as a distinct cause (`cause='occlusion'`), enabling operations managers to measure how packaging materials impact automation.

