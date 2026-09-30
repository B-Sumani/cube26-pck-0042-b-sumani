# CLAUDE.md · Project Instructions & Constraints

This document defines durable constraints, engineering standards, and commands for the Pack Manager repository.

---

## 1. Hard Engineering Rules

1. **Forced Row-Level Security**: Every database table must have `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY`. All application queries execute as `pack_app_user` (non-superuser, no `BYPASSRLS`). Connection pooling tenant isolation requires `SET LOCAL app.current_org_id` inside an explicit transaction block.
2. **Single Call Contract**: Exactly **ONE** vision model call per unit carrying all checks. Never one call per check, and no secondary LLM calls. JSON repair is strictly local deterministic string manipulation.
3. **Fail-Open Operational Safety**: If the vision model times out or encounters an unrecoverable provider error, the pack line never blocks. The system records a `status = 'pending'`, `verdict = NULL` record and displays: *"Agent unavailable: seal on your own judgment"*.
4. **Deterministic Rules Layer**: The vision model never receives order quantities or makes gating decisions. It reports observed counts and confidences; the deterministic rules engine applies orthogonal checks and threshold gates.
5. **Metric Separation**: `UNCERTAIN` and `PENDING` outcomes are tracked as first-class operational categories. They are never counted as correct or classified as false positives/negatives.
6. **Strict Dev / Eval Separation**: Prompt iteration and threshold calibration are performed exclusively on the development set. The 50-unit evaluation set remains frozen and untouched until explicit owner authorization.

---

## 2. Forbidden Language (context.md Section 9)

Do not use or generate copy claiming:
- "tamper-proof"
- "immutable" (except when referring specifically to PostgreSQL database triggers on the `overrides` table)
- "blockchain-anchored"
- "100% accurate"
- "eliminates mis-ships"
- "works with any product"
- "no training needed" (untested)
- "seamless", "robust", "state-of-the-art", "cutting-edge", "game-changing", "revolutionary", "production-grade", "rock-solid", "enterprise-grade"
- Do not cite Amazon rules or fees from memory.

---

## 3. Repo Layout & Workspace Boundary

All code and deliverables belong exclusively under:
`submissions/b-sumani/` on branch `b-sumani`.

Never modify files outside `submissions/b-sumani/` unless explicitly instructed by the repository owner.

---

## 4. Development & Test Commands

```bash
# Run all unit and integration tests (Offline suite: 50 passing, 4 live skipped)
python -m pytest submissions/b-sumani/tests/ -v

# Run rules hardening tests
python -m pytest submissions/b-sumani/tests/test_rules_hardening.py -v

# Run model adapter tests
python -m pytest submissions/b-sumani/tests/test_model_adapter.py -v

# Run web app tests
python -m pytest submissions/b-sumani/tests/test_v0_webapp.py submissions/b-sumani/tests/test_v2_evidence_and_records.py -v

# Run evaluation harness unit tests
python -m pytest submissions/b-sumani/tests/test_eval_harness.py -v

# Run development set evaluation CLI
python submissions/b-sumani/agent/eval/run_dev_eval.py

# Run live Supabase tenancy test (Requires DATABASE_URL)
DATABASE_URL=... python -m pytest submissions/b-sumani/tests/test_tenancy_live.py -v

# Run web app locally
uvicorn submissions.b-sumani.agent.main:app --reload --port 8000
```
