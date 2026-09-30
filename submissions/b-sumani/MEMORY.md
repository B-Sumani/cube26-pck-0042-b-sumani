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
- Current step: 0 (nothing built yet)
- Done: none
- Blocked: no dataset provided, owner captures own photos (dev set ~15, eval set 50)
- Open findings (Issues labelled `finding`): none yet
- Possible finding to raise: rule 2 (one model call per unit) vs design review's async re-run

## Decisions
- Uncertain-rate target and kill threshold: OPEN (must be set before eval results)
- Pending-rate target: <= 3% (OPEN, confirm)
- Occlusion approach: single-shot, occlusion tagged separately (OPEN, confirm)
- Decoys in production: YES, seller's other SKUs always in the candidate set (OPEN, confirm)
- Async re-run: NOT built unless owner approves
- Model provider: OPEN (kept behind a swappable adapter)
- Bounding boxes: evidence only, never used in the decision

## Eval
- Dev set: 0 of ~15 captured
- Eval set: 0 of 50 captured; two independent labellers required
- Named failure modes so far: none

## Output
- Files live under submissions/<github-username>/ per context.md section 10.
- Record IDs use prefix PCK-. unit_id format UNIT-XXXX.
- Required deliverables: README.md, ARCHITECTURE.md, eval report, demo video, deployment URL if applicable, LinkedIn post URL.

## Tools
- Backend: Python (FastAPI). Postgres with forced row-level security.
- Secrets via env vars only. Commit .env.example, never .env.
- Run and test commands: <fill in once the project is scaffolded>
