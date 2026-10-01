# Pack Manager · Evaluation Report (Held-Out Evaluation Set)

**Evaluation Pipeline:** Pack Manager Verification Suite (Stage 3)  
**Author:** Sumani (`b-sumani`)  
**Status:** ⏳ PENDING FROZEN RUN  
**Evaluation Dataset:** `eval_set_50_units` (50 units held out, unviewed)  
**Model for Evaluation:** `gemini-3.1-flash-lite-preview` (read from `MODEL_NAME_EVAL`, single unified preview model)  
**Prompt Version:** `pack-prompt-v1.0` (frozen)  
**Threshold Config Version:** `v1.0.0` (frozen)  
**Protocol:** Single frozen run on held-out evaluation set. Executed strictly once following owner freeze confirmation.

---

## 1. Evaluation Methodology & Metric Separation

Pack Manager evaluates outbound cartons using single-shot top-down vision verification immediately before sealing. 

### The Operational Decision Boundary
At the pack bench, the agent produces one primary operational outcome:
- **`SEAL` (Approved)**: Outbound parcel approved for sealing and label application.
- **`STOP_AND_FIX` (Rejected)**: Physical discrepancy detected. Carton stopped for repacking.
- **`UNCERTAIN` (Manual Inspection Required)**: Image quality, glare, or occlusion prevented clear verification. Operator is alerted: *"The agent could not verify this box. Please check the photo manually."* Operator action is `STOP`; record preserves true `UNCERTAIN` outcome.
- **`PENDING` (Fail-Open)**: Model timeout or unrecoverable API error. Operator is alerted: *"Agent unavailable: seal on your own judgment"*. Line continues without interruption.

### Metric Isolation Rule
$$\text{Decided Accuracy} = \frac{\text{TP} + \text{TN}}{\text{Decided Total}}$$
$$\text{Operational Coverage} = \frac{\text{Decided Total}}{\text{Total Units}}$$
$$\text{Escaped Mis-ship Rate (FN Rate)} = \frac{\text{FN}}{\text{Total Defective Units}}$$
$$\text{False Stoppage Rate (FP Rate)} = \frac{\text{FP}}{\text{Total Clean Units}}$$
$$\text{Uncertain Rate} = \frac{\text{Uncertain Count}}{\text{Total Units}}$$
$$\text{Pending Rate} = \frac{\text{Pending Count}}{\text{Total Units}}$$

> **Non-Negotiable Isolation Standard**: `UNCERTAIN` and `PENDING` cases are strictly excluded from $\text{TP}$, $\text{FP}$, $\text{FN}$, and $\text{TN}$. They represent incomplete verifications or fail-open safety events, not misclassifications.
> 
> > **Batch-Runner Pacing Note**: Automated benchmark evaluations enforce a 7-second inter-unit pacing interval to respect free-tier API provider quotas and prevent throttling-induced fail-opens (`pending = 0`). This is a test harness batch pacing setting, not a live packing-bench latency or takt-time claim. Live operations execute on-demand per packing event.
> 
> > **Stochastic Run-to-Run Variance Protocol**: To measure stochastic stability prior to freeze, the dev set was run twice consecutively under `temperature: 0.0`. Across both runs, 0 of 18 verdicts changed (0.0% variance) and 0 per-SKU counts changed across all 18 boxes. Setting `temperature: 0.0` eliminated count fluctuations observed at default temperatures. The frozen evaluation run will execute strictly under this deterministic `temperature: 0.0` configuration.
> 
> > **Model Confidence Calibration Note**: model-reported confidence was near-constant on the dev set and is not a reliable signal (all observations returned 1.00 for both count and identity confidence across all 18 dev cartons, including blurry and occluded boxes). As a result, the confidence thresholds (0.70 identity, 0.65 count) remained inactive during dev evaluation. Carton gating relies on deterministic image quality analysis, bounding detection, and piece-count mismatch logic.

---

## 2. Executive Summary & Operational Targets

_Result table will be populated upon completion of the single frozen evaluation run._

