# CONTEXT.md: Pack Manager agent

This file is the source of truth for scope, rules and behaviour. If a request conflicts with it, stop and ask instead of guessing.

## 0. Startup routine (do this at the start of every session and task)

1. Read every file in `context/`. This is your foundation (this file, the problem statement, the rules, the data README).
2. Read `MEMORY.md` at the repo root. This is what you have learned over time about how this owner wants things done and where the project stands.
3. Use both to shape every task. If they conflict, `context/` wins on rules and scope, `MEMORY.md` wins on the owner's preferences and current status. Flag the conflict instead of silently choosing.
4. Before finishing a task, check whether anything you learned belongs in `MEMORY.md` (section 13) and update it.

## 1. Mission

Pack Manager is step 3 of 5 in the Cube Buildathon chain (Receiving, Prep, **Pack**, Returns, Recovery).
Input: a photograph of an **open box before sealing** plus the order lines.
Output: per-check results, a verdict, and an evidence record that other agents can read.

Customer: a merchant-fulfilled or 3PL seller with **no fixed pack station and no hardware budget** (a phone camera is the whole hardware plan).
Out of scope: FBA orders (Amazon packs those). Reject `channel = fba` with a clear message.

Consumers of our record: Returns Manager (what was actually sent) and Recovery Manager (buyer disputes, empty-box and wrong-item claims).

## 2. Hard rules (non-negotiable, assessed)

1. **Tenancy first.** Every table has row-level security, enabled AND forced, scoped to `org_id`. Images are stored under unguessable keys and served only through org-checked, short-lived signed URLs. Write a test proving `org_demo_bravo` sees zero rows and cannot fetch an `org_demo_alpha` image by guessing a key. Build this before any feature.
2. **One model call per unit**, carrying all checks. Never one call per check. No second "async re-run" call unless the owner explicitly approves it.
3. **Fail open.** Model error, timeout or bad JSON: still save the capture, still write a record with `status = pending`, never block the operator. Fail-open means the operator seals on their own judgment, exactly as today. It never means auto-seal.
4. **Uncertain is a first-class verdict**, not a low-confidence PASS. It exists in the schema, the rules layer, the UI and the metrics.
5. **Look authoritative rules up.** Do not hardcode or recall channel requirements from memory. Do not treat the sample CSV flags or amounts as truth (they are dummy).
6. **Overrides are data.** When an operator disagrees, store original verdict, new verdict, reason, operator_id, timestamp. Never delete or overwrite.
7. **No secrets in the repo.** Keys come from environment variables. `.env` is gitignored. Commit `.env.example` only.
8. **Say what was built.** A SHA-256 content hash is a content hash. Do not describe the record as tamper-evident, immutable or anchored unless that is actually implemented and demonstrable.

## 3. Verdict semantics

Per-check values: `PASS`, `FAIL`, `UNCERTAIN`.
- PASS: evidence supports the condition.
- FAIL: evidence shows the condition is not met.
- UNCERTAIN: evidence is insufficient (occlusion, blur, glare, box not fully in frame).

Checks (each its own field, never blended):
- `all_items_present`: every SKU in `order_lines` is in the box (identity).
- `quantities_correct`: count per line matches (count). Expect this to be the weaker check.
- `nothing_extra`: no unexpected item or surplus quantity.

Box-level record verdict (three outcomes in the record):
- `SEAL`: all checks PASS.
- `STOP_AND_FIX`: at least one check is FAIL. FAIL takes precedence over UNCERTAIN.
- `UNCERTAIN`: no FAIL, at least one UNCERTAIN.

When model fails or times out (fail open), `status = 'pending'` and `verdict` is `NULL`. When evaluation completes normally, `status = 'completed'`.

Operator interface shows only two actions: **go** (SEAL) or **STOP** (STOP_AND_FIX or UNCERTAIN), with a visible reason. PENDING shows "Agent unavailable: seal on your own judgment". The record keeps the true three-way value.

## 4. Model call contract

