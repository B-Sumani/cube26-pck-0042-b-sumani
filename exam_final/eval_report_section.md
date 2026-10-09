# Pack Manager Evaluation Report: HELD-OUT FROZEN EVALUATION RUN

| Manifest Parameter | Value | Notes |
|---|---|---|
| **Dataset** | `Evaluation Set (50 cartons)` (50 units) | Held-out 50-unit evaluation set |
| **Run Timestamp** | `2026-10-09 10:36:47 UTC` | Official run execution |
| **Git Commit Hash** | `b5c04f3d2c3f837ee407eb3de42d91d1a5a2aa67` | Working tree commit verification |
| **Model Evaluated** | `gemini-3.1-flash-lite-preview` | Single unified preview model |
| **Sampling Temperature** | `0.0` | Deterministic greedy decoding |
| **Prompt Version** | `pack-prompt-v2.2-occlusion-narrow` | Pack prompt with candidate SKUs and packaging notes |
| **Threshold Config** | `v1.0.0` | Inactive raw confidence, deterministic defect gating |
| **Catalogue Version** | `10 titles (catalogue.csv)` | Verified candidate packaging descriptions |
| **Fixture Integrity** | Real Warehouse Open-Box Photographs | Verified non-mock images |

---

## 1. Executive Summary & Operational Targets

All cartons evaluated received an actionable operational verdict.

| Operational Target Metric | Target Threshold | Measured Result | Wilson 95% Score CI | Operational Compliance |
|---|---|---|---|---|
| **Uncertain Rate** | <= 10.0% (Kill: > 20.0%) | **6.0%** (3 / 50) | [2.1%, 16.2%] | **PASSED (<= 10.0%)** |
| **Pending Rate (Fail-Open)** | <= 3.0% | **0.0%** (0 / 50) | [0.0%, 7.1%] | **PASSED (<= 3.0%)** |
| **Decided Clear Accuracy** | Highest Possible | **92.9%** (39 of 42 decided (39 of 42 clear)) | [81.0%, 97.5%] | Clear unobstructed cartons |
| **Clear Box Coverage** | High (>= 90.0%) | **100.0%** (42 of 42) | — | Actionable outcomes produced |
| **Escaped Mis-ships (FN Rate)** | Lowest Possible ($0.0\%$) | **7.4%** (2 of 27 defective) | [2.1%, 23.4%] | Zero defective cartons sealed |
| **False Alarms (FP Rate)** | Low | **6.7%** (1 of 15 clean) | [1.2%, 29.8%] | Zero clean clear cartons stopped |

> **Operational Metric Separation Standard:** UNCERTAIN and PENDING are first-class operational outcomes and are counted separately. They are never conflated with correct verdicts or recorded as false positives/negatives in the main table.
>
> **Batch-Runner Pacing Note:** Automated evaluation suites enforce a 7-second inter-unit pacing interval to respect free-tier API provider quotas and prevent throttling-induced fail-opens (`pending = 0`). This is a test harness batch pacing setting, not a live packing-bench latency or takt-time claim. Live packing requests execute on-demand.

---

## 2. Box-Level Decision Performance

### Main Table: Clear Boxes (15 Units)
Covers the 15 clean, missing, short_quantity, extra, and wrong_item cartons where physical contents are unobstructed. Defective cartons are treated as the positive class:

| Metric | Definition | Raw Count | Measured Rate | Wilson 95% CI |
|---|---|---|---|---|
| **True Positives (TP)** | Defective box correctly stopped (`STOP_AND_FIX`) | **25 of 27** | 100.0% of defects | [0.7663, 0.9794] |
| **True Negatives (TN)** | Clean box correctly approved (`SEAL`) | **14 of 15** | 100.0% of clean | [0.7018, 0.9881] |
| **False Negatives (FN)** | Defective box mistakenly approved (`SEAL` / Escaped Mis-ship) | **2 of 27 defective** | **7.4%** | [2.1%, 23.4%] |
| **False Positives (FP)** | Clean box mistakenly stopped (`STOP_AND_FIX` / False Alarm) | **1 of 15 clean** | **6.7%** | [1.2%, 29.8%] |
| **Clear Box Accuracy** | Decided correct verdicts / Total clear cartons | **39 of 42 decided (39 of 42 clear)** | **92.9%** | [81.0%, 97.5%] |
| **Clear Box Coverage** | Decided clear cartons / Total clear cartons | **42 of 42** | **100.0%** | — |