| Metric | Target | Actual (Frozen Eval Set) | Operational Status |
|---|---|---|---|
| **Uncertain Rate** | $\le 10.0\%$ (Kill: $> 20.0\%$) | — | [Pending frozen run] |
| **Pending Rate (Fail-Open)** | $\le 3.0\%$ | — | [Pending frozen run] |
| **Decided Accuracy** | High | — | [Pending frozen run] |
| **Operational Coverage** | High | — | [Pending frozen run] |
| **Escaped Mis-ships (FN Rate)** | Lowest possible ($0.0\%$) | — | [Pending frozen run] |
| **False Stoppages (FP Rate)** | Low | — | [Pending frozen run] |
| **Median Latency (p50)** | $\le 5000\text{ ms}$ | — | [Pending frozen run] |
| **95th Percentile (p95)** | $\le 10000\text{ ms}$ | — | [Pending frozen run] |
| **Inter-Annotator Agreement** | High ($\text{Kappa} \ge 0.60$) | — | [Pending frozen run] |

---

## 3. Box-Level Decision Performance Matrix

| Operational Outcome | Category Definition | Count | Rate |
|---|---|---|---|
| **True Positives (TP)** | Defective box correctly stopped (`STOP_AND_FIX`) | — | — |
| **True Negatives (TN)** | Clean box correctly approved (`SEAL`) | — | — |
| **False Negatives (FN)** | Defective box erroneously approved (`SEAL` / Escaped mis-ship) | — | — |
| **False Positives (FP)** | Clean box erroneously stopped (`STOP_AND_FIX` / False stoppage) | — | — |
| **Uncertain Cases** | Human operator manual check requested | — | — |
| **Pending Cases** | Fail-open triggered (timeout / provider error) | — | — |

---

## 4. Orthogonal Check Performance ("One Home Per Check")

Pack Manager maps every defect to exactly one check:
1. `all_items_present`: strictly identity and presence of ordered items ($count \ge 1$).
2. `quantities_correct`: strictly piece count accuracy of ordered items (short or surplus).
3. `nothing_extra`: strictly absence of unauthorized items (catalog decoys or foreign objects).

| Check Name | Total Units | Decided | Accuracy | TP | FP | FN | TN | Uncertain | Pending |
|---|---|---|---|---|---|---|---|---|---|
| **All Items Present** | 50 | — | — | — | — | — | — | — | — |
| **Quantities Correct** | 50 | — | — | — | — | — | — | — | — |
| **Nothing Extra** | 50 | — | — | — | — | — | — | — | — |

---

## 5. Failure Mode Breakdown

| Failure / Uncertainty Category | Cause Attribution | Count | % of Uncertainties |
|---|---|---|---|
| **Occlusion (Hidden Items)** | `cause='occlusion'` | — | — |
| **Recognition (Low Confidence / Glare)** | `cause='recognition'` | — | — |

---

## 6. End-to-End Latency Distribution

End-to-end model call latency per unit (including single call and transport retries inside the 15-second budget):

| Latency Metric | Measured Latency (ms) | Target SLA |
|---|---|---|
| **Median (p50)** | — | $\le 5000\text{ ms}$ |
| **95th Percentile (p95)** | — | $\le 10000\text{ ms}$ |
| **Mean** | — | — |
| **Min / Max** | — | — |

---

## 7. Inter-Annotator Reliability (Ground Truth)

Ground truth verification across independent human reviewers on the 50-unit evaluation set:

- **Raw Percentage Agreement:** — [Pending frozen run]
- **Cohen's Kappa:** — [Pending frozen run]

---

## 8. Compliance & Audit Commitments

1. **Non-Mock Adapter Enforcement**: The evaluation harness strictly executes `validate_eval_adapter()`. The harness refuses to run if any mock adapter is supplied.
2. **Single Frozen Run Protocol**: Per Section 15 of `context.md`, the 50-unit evaluation set is never viewed, tuned against, or executed during development. The evaluation will be executed exactly once following explicit owner confirmation of prompt and threshold freeze.
3. **Zero Leaked Quantities**: Order quantities are never provided to the vision model. The model receives only candidate SKUs and the photograph. Count verification is performed entirely in deterministic code.
4. **Dev Set Separation**: Iterative development measurements on synthetic dev fixtures are preserved separately in `eval/dev_report.md` and are never substituted for evaluation set findings.