One call per unit. Inputs: the photo(s), the order lines, and a **candidate set** = the order's SKUs plus the seller's other SKUs (decoys). Decoys stay in production, not just eval, so the model must discriminate rather than confirm. Do not tell the model which candidates are the "real" order items in a way that invites confirmation; give the candidate list and ask what is visible.

The model returns strict JSON (validate with a schema; retry parsing once, then fall to PENDING):

```json
{
  "observed_items": [
    {"sku": "string", "count": 0, "count_confidence": 0.0,
     "identity_confidence": 0.0, "partially_occluded": false, "bbox": [0,0,0,0]}
  ],
  "unrecognised_items": [{"description": "string", "bbox": [0,0,0,0]}],
  "image_quality": {"usable": true, "issues": ["blur","glare","box_not_in_frame","dark"]},
  "occlusion_suspected": false,
  "notes": "string"
}
```

Bounding boxes are **evidence for the record only**. The decision never depends on box accuracy.

## 5. Rules layer (deterministic code, not the model)

The model observes; plain code decides. Compare `observed_items` to `order_lines`:
- Image unusable, or a needed item is partially occluded, or count_confidence below threshold: that check is `UNCERTAIN`.
- Missing SKU or wrong count with sufficient confidence: `FAIL`.
- Thresholds live in config, not scattered in code.
- Every FAIL or UNCERTAIN carries a machine-readable `reason_code` and a human-readable `reason`.

Occlusion decision (owner may change): **single-shot capture**, with occlusion-caused UNCERTAIN/FAIL tagged `cause = occlusion`, separate from `cause = recognition`, so the eval report can split them.

## 6. Data model (Postgres, RLS on every table)

- `orgs`, `users(org_id)`
- `captures(id, org_id, unit_id, order_id, photo_keys[], captured_at, operator_id)`
- `records(id, org_id, unit_id, capture_id, order_lines, observed_in_box, checks jsonb, verdict, status, model, model_latency_ms, content_hash, created_at)` with `unit_id` as the cross-pod join key
- `overrides(id, org_id, record_id, original_verdict, new_verdict, reason, operator_id, created_at)` (append-only)
- `eval_runs`, `eval_items` for storing eval results

Record IDs use prefix `PCK-`. `unit_id` values are `UNIT-0001` to `UNIT-0100`, shared across all five repos.

## 7. Sample data

`data/pack_sample.csv` (29 rows, synthetic). Use it to design schema, structured output and record page. It has no images. It is **not** the eval set and must never be used for accuracy claims. Columns: record_id, unit_id, org_id, photo_refs, operator_id, captured_at, order_id, channel, order_lines, observed_in_box, operator_verdict. Format for lines: `SKU:qty;SKU:qty`. Note `operator_verdict` is sometimes wrong on purpose. Any inconsistency found is a finding: raise it as an Issue labelled `finding`.

## 8. Evaluation

- Eval set: 50 units the agent has never seen, **captured by the owner**, labelled independently by two humans. Report inter-labeller agreement.
- Never tune prompts on eval items. Keep a separate dev set.
- Report per check (`all_items_present`, `quantities_correct`, `nothing_extra`) separately: TP, FP, FN, TN, plus UNCERTAIN count. FP and FN reported separately, method written down.
- Report **uncertain rate** and **pending rate** as first-class metrics, with targets set before results are known.
- Report failure modes by name, splitting occlusion from recognition.
- An honest number with a breakdown beats a high number without one. Finding that the vision assumption does not hold is a valid, useful result.

Targets (OWNER TO CONFIRM BEFORE RUNNING EVAL):
- Uncertain rate target: `<= __%`. Kill condition: `> __%` makes the product unusable.
- Pending rate target: `<= 3%`.

## 9. Forbidden language

Do not write or generate copy that claims: "tamper-proof", "immutable", "blockchain-anchored", "100% accurate", "eliminates mis-ships", "works with any product", "no training needed" (untested), or any accuracy figure not backed by the eval report. Do not cite Amazon rules or fees from memory.

## 10. Repo layout