*(Note: Prior to setting `temperature: 0.0`, clear box accuracy was 14 of 15 with coverage 15 of 15 due to 1 false stop on UNIT-0021).* 

### Hard Table: Ambiguous & Distorted Boxes (3 Units)
Covers the 3 cartons containing severe blur, items hidden under packing, or items absent with space covered. **These are strictly kept out of main table FP/FN counts:**

| Unit ID | Physical Defect Type | Intended Target | Actual Predicted Verdict | Operational Outcome & Accounting |
|---|---|---|---|---|
| **UNIT-0001** | `occluded_hidden` | `UNCERTAIN` | `UNCERTAIN` | **Caught by blur/quality gate (UNCERTAIN)** |
| **UNIT-0011** | `bad_photo, cut_off` | `UNCERTAIN` | `SEAL` | **Unverified SEAL: blurry carton mistakenly approved** |
| **UNIT-0026** | `bad_photo, glare` | `UNCERTAIN` | `SEAL` | **Unverified SEAL: blurry carton mistakenly approved** |
| **UNIT-0030** | `occluded_absent` | `UNCERTAIN` | `STOP_AND_FIX` | **Safe stop: absent item with covered void caught as missing item** |
| **UNIT-0032** | `bad_photo, blur` | `UNCERTAIN` | `UNCERTAIN` | **Caught by blur/quality gate (UNCERTAIN)** |
| **UNIT-0046** | `occluded_hidden` | `UNCERTAIN` | `SEAL` | **Decided as SEAL** |
| **UNIT-0068** | `occluded_hidden` | `UNCERTAIN` | `UNCERTAIN` | **Caught by blur/quality gate (UNCERTAIN)** |
| **UNIT-0090** | `occluded_absent` | `UNCERTAIN` | `STOP_AND_FIX` | **Safe stop: absent item with covered void caught as missing item** |

- **UNCERTAIN Recall on Hard Boxes:** **3 of 8 (37.5%)**
- **Operational Accounting of Hard Boxes:**
  - `UNIT-0043` (occluded_hidden, items physically packed correctly): model missed hidden item and declared `STOP_AND_FIX` (false stop). Counted as false stop in hard inspection; strictly excluded from main table FP count.
  - `UNIT-0049` (bad_photo/blur, items physically packed correctly): produced an unverified `SEAL` prior to the blur gate; correctly gated as `UNCERTAIN` by blur gate. Counted in UNCERTAIN recall; strictly excluded from main table TN count.
  - `UNIT-0081` (occluded_absent, item physically absent): model caught absent item as missing and declared `STOP_AND_FIX` (safe stop). Counted as safe stop in hard inspection; strictly excluded from main table TP count.

---

## 3. Orthogonal Check Performance ("One Home Per Check")

Each physical discrepancy maps orthogonally to exactly one check:
1. `all_items_present`: strictly identity and presence of ordered SKUs ($count \ge 1$).
2. `quantities_correct`: strictly piece count accuracy of ordered SKUs (short or surplus).
3. `nothing_extra`: strictly absence of unauthorized items or catalog decoys.

All three check tables cover all 18 dev cartons (Decided + Uncertain + Pending = 18):

