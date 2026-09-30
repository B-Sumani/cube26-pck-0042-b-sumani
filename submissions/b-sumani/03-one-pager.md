# Pack Manager · Executive One-Pager

**Product:** Pack Manager (Stage 3 of 5 in Commerce Context Pipeline)  
**Author:** Sumani (`b-sumani`)  
**Target Market:** Merchant-fulfilled e-commerce sellers and mid-market 3PL fulfillment centers  
**Hardware Requirement:** Zero specialized hardware; standard mobile phone or benchtop camera  

---

## 1. Operational Problem Statement
In outbound fulfillment, items picked from warehouse shelves are placed into shipping cartons, taped shut, and handed to carriers. When a packing error occurs—omitted items, incorrect piece counts, or swapped SKUs—the mis-ship results in customer dissatisfaction, replacement shipping, and restocking costs *(ASSUMPTION, unverified cost impact)*.

Manual supervisor inspection of every carton slows packing bench throughput *(ASSUMPTION, unverified)*, while automated conveyor scanning tunnels require capital investments unavailable to flexible packing benches *(ASSUMPTION, unverified)*. Crucially, when buyers subsequently file "empty box" or "missing item" claims, merchant sellers lack visual proof of carton contents at seal time to defend against chargebacks *(ASSUMPTION, unverified dispute impact)*.

---

## 2. Solution: Single-Shot Vision Verification
Pack Manager introduces an automated check at the packing bench immediately prior to carton sealing:
- **One Overhead Photo**: The packer captures a single top-down photograph of the open carton.
- **Single Model Call**: A vision model evaluates the carton against expected order lines and candidate catalog SKUs (including decoys). Quantities are never sent to the model.
- **Three Orthogonal Checks**:
  1. `all_items_present`: strictly identity and presence of ordered items.
  2. `quantities_correct`: strictly piece count accuracy for present items.
  3. `nothing_extra`: strictly absence of foreign objects or catalog decoys.
- **Operator Decision Signals**:
  - `GO · SEAL`: Order matches. Packer tapes the carton.
  - `STOP · STOP_AND_FIX`: Discrepancy detected with plain-language defect reason.
  - `STOP · UNCERTAIN`: Occlusion or glare detected. Prominently instructs: *"The agent could not verify this box. Please check the photo manually."*
  - `PENDING`: Model timeout or network failure. Prominently displays: *"Agent unavailable: seal on your own judgment"*. The packing line is never blocked.
- **Permanent Evidence Record**: Every verification creates a record keyed by `unit_id` (`UNIT-0001` to `UNIT-0100`) containing a SHA-256 photo hash, enabling downstream Returns (Stage 4) and Recovery (Stage 5) to substantiate claims.

---

## 3. Operational Scorecard & Target Thresholds

_Note: Operational targets and kill conditions are defined below. Official measured outcomes await the single frozen evaluation run on the 50-unit evaluation set._

| Metric | Target | Kill Condition | Measured Result | Operational Status |
|---|---|---|---|---|
| **Uncertain Rate** | $\le 10.0\%$ | $> 20.0\%$ (Disrupts line flow) | — | [Pending frozen run] |
| **Pending Rate (Fail-Open)** | $\le 3.0\%$ | $> 10.0\%$ (Excessive offline) | — | [Pending frozen run] |
| **Decided Accuracy** | High | $< 70.0\%$ | — | [Pending frozen run] |
| **Operational Coverage** | High | $< 65.0\%$ | — | [Pending frozen run] |
| **Escaped Mis-ships (FN Rate)** | $0.0\%$ | $> 2.0\%$ (Escaped errors) | — | [Pending frozen run] |
| **False Stoppage Rate (FP Rate)** | Low | $> 25.0\%$ | — | [Pending frozen run] |
| **Median Latency (p50)** | $\le 5000\text{ ms}$ | $> 10000\text{ ms}$ | — | [Pending frozen run] |
| **Labeller Agreement (Kappa)** | $\ge 0.60$ | $< 0.40$ (Ambiguous data) | — | [Pending frozen run] |

---

## 4. Architectural Non-Negotiables
1. **Multi-Tenant Forced RLS**: All tables enforce Postgres RLS under non-bypass user `pack_app_user`. Tenant context is passed via `SET LOCAL app.current_org_id` inside explicit transactions.
2. **One Call Per Unit**: Exactly one model call per unit carrying all checks. Local deterministic regex string repair for JSON; no secondary LLM calls.
3. **Fail-Open Operational Safety**: If model times out or encounters 5xx errors, carton is marked `PENDING` with `verdict = NULL`; warehouse operations never stall.
4. **Append-Only Override History**: Operator adjustments are recorded immutably via database trigger `trg_prevent_override_mutation`.
5. **Frozen Eval Set Boundary**: Evaluation set of 50 units remains completely frozen and untouched until explicit owner freeze confirmation.