```
submissions/<github-username>/
  context/      this file plus the problem statement, RULES.md and data/README.md (read at startup)
  MEMORY.md     what the build agent has learned; kept current in place (section 13)
  README.md  ARCHITECTURE.md  CLAUDE.md  build-brief.md  build-log.md  eval-report.md
  01-customer-letter.md  02-prfaq.md  03-one-pager.md
  contract/     evidence-record schema (align with other pods)
  agent/        headless-first code, then UI
  tests/        tenancy test, fail-open test, rules-layer tests
```

## 11. Build order (iterative)
Build a thin end-to-end version first, then improve it in versions. One version
at a time. After each version: run all tests, append to build-log.md what
changed and why, update MEMORY.md in place, then stop and wait for the owner's
'continue'.
- v0: working web app, photo in, verdict out (upload, one model call, basic
  rules, result page). Tenancy, private storage and fail-open included from the
  start.
- v1: rules hardening (one home per check, confidence gates FAIL, reason_code,
  reason and cause on every FAIL/UNCERTAIN, edge-case tests).
- v2: evidence record page, override flow, history.
- v3: eval harness and report. Dev-set run first, then a single frozen run on
  the eval set.
- v4: UX polish, README, ARCHITECTURE.md, contract/, demo, deploy.
Steps 1, 1b and 2 (schema/RLS/tenancy, adapter) are done.

## 12. Definition of done

Tenancy test passes. Fail-open test passes. Every record shows per-check results, verdict, reason and model latency. Uncertain and pending appear in UI and metrics. Overrides are stored. Eval report has per-check FP/FN. No secrets committed. Docs claim only what exists.

## 13. Memory system (MEMORY.md)

`MEMORY.md` is the build agent's working memory across sessions. It is for you, the coding agent. It is **not** runtime memory for Pack Manager: verdicts, checks and thresholds must never depend on anything in `MEMORY.md`. They come from code, config and the model output only.

When the owner corrects you, or you learn something new, update the relevant section of `MEMORY.md` before ending the task. Sections:

- **Voice**: tone and phrasing for docs, the PR/FAQ, customer letter and UI copy; writing corrections; forbidden-language hits the owner has flagged (see section 9).
- **Process**: how the owner wants tasks done: one build step at a time, plan before code, tests before moving on, wait for "continue".
- **People**: the owner, the second labeller, organisers, the pod contacts for the cross-pod contract, and who agreed what.
- **Projects**: current build step (1 to 7), what is done, what is blocked, open findings raised as Issues, days left to the 1 Oct 6:00 PM IST deadline.
- **Decisions**: settled choices with the reason: uncertain-rate target and kill threshold, occlusion approach, decoys in production, model provider, thresholds. Mark each `LOCKED` or `OPEN`.
- **Eval**: dev vs eval set status, labelling progress and agreement, named failure modes seen so far, per-check numbers once measured.
- **Output**: file names, formats, folder locations, commit message style, how deliverables are presented.
- **Tools**: stack and how to run it (commands, test runner, env var names, never values), which tools to use for what.

Rules for keeping it current:

1. **Update in place.** When something changes, replace the outdated line. Do not append below it. The file must always reflect the latest state.
2. Keep it short and scannable, one line per fact, dated only where the date matters.
3. **Never store secrets**: no API keys, tokens, passwords or `.env` contents. Names of env vars only.
4. **Never store eval labels, ground truth or accuracy claims** that could leak into tuning. Record only process facts (for example "eval set 32 of 50 captured").
5. Do not silently discard an owner correction. If it contradicts `context/`, record it and flag the conflict to the owner.
6. `MEMORY.md` is not `build-log.md`. The build log is a chronological record that organisers read, and it is append-only. `MEMORY.md` is a current-state snapshot.
7. Only state what you actually know. If unsure, mark it `UNVERIFIED` rather than guessing.

## 14. Website scope and frontend design

Single-page site. One route serves one page with these sections, linked from a
small top nav using anchors:
1. Hero: dark espresso block with a large light serif wordmark "PACK MANAGER" and
   one short line on what it does. No photographs.