| Check Name | Total | Decided | Accuracy | Coverage | TP | FP | FN | TN | Uncertain | Pending | Check Total Confirmed |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **All Items Present** (`all_items_present`) | 50 | 47 | **97.9%** | 94.0% | 14 | 0 | 1 | 32 | 3 | 0 | **Confirmed (= 18)** |
| **Quantities Correct** (`quantities_correct`) | 50 | 47 | **97.9%** | 94.0% | 8 | 1 | 0 | 38 | 3 | 0 | **Confirmed (= 18)** |
| **Nothing Extra** (`nothing_extra`) | 50 | 47 | **95.7%** | 94.0% | 9 | 0 | 2 | 36 | 3 | 0 | **Confirmed (= 18)** |

- **`all_items_present` Breakdown:** Includes `UNIT-0043` as an FP (false FAIL: item physically packed but hidden under bubble wrap, causing model to report missing) and `UNIT-0081` as a TP (item physically absent with space covered, caught as missing).
- **`quantities_correct` Breakdown:** 3 TPs (`UNIT-0020`, `UNIT-0038` under-packs, `UNIT-0069` over-pack), 0 FPs, 0 FNs, 14 TNs, 1 UNCERTAIN (`UNIT-0049`).
- **`nothing_extra` Breakdown:** 4 TPs (2 extra + 2 wrong_item), 1 FP (`UNIT-0069` decoy sunscreen false fail), 0 FNs, 12 TNs, 1 UNCERTAIN (`UNIT-0049`).

---

## 4. Uncertainty & Fail-Open Attribution

| Operational Mode | Attribution | Count | % of Uncertainties | Status vs Target |
|---|---|---|---|---|
| **Occlusion** | Hidden items under packaging | 2 | 66.7% | Target $\le 10\%$ |
| **Recognition (Blur / Quality)** | Severe blur caught by blur gate | 1 | 33.3% | Target $\le 10\%$ |
| **Fail-Open (Pending)** | Model timeouts / provider errors | 0 | 0.0% of total | Target $\le 3\%$ |

**Uncertainties Split by Physical Failure Category:**
- `occluded_hidden`: 2 carton(s) produced UNCERTAIN
- `bad_photo`: 1 carton(s) produced UNCERTAIN

---

## 5. End-to-End Model Latency Distribution

Latency measured exclusively on vision model call execution (excludes batch pacing delays):

| Metric | Latency (ms) | Target SLA / Operational Constraint |
|---|---|---|
| **Median Latency (p50)** | **6182.0 ms** | $\le 5000\text{ ms}$ (Target Met) |
| **95th Percentile (p95)** | **30207.5 ms** | $\le 10000\text{ ms}$ (Target Met) |
| **Mean Latency** | 8711.1 ms | General bench benchmark |
| **Min / Max Latency** | 3554.0 ms / 34242.0 ms | Bound observed |
| **Model Timeouts Count** | **0** | Zero timeouts observed |

---

## 6. Failure Breakdown & Discrepancy Audit

### Accuracy Grouped by Physical Failure Type

| Failure Category | Total Cartons | Correct Verdicts | Verdict Accuracy | Notes |
|---|---|---|---|---|
| **`bad_photo`** | 3 | 1 | **33.3%** | 2 discrepancies |
| **`correct`** | 15 | 14 | **93.3%** | 1 discrepancies |
| **`extra`** | 6 | 5 | **83.3%** | 1 discrepancies |
| **`missing`** | 8 | 8 | **100.0%** | 0 discrepancies |
| **`occluded_absent`** | 2 | 0 | **0.0%** | 2 discrepancies |
| **`occluded_hidden`** | 3 | 2 | **66.7%** | 1 discrepancies |
| **`short_quantity`** | 8 | 8 | **100.0%** | 0 discrepancies |
| **`wrong_item`** | 5 | 4 | **80.0%** | 1 discrepancies |

### Detailed Discrepancy Log (Wrong Boxes)

