# MEMORY.md

Current-state notes for the build agent. Update in place. Replace outdated lines, never append below them. No secrets, no eval labels. Rules are in context/context.md section 13.

## Voice
- Plain, honest, operations-minded tone. Say what was built, not what it sounds like.
- Avoid the forbidden language in context.md section 9.
- (Add owner corrections here.)

## Process
- One build step at a time, in the order in context.md section 11.
- Show a short plan before writing code. Run tests. Update build-log.md. Wait for "continue".
- Tenancy test must be green before any feature work.
- Iterative build v0-v4; dev set only until owner freezes; context.md edits only when the owner asks.

## People
- Owner: Sumani, GitHub: b-sumani
- Second labeller: not confirmed yet
- Pod contacts for the contract: not needed yet

## Projects
- Deadline: 1 Oct 2026, 6:00 PM IST. No resubmission. Commits only during the build phase.
- Current step: Phase 1 Real Dev Run complete (18 real boxes evaluated under live Gemini Vision `gemini-3.1-flash-lite-preview`). Awaiting owner "continue" before Phase 2 (Bounded tuning on dev set only).
- Done:
  - Step 1 & 1b: DB schema with forced RLS on all 7 tables, non-bypass app role `pack_app_user`, append-only overrides, connection pooling isolation with `SET LOCAL app.current_org_id`, unguessable storage keys with HMAC-SHA256 signed URLs. Tenancy logic tested offline (6/6 tests passing); live suite ready.
  - Step 2: Model adapter with tightened schema, non-candidate demotion to unrecognised items, local string repair (no second LLM call), transport retries inside timeout budget, live smoke test verified on `gemini-3-flash-preview` (latency: 4466ms). Eval harness mock-adapter guard.
  - Step 3 / v0: Working web app (FastAPI + Jinja2 + Tailwind CDN + HTMX). Single page with 5 sections (Hero, Check a box, Result, Records, Footer). Photo upload + order lines verification returning GO/STOP, 3 checks with reason and reason_code, SEAL/STOP_AND_FIX/UNCERTAIN verdict, fail-open PENDING on timeout/provider error, prominent UNCERTAIN human check banner, append-only operator overrides, org-scoped signed URL image serving.
  - Step 4 / v1: Rules hardening. One home per check (orthogonal failure partitioning). Confidence gates FAIL & PASS (low confidence or occlusion gates to UNCERTAIN). Machine-readable `reason_code`, human `reason`, and failure `cause` (`occlusion` | `recognition`) on every check. Configurable threshold module `RulesThresholdConfig` with env loading and versioning. 15 unit tests covering edge cases, box precedence, and both-direction evidence tests.
  - Step 5 / v2: Evidence record detail page (`/pack/record/{record_id}`) for downstream pods with complete audit metadata (`_audit`), order vs observation comparison table, signed URL photo with SVG bounding boxes, and append-only override history via database trigger. Records section upgraded with instant HTMX multi-field filtering (verdict, cause, date, unit_id). Append-only override history accumulation verified. 5 integration tests.
  - Step 6 / v3: Eval harness and report on dev set. Strict non-mock adapter guard. Metric separation (UNCERTAIN and PENDING isolated from FP/FN).
  - Step 7 / v4: UX polish (loading state feedback, restrained entry animations, responsive layout), cross-pod contract artifacts (`contract/evidence-record.schema.json` and `contract/README.md`), full documentation suite, deployment blueprints, and 3-minute video walkthrough script.
  - Step 8 / Honesty Audit: Removed unverified claims, tagged operational assumptions, reframed customer letter & PR/FAQ as hypothetical working-backwards planning exercises, reset eval-report.md to method and empty tables, added sliding-window rate limiting & 10MB upload cap to main.py, verified zero secrets in repo and git history.
  - Step 9 / Phase 1 Real Dev Run: Populated `catalogue.csv` with confirmed titles and visual descriptions for 10 SKUs, executed 18 real boxes from `IMAGES_DIR` under respective `org_id`s with 7s pacing. 0.0% PENDING (0 units), 100% accuracy on decided cases (15/15), 0% FP, 0% FN, p50 latency 5045.5ms, p95 11180.6ms.
- Blocked: awaiting owner "continue" to proceed to Phase 2 (Bounded tuning on dev set only). The 50-unit eval set remains strictly frozen and sealed.
- Open findings (Issues labelled `finding`):
  - Finding A resolved: schema uses verdict = SEAL | STOP_AND_FIX | UNCERTAIN, status = completed | pending. When pending, verdict is NULL.
- Possible finding to raise: rule 2 (one model call per unit) vs design review's async re-run

## Decisions
- Uncertain-rate target: <= 10%, kill condition > 20%
- Pending-rate target: <= 3%
- Occlusion approach: single-shot, occlusion tagged separately
- Decoys in production and eval: YES, seller's other SKUs always in the candidate set; model never gets order quantities
- Async re-run: NOT built
- Model provider: Gemini (`gemini-3.1-flash-lite-preview` for dev run, `gemini-3.1-pro-preview` for frozen eval)
- Database: Supabase/PostgreSQL with forced RLS
- Frontend: FastAPI + Jinja2 + Tailwind CDN + HTMX single-page site
- Bounding boxes: evidence only, never used in the decision

## Eval
- Dev set: 18 real warehouse boxes evaluated with `gemini-3.1-flash-lite-preview` (raw data at `eval/real_dev_results.json`)
- Eval set: 50-unit frozen evaluation strictly sealed until owner confirms freeze
- Named failure modes from real dev run:
  - Occlusion Tagging Boundary: For `occluded_hidden` (UNIT-0043) and `occluded_absent` (UNIT-0081), model did not mark `occlusion_suspected=True`; missing items were caught as `MISSING_ITEMS` -> `STOP_AND_FIX` instead of routing to `UNCERTAIN (cause=occlusion)`.
  - Blur Image Quality Gate: For `bad_photo` (UNIT-0049), model noted `issues: ['blur']` but kept `usable: True` and high confidence, allowing `SEAL` instead of `UNCERTAIN (cause=recognition)`.

## Output
- Files live under submissions/b-sumani/ per context.md section 10.
- Record IDs use prefix PCK-. unit_id format UNIT-XXXX.
- Required deliverables: README.md, ARCHITECTURE.md, eval report, demo video, deployment URL if applicable, LinkedIn post URL.

## Tools
- Backend: Python (FastAPI). Postgres with forced row-level security.
- Secrets via env vars only. Commit .env.example, never .env.
- Run and test commands:
  - All unit/integration tests: `python -m pytest submissions/b-sumani/tests/ -v`
  - Live tenancy test (requires DATABASE_URL): `DATABASE_URL=... python -m pytest submissions/b-sumani/tests/test_tenancy_live.py -v`
  - Run app locally: `uvicorn submissions.b-sumani.agent.main:app --reload --port 8000`
