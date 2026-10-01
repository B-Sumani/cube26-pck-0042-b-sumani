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
- Current step: Step 16 complete (Blind Dev Set Verification & Audit Trail Evidence Seeding). Dev set verified without answers. 18 verified records and evidence photographs populated in audit log. 69 tests passing offline, 5 live skipped. Working tree uncommitted awaiting owner instruction. The 50-unit eval set remains strictly frozen and sealed.
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
    - Executed 2 consecutive runs on 18 dev boxes with temperature=0.0: 0 of 18 verdicts changed (0.0% run-to-run variance), 0 per-SKU count changes.
    - Updated per-check table to cover all 18 boxes (Decided 17 + Uncertain 1 = 18).
    - Documented UNIT-0069 as "right verdict, wrong reason" and breakdown of the 7 physically clean boxes (5 sealed, 1 false stop, 1 manual check).
  - Step 11 / Part 3 Live Web E2E: Started uvicorn server on `http://127.0.0.1:8000` with live Gemini vision adapter (`gemini-3.1-flash-lite-preview`). Playwright tests verified: UNIT-0017 (correct -> SEAL), UNIT-0029 (wrong -> STOP_AND_FIX), UNIT-0049 (blurry -> UNCERTAIN with human inspection banner), operator override flow (`OVR-B18B74B4` from UNCERTAIN to SEAL), simulated timeout fail-open (`PENDING`), upload validations (non-image, oversize, path traversal rejected), and mobile responsive navbar fix. UI cleaned up: hero subtitle/tagline removed (strictly PACK MANAGER), override history stripped from record_detail.html, stage badge and RLS label removed from footers.
  - Step 12 / Form Polish & Tenancy Hardening: Removed "Station 03" badge from open box form; cleared prefilled data from order_lines and candidate_skus textareas with light guidance text; added dynamic onchange tenant switching; enforced strict tenant key requirements in storage signing/verification; enforced record ownership in override submission; expanded tenancy test suite (53 tests passing).
  - Step 13 / Demo Org Login & Seller Product Catalogue Integration:
    - Part A: Standalone `/login` page with "Enter as Alpha Demo Merchant" and "Enter as Bravo Demo Merchant" buttons, setting signed, HttpOnly, SameSite=Lax `pack_session` cookie; application startup requires `SESSION_SECRET`; nav displays "Signed in as <org name> (<org_id>)" and "Switch organisation"; tenant identity determined exclusively via session; non-session requests redirect to `/login` or 401.
    - Part B: `catalogue_items` table under forced RLS seeded per org; removed catalogue textarea; added expandable "Using your catalogue: 10 products" summary; interactive product picker with dropdown + quantity stepper (`[-] [ qty ] [+]`, min 1) serializing to `SKU:qty;SKU:qty` (quantities never sent to model); dedicated `#catalogue` section with view/add/edit/delete and CSV upload; empty catalogue fallback shows explicit warning banner and sets `candidate_source = 'order_only'` in audit metadata.
    - Expanded test suite: 58 passed offline, 5 skipped (live). Captured screenshots: `15_login_page.png`, `02_check_a_box_form.png`, `16_catalogue_section.png`, `04_result_unit0017_correct.png`, `05_result_unit0029_wrong.png`, `06_result_unit0049_blurry.png`, `14_tenancy_bravo_isolated.png`.
  - Step 14 / Confidence Display Diagnosis & Precision Fix:
    - Diagnosed dev run confidences: 100% of values are 1.00 (min 1.00, median 1.00, max 1.00 across all 50 observed items in all 18 dev boxes).
    - Identified dual root cause: (a) display template bug multiplying by 100 and formatting as `%.0f%%` (rounding to 100%), and (b) model genuinely returning 1.0 everywhere.
    - Updated `result_partial.html` and `record_detail.html` to display raw stored value with two decimals (`0.93 count · 0.93 id`), labelled column header `"Model-Reported Confidence (Not Calibrated)"`.
    - Added test in `test_v2_evidence_and_records.py` verifying stored `0.93` is rendered as `0.93` and never rounded to `100%`.
    - Documented uncalibrated confidence and inactive threshold status in `README.md` and `eval-report.md`.
    - Captured updated screenshot `17_result_corrected_confidence.png` / `04_result_unit0017_correct.png`.
- Blocked: awaiting owner "continue" to proceed to Part 4: Deployment readiness. The 50-unit eval set remains strictly frozen and sealed.
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
  - Main Table (15 clear boxes): TP=10/10, TN=5/5, FP=0/5 clean (0/15 clear, 95% CI: [0.0%, 43.4%]), FN=0/10 defective (95% CI: [0.0%, 27.8%]). Accuracy: 15/15 (100.0%, 95% CI: [79.6%, 100.0%]) with coverage 15/15 (100.0%). (Pre-temp=0: 14/15, FP=1).
  - Hard Table (3 boxes): UNCERTAIN Recall: 1 of 3 (33.3%, UNIT-0049 caught as UNCERTAIN; UNIT-0043 false stop and UNIT-0081 safe stop halted as STOP_AND_FIX missing defects; kept strictly out of main FP/FN).
  - Per-Check Results (all 3 checks total to 18): `all_items_present` (TP=6, FP=2, FN=0, TN=9, UNC=1, PEN=0), `quantities_correct` (TP=3, FP=0, FN=0, TN=14, UNC=1, PEN=0), `nothing_extra` (TP=4, FP=1, FN=0, TN=12, UNC=1, PEN=0).
  - Run-to-Run Variance (Run 1 vs Run 2 at temp=0.0): 0/18 verdicts changed (0.0%), 0 count changes.
- Eval set: 50-unit frozen evaluation strictly sealed until owner confirms freeze.
- Named failure modes from real dev run:
  1. The model never reports occlusion: `occluded_hidden` (UNIT-0043) and `occluded_absent` (UNIT-0081) are not detected; UNIT-0043 causes a false stop, UNIT-0081 causes a safe stop as missing item.
  2. Counting 3 identical items is unstable: UNIT-0021 counted 2 soaps under default temperature (false stop) and 3 soaps under temp=0.0 (SEAL).
  3. The blur gate depends on the model reporting blur: UNIT-0049 is a directional result from one box, not a fix; relies on model outputting "blur" in issues list.
  4. Uncalibrated Model Confidence: Model returns 1.00 count and identity confidence across all items; thresholds remain inactive.

## Output
- Files live under submissions/b-sumani/ per context.md section 10.
- Record IDs use prefix PCK-. unit_id format UNIT-XXXX.
- Required deliverables: README.md, ARCHITECTURE.md, eval report, demo video, deployment URL if applicable, LinkedIn post URL.

## Tools & Commands
- Backend: Python (FastAPI). Postgres with forced row-level security.
- Secrets via env vars only. Commit .env.example, never .env.
- Run and test commands:
  - All unit/integration tests: `python -m pytest submissions/b-sumani/tests/ -v` (68 passed offline, 5 live skipped)
  - Live tenancy test (requires DATABASE_URL): `DATABASE_URL=... python -m pytest submissions/b-sumani/tests/test_tenancy_live.py -v`
  - Run app locally: `uvicorn submissions.b-sumani.agent.main:app --reload --port 8000`
  - Dev eval benchmark run: `python submissions/b-sumani/agent/eval/run_eval.py --dev --images-dir images`
  - Official Sealed Eval Set Run command:
    `python submissions/b-sumani/agent/eval/run_eval.py --images-dir <IMAGES_DIR> --eval-dir <EVAL_DIR> [--labels-b <LABELS_B>]`
