# Pack Manager Evaluation Report: DEVELOPMENT SET EVALUATION RUN

- **Dataset:** `dev_set_15_units` (15 units)
- **Timestamp:** 2026-09-30 09:54:20 UTC
- **Model Evaluated:** `gemini-3-flash-preview`
- **Prompt Version:** `pack-prompt-v1.0`
- **Threshold Config Version:** `v1.0.0`
- **Run Type:** Iterative dev-set evaluation
- **Fixture Integrity:** ⚠️ Synthetic Fixtures (Labelled - never used for production accuracy claims)

---

## 1. Executive Summary & Operational Targets

| Metric | Target | Actual | Operational Status |
|---|---|---|---|
| **Uncertain Rate** | <= 10.0% (Kill: > 20.0%) | **6.7%** (1 / 15) | PASSED (<= 10%) |
| **Pending Rate (Fail-Open)** | <= 3.0% | **20.0%** (3 / 15) | WARNING (> 3%) |
| **Decided Accuracy** | High | **81.8%** | 11 decided cases |
| **Operational Coverage** | High | **73.3%** | Non-uncertain, completed |

> **Note on Metric Separation:** UNCERTAIN and PENDING cases are tracked as first-class operational outcomes and are counted separately. They are never conflated with correct verdicts or recorded as false positives/negatives.

---

## 2. Box-Level Decision Performance

A box verdict is either **SEAL** (Clean box approved for outbound shipping) or **STOP_AND_FIX** (Defective box flagged for repacking).

| Operational Category | Definition | Count | Rate |
|---|---|---|---|
| **True Positives (TP)** | Defective box correctly flagged (STOP_AND_FIX) | 6 | - |
| **True Negatives (TN)** | Clean box correctly approved (SEAL) | 3 | - |
| **False Negatives (FN)** | Defective box mistakenly approved (SEAL) | **0** | **0.0%** of defects |
| **False Positives (FP)** | Clean box mistakenly rejected (STOP_AND_FIX) | **2** | **40.0%** of clean |
| **Uncertain Cases** | Human operator verification required | 1 | 6.7% |
| **Pending Cases** | Fail-open on timeout or provider error | 3 | 20.0% |

> **Risk Breakdown:**
> - **Escaped Mis-ships (FN Rate):** 0.0%. A defective box approved for outbound shipping leads to customer returns or recovery disputes.
> - **False Stoppages (FP Rate):** 40.0%. A clean box stopped causes unnecessary warehouse rework.

---

## 3. Check-Level Performance (One Home Per Check)

Each physical defect is mapped orthogonally to exactly one check:
- `all_items_present`: strictly identity/presence of ordered SKUs ($count \ge 1$).
- `quantities_correct`: strictly piece count accuracy for ordered SKUs (short or surplus).
- `nothing_extra`: strictly absence of foreign objects or catalog decoys.

| Check Name | Total | Decided | Accuracy | TP | FP | FN | TN | Uncertain | Pending |
|---|---|---|---|---|---|---|---|---|---|
| **All Items Present** | 15 | 10 | **90.0%** | 3 | 1 | 0 | 6 | 2 | 3 |
| **Quantities Correct** | 15 | 10 | **100.0%** | 2 | 0 | 0 | 8 | 2 | 3 |
| **Nothing Extra** | 15 | 11 | **63.6%** | 1 | 4 | 0 | 6 | 1 | 3 |

---

## 4. Failure Mode & Uncertainty Breakdown

| Failure / Uncertainty Category | Cause Attribution | Count | % of Uncertainties |
|---|---|---|---|
| **Occlusion (Hidden Items)** | `cause='occlusion'` | 0 | 0.0% |
| **Recognition (Low Confidence / Quality)** | `cause='recognition'` | 1 | 100.0% |

---

## 5. Latency & System Timing

End-to-end model call latency per unit (transport retries and local JSON repair included):

| Metric | Latency (ms) | Target / SLA |
|---|---|---|
| **Median (p50)** | **6297.0 ms** | <= 5000 ms |
| **95th Percentile (p95)** | **13199.5 ms** | <= 10000 ms |
| **Mean** | 6114.4 ms | - |
| **Min / Max** | 0.0 ms / 14694.0 ms | - |

---

## 6. Human Labeller Agreement

Ground truth verification across independent human reviewers:

- **Raw Percentage Agreement:** 86.7%
- **Cohen's Kappa:** 0.722

---

## 7. Audit Compliance Statement

1. **Adapter Integrity:** Verified non-mock vision adapter. Mock adapters are strictly rejected during evaluation.
2. **Single Frozen Run Protocol:** The official evaluation on the 50-unit eval set is run exactly once following freeze confirmation.
3. **Zero Leaked Quantities:** Only candidate SKUs and open-box photographs are provided to the vision model. Quantities are verified strictly by deterministic code.
4. **Fail-Open Operational Safety:** Every timeout or provider exception produces a capture and PENDING record, ensuring the warehouse packaging line is never blocked.