2. Check a box: order lines, seller catalogue, ONE photo upload.
3. Result: decision, three checks, evidence, photo (HTMX swaps this in, no reload).
4. Records: filters and detail view of the audit log.
5. Footer: dark charcoal block.

### Design tokens and styling
- Palette (CSS variables block, extended into Tailwind CDN config):
  `--cream #f7f1ec`, `--cream-soft #fbf9f7`, `--stone #bdbab4`, `--stone-light #e1dcd5`,
  `--taupe #8a7967`, `--walnut #684432`, `--umber #64503d`, `--espresso #382d22`,
  `--charcoal #1c1c1c`.
  Status tokens: `--pass #4f6a4a`, `--fail #9c3a2b`, `--uncertain #8a5a00`, `--pending #5b5f66`.
- Typography (Google Fonts): Cormorant Garamond for headings and the wordmark,
  Inter for body. Small uppercase labels with wide letter-spacing.
- Style: generous whitespace, thin borders, soft cream cards, restrained motion
  (fade/slide on result). Layout is original: take only colours and fonts from
  the reference, and do not copy any images or text.
- Mobile-friendly (operators use phones).
- No keys in the browser, no external assets except Google Fonts and Tailwind CDN.

### Decision and Evidence View (v0a shows basics, v2 full history)
- Result page shows the decision (go / STOP / "needs human check"), the three
  checks each PASS/FAIL/UNCERTAIN with a plain-language reason, what the order
  expects vs what the model saw (per SKU count, labelled "model-reported
  confidence"), and the uploaded photo next to it. Bounding boxes are drawn on
  the photo as evidence only.
- Every status shows a text label as well as a colour, and passes contrast.
- When the record is UNCERTAIN (blurry, glare, box cut off, item occluded, low
  confidence), the page says clearly: "The agent could not verify this box.
  Please check the photo manually.", shows the specific reason, and shows the
  photo prominently. Operator sees STOP; the record keeps the true UNCERTAIN value.
- PENDING shows "Agent unavailable: seal on your own judgment".
- The "MOCK RESULT, not a real check" banner stays visible while on the mock
  adapter.
- UNCERTAIN must come only from evidence, never forced or quota-based. A clear
  photo must still get PASS or FAIL. Add tests for both directions.
- Images are served only through org-scoped signed URLs. Upload validation:
  JPEG/PNG only, size limit, no path tricks. Keys never reach the browser.
- An override button stores original verdict, new verdict and reason.

### Audit Log (append-only, no secrets)
For every record save: record_id, unit_id, org_id, UTC timestamp, model name and
version, prompt version, threshold-config version, per-check result with
reason_code, reason and cause (occlusion|recognition), the parsed observations
(counts and confidences), image-quality issues, latency in ms, status
(completed|pending), and every override. Add a Records page listing these
with filters (verdict, cause, date). Never log keys or raw auth headers.

### Eval Report (v3, DEV set first)
Build the harness to report on the eval set, but do NOT run it on the 50 eval
cases until I say the prompt and thresholds are frozen. Metrics, per check and
per box: accuracy on decided cases, coverage, FN (bad box got SEAL), FP (good box
got STOP_AND_FIX) as raw counts and rates, uncertain rate split by cause,
pending rate, latency p50/p95, model name, and labeller agreement. UNCERTAIN and
PENDING are counted separately, never as correct or as FP/FN. The frozen eval
runs once, and the report states this.

## 15. Iteration and change control

- Improvements are driven by the DEV set only. The eval set is never viewed,
  tuned on or run until the owner says the prompt and thresholds are frozen.
- Change one thing per iteration. Record before/after dev-set results and keep a
  list of named failure modes.
- Never generate fake photos or fake accuracy numbers.
- The agent may edit context.md only when the owner asks, and must show the diff.
- The agent must never edit, weaken or remove Section 2 (Hard rules), Section 9
  (Forbidden language) or the targets in Section 8 without explicit owner
  approval in that message.