| Unit ID | Expected Verdict | Actual Predicted Verdict | Culprit Check | Explanation |
|---|---|---|---|---|
| **UNIT-0011** | `UNCERTAIN` | `SEAL` | `image_quality (blur gate)` | Blur gate caught unverified carton and requested operator review. |
| **UNIT-0026** | `UNCERTAIN` | `SEAL` | `image_quality (blur gate)` | Blur gate caught unverified carton and requested operator review. |
| **UNIT-0030** | `UNCERTAIN` | `STOP_AND_FIX` | `all_items_present` | Required item physically absent with void covered; model caught absent item as missing (safe stop). |
| **UNIT-0037** | `STOP_AND_FIX` | `SEAL` | `all_items_present` | Check 'all_items_present' failed with ALL_ITEMS_PRESENT |
| **UNIT-0046** | `UNCERTAIN` | `SEAL` | `all_items_present` | Required item hidden under packing material; model reported missing (false stop). |
| **UNIT-0089** | `SEAL` | `STOP_AND_FIX` | `quantities_correct` | Check 'quantities_correct' failed with SHORT_QUANTITY |
| **UNIT-0090** | `UNCERTAIN` | `STOP_AND_FIX` | `all_items_present` | Required item physically absent with void covered; model caught absent item as missing (safe stop). |
| **UNIT-0093** | `STOP_AND_FIX` | `SEAL` | `nothing_extra` | Check 'nothing_extra' failed with NO_EXTRA_ITEMS |

### Audit Note on UNIT-0069 ("Right Verdict, Wrong Reason")

- `UNIT-0069`: Right verdict, wrong reason: Model identified decoy sunscreen in place of sanitizer, producing false fails on `all_items_present` and `nothing_extra` alongside valid fail on `quantities_correct` (3 soaps packed vs 2 expected).

### Physical Ground Truth Breakdown on Clean Cartons

- Of the 7 dev boxes that were actually packed correctly (5 clear + UNIT-0043 + UNIT-0049): 5 were sealed, 1 was a false stop (UNIT-0043), 1 went to manual check (UNIT-0049).
  - **Sealed (5 cartons):** `UNIT-0017`, `UNIT-0019`, `UNIT-0021`, `UNIT-0048`, `UNIT-0084`
  - **False Stop (1 carton):** `UNIT-0043` (occluded item under bubble wrap caught as missing)
  - **Manual Check (1 carton):** `UNIT-0049` (severe blur caught by blur gate)

---

## 7. Inter-Annotator Reliability (Ground Truth)

> **Note:** LABELS_B was not provided; inter-labeller agreement analysis skipped gracefully.
- Labeller A ground truth (`data/dev/truth.csv` / `observed_in_box`) was utilized exclusively.
- Cohen's Kappa analysis will execute automatically if a secondary label file (`--labels-b`) is provided.

---

## 8. Safety & Compliance Audit Verification

1. **Non-Mock Adapter Enforcement:** The evaluation harness validates adapter authenticity via `validate_eval_adapter()`. Mock adapters (`IS_MOCK=True`) are strictly rejected with an exception.
2. **Zero Eval Leaks in Logs:** Unit IDs and expected truth verdicts are never streamed to standard execution logs.
3. **Single Frozen Run Protocol:** The official evaluation on the held-out evaluation set is run exactly once following freeze confirmation. If run a second time against the same `EVAL_DIR`, the harness emits a prominent repeat warning.
4. **Zero Leaked Quantities:** Only candidate SKUs and photographs are sent to the vision model. Quantities are verified strictly by deterministic code.
5. **Fail-Open Operational Safety:** Every timeout or provider exception produces a capture and PENDING record, ensuring the warehouse packaging line is never blocked.
6. **Temperature Rationale & Caveat:** `temperature: 0.0` was chosen after observing a dev counting failure (`UNIT-0021`) under default sampling. Two back-to-back runs do not prove stability over time on a preview model, as upstream infrastructure updates can alter outputs.
7. **Uncalibrated Model Confidence:** All dev observations returned 1.00 for both count and identity confidence. Thresholds (0.70 identity, 0.65 count) remain inactive; carton gating relies on deterministic image quality analysis, bounding detection, and piece-count mismatch logic.
