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
- Current step: Phase 2 Bounded Tuning complete on dev set. Awaiting owner "continue" to proceed to Phase 3: Finish the product.
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
  - Step 10 / Phase 2 Bounded Tuning & Part 2 Variance:
    - Iteration B adopted (rules ambiguity gate: blur/glare/box_not_in_frame or occlusion_suspected routes missing FAIL / any PASS to UNCERTAIN).
    - Temperature set to 0.0 in generationConfig (generic change, documented).
    - Executed 2 consecutive runs on 18 dev boxes with temperature=0.0:
      - 0 of 18 verdicts changed (0.0% run-to-run variance).
      - 0 per-SKU count changes across all 18 boxes.
- Blocked: awaiting owner "continue" to proceed to Part 3: Website end to end with real model. The 50-unit eval set remains strictly frozen and sealed.
- Open findings (Issues labelled `finding`):
  - Finding A resolved: schema uses verdict = SEAL | STOP_AND_FIX | UNCERTAIN, status = completed | pending. When pending, verdict is NULL.
- Possible finding to raise: rule 2 (one model call per unit) vs design review's async re-run

## Decisions
- Uncertain-rate target: <= 10%, kill condition > 20%
- Pending-rate target: <= 3%
- Occlusion approach: single-shot, occlusion tagged separately
- Decoys in production and eval: YES, seller's other SKUs always in the candidate set; model never gets order quantities
- Async re-run: NOT built
- Model provider: Gemini (`gemini-3.1-flash-lite-preview` for both dev tuning and evaluation - single unified preview model; run date: 2026-10-01)
- Generation config: temperature = 0.0
- Database: Supabase/PostgreSQL with forced RLS
- Frontend: FastAPI + Jinja2 + Tailwind CDN + HTMX single-page site
- Bounding boxes: evidence only, never used in the decision

## Eval
- Dev set: 18 real warehouse boxes evaluated with `gemini-3.1-flash-lite-preview` (preview model; run date: 2026-10-01).
  - Headline Raw Counts:
    - Bad boxes sealed: 0 of 10 (FN = 0)
    - Good boxes stopped: 0 of 15 in final run (1 of 15 in pre-temp=0 run on UNIT-0021)
    - UNCERTAIN recall on hard boxes: 1 of 3 (UNIT-0049 caught; UNIT-0043 and UNIT-0081 halted as missing defects)
    - Operational Coverage: 18 of 18 (100.0% coverage; 17 decided, 1 UNCERTAIN, 0 PENDING)
    - Uncertain rate: 1 of 18 (5.6%)
    - Pending rate: 0 of 18 (0.0%)
  - Main Table (15 clear boxes): TP=10/10, TN=5/5, FP=0/15, FN=0/10. Accuracy: 15/15 (100.0%) with coverage 15/15 (100.0%). (Pre-temp=0: 14/15, FP=1).
  - Hard Table (3 boxes): UNCERTAIN Recall: 1 of 3 (UNIT-0049 caught as UNCERTAIN; UNIT-0043 and UNIT-0081 halted as STOP_AND_FIX missing defects).
  - Per-Check Results: `all_items_present` (FP=1, FN=0), `quantities_correct` (FP=0, FN=0), `nothing_extra` (FP=1, FN=0).
  - Run-to-Run Variance (Run 1 vs Run 2 at temp=0.0): 0/18 verdicts changed (0.0%), 0 count changes.
- Eval set: 50-unit frozen evaluation strictly sealed until owner confirms freeze.
- Named failure modes from real dev run:
  1. The model never reports occlusion: `occluded_hidden` (UNIT-0043) and `occluded_absent` (UNIT-0081) are not detected; UNIT-0043 causes a false stop, UNIT-0081 causes a safe stop as missing item.
  2. Counting 3 identical items is unstable: UNIT-0021 counted 2 soaps under default temperature (false stop) and 3 soaps under temp=0.0 (SEAL).
  3. The blur gate depends on the model reporting blur: UNIT-0049 is a directional result from one box, not a fix; relies on model outputting "blur" in issues list.

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
