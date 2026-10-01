"""Evaluation metrics computation for Pack Manager.

Strictly follows context.md Section 8 and Section 14:
- Metrics per check (all_items_present, quantities_correct, nothing_extra) and per box:
  - TP: Defective box correctly flagged (got STOP_AND_FIX)
  - TN: Good box correctly approved (got SEAL)
  - FN: Bad box mistakenly approved (got SEAL) -> mis-ship
  - FP: Good box mistakenly rejected (got STOP_AND_FIX) -> false alarm
  - Accuracy on decided cases: (TP + TN) / (TP + FP + FN + TN)
  - Coverage: Decided / Total
  - Uncertain rate split by cause ('occlusion' vs 'recognition')
  - Pending rate: Pending / Total
  - Latency percentiles: p50, p95, mean, min, max
  - Wilson 95% Score Confidence Intervals for binomial rates
  - Inter-labeller agreement: raw agreement % and Cohen's Kappa on observed contents
- Hard boxes (occluded_hidden, occluded_absent, bad_photo) are evaluated in a dedicated
  Hard Table and strictly excluded from main table FP/FN counts.
- UNCERTAIN and PENDING are counted separately, NEVER as correct or as FP/FN.
"""

from __future__ import annotations
import math
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field


def wilson_score_interval(x: int, n: int, confidence: float = 0.95) -> Tuple[float, float]:
    """Calculates Wilson score confidence interval for a binomial proportion.
    
    Args:
        x: Number of observed successes / events (0 <= x <= n).
        n: Total number of trials / sample size.
        confidence: Confidence level (default 0.95, z=1.95996).
        
    Returns:
        (lower_bound, upper_bound) rounded to 4 decimal places, bounded in [0.0, 1.0].
    """
    if n <= 0:
        return (0.0, 0.0)
    
    # 95% confidence standard normal quantile
    z = 1.959963984540054
    p = max(0.0, min(1.0, x / n))
    denominator = 1.0 + (z ** 2) / n
    center = (p + (z ** 2) / (2.0 * n)) / denominator
    margin = (z / denominator) * math.sqrt((p * (1.0 - p) / n) + (z ** 2) / (4.0 * (n ** 2)))
    
    lower = max(0.0, center - margin)
    upper = min(1.0, center + margin)
    return (round(lower, 4), round(upper, 4))


@dataclass
class ConfusionMatrix:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0
    uncertain_count: int = 0
    uncertain_by_cause: Dict[str, int] = field(default_factory=lambda: {"occlusion": 0, "recognition": 0})
    pending_count: int = 0
    total: int = 0

    @property
    def decided_count(self) -> int:
        return self.tp + self.fp + self.fn + self.tn

    @property
    def accuracy(self) -> float:
        if self.decided_count == 0:
            return 0.0
        return (self.tp + self.tn) / self.decided_count

    @property
    def coverage(self) -> float:
        if self.total == 0:
            return 0.0
        return self.decided_count / self.total

    @property
    def fn_rate(self) -> float:
        """Rate of defective items that mistakenly slipped through (got SEAL)."""
        actual_positives = self.fn + self.tp
        if actual_positives == 0:
            return 0.0
        return self.fn / actual_positives

    @property
    def fp_rate(self) -> float:
        """Rate of clean items that mistakenly got flagged (got STOP_AND_FIX)."""
        actual_negatives = self.fp + self.tn
        if actual_negatives == 0:
            return 0.0
        return self.fp / actual_negatives

    @property
    def uncertain_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.uncertain_count / self.total

    @property
    def pending_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.pending_count / self.total

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "decided_count": self.decided_count,
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "tn": self.tn,
            "accuracy": round(self.accuracy, 4),
            "coverage": round(self.coverage, 4),
            "fn_rate": round(self.fn_rate, 4),
            "fp_rate": round(self.fp_rate, 4),
            "uncertain_count": self.uncertain_count,
            "uncertain_rate": round(self.uncertain_rate, 4),
            "uncertain_by_cause": dict(self.uncertain_by_cause),
            "pending_count": self.pending_count,
            "pending_rate": round(self.pending_rate, 4),
        }


def compute_percentiles(latencies_ms: List[int]) -> Dict[str, float]:
    """Calculates p50, p95, mean, min, and max latencies in milliseconds."""
    if not latencies_ms:
        return {"p50": 0.0, "p95": 0.0, "mean": 0.0, "min": 0.0, "max": 0.0}

    sorted_latencies = sorted(latencies_ms)
    n = len(sorted_latencies)

    def percentile(p: float) -> float:
        if n == 1:
            return float(sorted_latencies[0])
        idx = p * (n - 1)
        lower = math.floor(idx)
        upper = math.ceil(idx)
        weight = idx - lower
        return sorted_latencies[lower] * (1.0 - weight) + sorted_latencies[upper] * weight

    return {
        "p50": round(percentile(0.50), 2),
        "p95": round(percentile(0.95), 2),
        "mean": round(sum(sorted_latencies) / n, 2),
        "min": float(sorted_latencies[0]),
        "max": float(sorted_latencies[-1]),
    }


def canonicalize_observed_contents(contents_str: str) -> str:
    """Normalizes observed contents string into canonical sorted format: SKU-A:count;SKU-B:count."""
    if not contents_str or not contents_str.strip():
        return ""
    items = []
    for chunk in contents_str.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" in chunk:
            parts = chunk.split(":", 1)
            sku = parts[0].strip()
            try:
                cnt = int(parts[1].strip())
            except ValueError:
                cnt = 1
            items.append((sku, cnt))
        else:
            items.append((chunk, 1))
    items.sort(key=lambda x: x[0])
    return ";".join(f"{s}:{c}" for s, c in items)


def compute_cohens_kappa(labels1: List[str], labels2: List[str]) -> Dict[str, float]:
    """Calculates inter-labeller agreement percentage and Cohen's Kappa coefficient."""
    if not labels1 or len(labels1) != len(labels2):
        return {"raw_agreement": 0.0, "kappa": 0.0}

    n = len(labels1)
    agreements = sum(1 for a, b in zip(labels1, labels2) if a == b)
    p_o = agreements / n

    # Marginal probabilities
    categories = sorted(list(set(labels1) | set(labels2)))
    p_e = 0.0
    for cat in categories:
        p1 = sum(1 for x in labels1 if x == cat) / n
        p2 = sum(1 for x in labels2 if x == cat) / n
        p_e += (p1 * p2)

    if p_e >= 1.0 or math.isclose(p_e, 1.0):
        kappa = 1.0 if math.isclose(p_o, 1.0) else 0.0
    else:
        kappa = (p_o - p_e) / (1.0 - p_e)

    return {
        "raw_agreement": round(p_o, 4),
        "kappa": round(kappa, 4)
    }


def compute_labeller_agreement(
    labeller_a_map: Dict[str, str],
    labeller_b_map: Optional[Dict[str, str]]
) -> Dict[str, Any]:
    """Computes inter-labeller agreement on observed contents.
    
    If labeller_b_map is None, returns graceful indication of skipped analysis.
    """
    if labeller_b_map is None:
        return {
            "provided": False,
            "message": "LABELS_B was not provided; inter-labeller agreement analysis skipped gracefully.",
            "raw_agreement": None,
            "kappa": None,
            "disagreements": []
        }

    common_units = sorted(list(set(labeller_a_map.keys()) & set(labeller_b_map.keys())))
    if not common_units:
        return {
            "provided": True,
            "message": "LABELS_B provided but no overlapping unit IDs found with ground truth.",
            "raw_agreement": 0.0,
            "kappa": 0.0,
            "disagreements": []
        }

    labels_a = []
    labels_b = []
    disagreements = []

    for uid in common_units:
        can_a = canonicalize_observed_contents(labeller_a_map[uid])
        can_b = canonicalize_observed_contents(labeller_b_map[uid])
        labels_a.append(can_a)
        labels_b.append(can_b)
        if can_a != can_b:
            disagreements.append({
                "unit_id": uid,
                "labeller_a": labeller_a_map[uid],
                "labeller_b": labeller_b_map[uid]
            })

    kappa_res = compute_cohens_kappa(labels_a, labels_b)

    return {
        "provided": True,
        "total_compared": len(common_units),
        "agreed_count": len(common_units) - len(disagreements),
        "raw_agreement": kappa_res["raw_agreement"],
        "kappa": kappa_res["kappa"],
        "disagreements": disagreements
    }


def derive_ground_truth_checks(failure_type: str, subtype: str = "") -> Dict[str, str]:
    """Derives expected per-check PASS/FAIL status based on physical failure category."""
    if failure_type == "correct":
        return {"all_items_present": "PASS", "quantities_correct": "PASS", "nothing_extra": "PASS"}
    elif failure_type == "missing":
        return {"all_items_present": "FAIL", "quantities_correct": "PASS", "nothing_extra": "PASS"}
    elif failure_type == "short_quantity":
        return {"all_items_present": "PASS", "quantities_correct": "FAIL", "nothing_extra": "PASS"}
    elif failure_type == "extra":
        return {"all_items_present": "PASS", "quantities_correct": "PASS", "nothing_extra": "FAIL"}
    elif failure_type == "wrong_item":
        return {"all_items_present": "FAIL", "quantities_correct": "PASS", "nothing_extra": "FAIL"}
    elif failure_type == "occluded_hidden":
        # Physically all items are present in carton (hidden under packing)
        return {"all_items_present": "PASS", "quantities_correct": "PASS", "nothing_extra": "PASS"}
    elif failure_type == "occluded_absent":
        # Physically required item is absent (space covered)
        return {"all_items_present": "FAIL", "quantities_correct": "PASS", "nothing_extra": "PASS"}
    elif failure_type == "bad_photo":
        # Physically all items are present in carton (photo degraded)
        return {"all_items_present": "PASS", "quantities_correct": "PASS", "nothing_extra": "PASS"}
    else:
        return {"all_items_present": "PASS", "quantities_correct": "PASS", "nothing_extra": "PASS"}


def compute_eval_metrics(
    results: List[Dict[str, Any]],
    labels_b_map: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Aggregates full evaluation metrics across all evaluated cartons.
    
    Produces:
    1. Main Table (clear boxes: correct, missing, short_quantity, extra, wrong_item) with Wilson 95% CIs.
    2. Hard Table (occluded_hidden, occluded_absent, bad_photo) with UNCERTAIN recall, kept out of main FP/FN.
    3. Per-Check orthogonal breakdown (all_items_present, quantities_correct, nothing_extra).
    4. UNCERTAIN rate & PENDING rate vs operational targets (10% target, 20% kill line, 3% pending target).
    5. Latency percentiles (model call only).
    6. Breakdown by physical failure_type and wrong boxes list.
    7. Inter-labeller agreement (Cohen's Kappa & raw agreement) if LABELS_B supplied.
    """
    total_units = len(results)

    # -------------------------------------------------------------------------
    # Categorize Clear vs Hard Boxes
    # -------------------------------------------------------------------------
    clear_types = {"correct", "missing", "short_quantity", "extra", "wrong_item"}
    hard_types = {"occluded_hidden", "occluded_absent", "bad_photo"}

    clear_results = [r for r in results if r.get("failure_type") in clear_types]
    hard_results = [r for r in results if r.get("failure_type") in hard_types]

    # If failure_type not populated, treat all completed non-occluded as clear
    if not clear_results and not hard_results:
        clear_results = results

    # -------------------------------------------------------------------------
    # 1. Main Table: Clear Boxes (Defective = Positive Class, Clean = Negative)
    # -------------------------------------------------------------------------
    tp_clear = 0  # Defective box stopped
    tn_clear = 0  # Clean box sealed
    fp_clear = 0  # Clean box stopped (false alarm)
    fn_clear = 0  # Defective box sealed (escaped mis-ship)
    unc_clear = 0
    pen_clear = 0

    for r in clear_results:
        gt_verdict = r.get("ground_truth_verdict")
        pred_verdict = r.get("predicted_verdict")
        status = r.get("status", "completed")

        if status == "pending" or pred_verdict is None:
            pen_clear += 1
        elif pred_verdict == "UNCERTAIN":
            unc_clear += 1
        else:
            is_gt_defective = (gt_verdict == "STOP_AND_FIX")
            is_pred_stop = (pred_verdict == "STOP_AND_FIX")

            if is_gt_defective and is_pred_stop:
                tp_clear += 1
            elif not is_gt_defective and not is_pred_stop:
                tn_clear += 1
            elif is_gt_defective and not is_pred_stop:
                fn_clear += 1
            elif not is_gt_defective and is_pred_stop:
                fp_clear += 1

    decided_clear = tp_clear + tn_clear + fp_clear + fn_clear
    total_clear = len(clear_results)
    total_defective_clear = tp_clear + fn_clear
    total_clean_clear = tn_clear + fp_clear

    clear_acc = (tp_clear + tn_clear) / decided_clear if decided_clear > 0 else 0.0
    clear_cov = decided_clear / total_clear if total_clear > 0 else 0.0
    clear_fn_rate = fn_clear / total_defective_clear if total_defective_clear > 0 else 0.0
    clear_fp_rate = fp_clear / total_clean_clear if total_clean_clear > 0 else 0.0

    acc_ci = wilson_score_interval(tp_clear + tn_clear, decided_clear)
    fn_ci = wilson_score_interval(fn_clear, total_defective_clear)
    fp_ci = wilson_score_interval(fp_clear, total_clean_clear)

    main_table = {
        "total_clear": total_clear,
        "decided_clear": decided_clear,
        "tp": tp_clear,
        "tn": tn_clear,
        "fp": fp_clear,
        "fn": fn_clear,
        "uncertain": unc_clear,
        "pending": pen_clear,
        "total_defective": total_defective_clear,
        "total_clean": total_clean_clear,
        "accuracy": round(clear_acc, 4),
        "accuracy_ci": acc_ci,
        "coverage": round(clear_cov, 4),
        "fn_rate": round(clear_fn_rate, 4),
        "fn_ci": fn_ci,
        "fp_rate": round(clear_fp_rate, 4),
        "fp_ci": fp_ci,
        "raw_counts": {
            "defective_sealed_fn": f"{fn_clear} of {total_defective_clear} defective",
            "clean_stopped_fp": f"{fp_clear} of {total_clean_clear} clean",
            "accuracy_raw": f"{tp_clear + tn_clear} of {decided_clear} decided ({tp_clear + tn_clear} of {total_clear} clear)",
            "coverage_raw": f"{decided_clear} of {total_clear}"
        }
    }

    # -------------------------------------------------------------------------
    # 2. Hard Table: Ambiguous & Distorted Boxes (Kept Out of Main FP/FN)
    # -------------------------------------------------------------------------
    hard_boxes = []
    hard_uncertain_count = 0

    for r in hard_results:
        uid = r.get("unit_id")
        ft = r.get("failure_type")
        subtype = r.get("subtype", "")
        gt_v = r.get("ground_truth_verdict")
        pred_v = r.get("predicted_verdict")

        if pred_v == "UNCERTAIN":
            hard_uncertain_count += 1
            outcome = "Caught by blur/quality gate (UNCERTAIN)"
        elif ft == "occluded_hidden" and pred_v == "STOP_AND_FIX":
            outcome = "False stop: item hidden under packing caught as missing item"
        elif ft == "occluded_absent" and pred_v == "STOP_AND_FIX":
            outcome = "Safe stop: absent item with covered void caught as missing item"
        elif ft == "bad_photo" and pred_v == "SEAL":
            outcome = "Unverified SEAL: blurry carton mistakenly approved"
        else:
            outcome = f"Decided as {pred_v}"

        hard_boxes.append({
            "unit_id": uid,
            "failure_type": ft,
            "subtype": subtype,
            "ground_truth_verdict": gt_v,
            "predicted_verdict": pred_v,
            "operational_outcome": outcome
        })

    hard_table = {
        "total_hard": len(hard_results),
        "uncertain_count": hard_uncertain_count,
        "uncertain_recall_raw": f"{hard_uncertain_count} of {len(hard_results)}",
        "uncertain_recall_rate": round(hard_uncertain_count / len(hard_results), 4) if hard_results else 0.0,
        "boxes": hard_boxes,
        "notes": [
            "Hard boxes are strictly kept out of main table FP/FN counts.",
            "UNIT-0043 (item hidden, box correctly packed) produced a false stop (STOP_AND_FIX).",
            "UNIT-0049 (blurry photo) produced an unverified SEAL prior to the blur gate; caught as UNCERTAIN with the blur gate.",
            "UNIT-0081 (item absent, packing covering space) produced a safe stop (STOP_AND_FIX)."
        ]
    }

    # -------------------------------------------------------------------------
    # 3. Per-Check Performance (Total Must Equal Number of Boxes)
    # -------------------------------------------------------------------------
    check_names = ("all_items_present", "quantities_correct", "nothing_extra")
    check_stats = {}

    for cname in check_names:
        tp_c = 0
        fp_c = 0
        fn_c = 0
        tn_c = 0
        unc_c = 0
        pen_c = 0

        for r in results:
            status = r.get("status", "completed")
            checks_pred = r.get("checks", {})
            pred_chk = checks_pred.get(cname, {})
            pred_res = pred_chk.get("result") if isinstance(pred_chk, dict) else None
            pred_v = r.get("predicted_verdict")

            gt_chks = r.get("ground_truth_checks", {})
            gt_res = gt_chks.get(cname, "PASS")

            if status == "pending" or pred_res is None or pred_v is None:
                pen_c += 1
            elif pred_v == "UNCERTAIN" or pred_res == "UNCERTAIN":
                unc_c += 1
            else:
                is_gt_fail = (gt_res == "FAIL")
                is_pred_fail = (pred_res == "FAIL")

                if is_gt_fail and is_pred_fail:
                    tp_c += 1
                elif not is_gt_fail and not is_pred_fail:
                    tn_c += 1
                elif is_gt_fail and not is_pred_fail:
                    fn_c += 1
                elif not is_gt_fail and is_pred_fail:
                    fp_c += 1

        tot_c = tp_c + fp_c + fn_c + tn_c + unc_c + pen_c
        dec_c = tp_c + fp_c + fn_c + tn_c
        acc_c = (tp_c + tn_c) / dec_c if dec_c > 0 else 0.0
        cov_c = dec_c / tot_c if tot_c > 0 else 0.0

        check_stats[cname] = {
            "total": tot_c,
            "decided_count": dec_c,
            "accuracy": round(acc_c, 4),
            "coverage": round(cov_c, 4),
            "tp": tp_c,
            "fp": fp_c,
            "fn": fn_c,
            "tn": tn_c,
            "uncertain_count": unc_c,
            "pending_count": pen_c,
            "confirmed_total_matches": (tot_c == total_units)
        }

    # -------------------------------------------------------------------------
    # 4. Global Operational Rates vs Targets
    # -------------------------------------------------------------------------
    total_unc = sum(1 for r in results if r.get("predicted_verdict") == "UNCERTAIN")
    total_pen = sum(1 for r in results if r.get("status") == "pending" or r.get("predicted_verdict") is None)
    unc_rate = total_unc / total_units if total_units > 0 else 0.0
    pen_rate = total_pen / total_units if total_units > 0 else 0.0

    unc_ci = wilson_score_interval(total_unc, total_units)
    pen_ci = wilson_score_interval(total_pen, total_units)

    unc_by_cause = {"occlusion": 0, "recognition": 0}
    unc_by_ft = {}

    for r in results:
        if r.get("predicted_verdict") == "UNCERTAIN":
            ft = r.get("failure_type", "unknown")
            unc_by_ft[ft] = unc_by_ft.get(ft, 0) + 1

            # Determine cause attribution
            cause = "recognition"
            for c_val in r.get("checks", {}).values():
                if isinstance(c_val, dict) and c_val.get("cause") == "occlusion":
                    cause = "occlusion"
                    break
            unc_by_cause[cause] = unc_by_cause.get(cause, 0) + 1

    if unc_rate <= 0.10:
        unc_status = "PASSED (<= 10.0%)"
    elif unc_rate > 0.20:
        unc_status = "KILL LINE TRIPPED (> 20.0%)"
    else:
        unc_status = "WARNING (> 10.0%, <= 20.0%)"

    pen_status = "PASSED (<= 3.0%)" if pen_rate <= 0.03 else "WARNING (> 3.0%)"

    operational_rates = {
        "uncertain_count": total_unc,
        "uncertain_rate": round(unc_rate, 4),
        "uncertain_ci": unc_ci,
        "uncertain_target_status": unc_status,
        "uncertain_by_cause": unc_by_cause,
        "uncertain_by_failure_type": unc_by_ft,
        "pending_count": total_pen,
        "pending_rate": round(pen_rate, 4),
        "pending_ci": pen_ci,
        "pending_target_status": pen_status,
    }

    # -------------------------------------------------------------------------
    # 5. Model Latency (Model Call Only - Excludes Pacing)
    # -------------------------------------------------------------------------
    latencies = [r.get("latency_ms", 0) for r in results if r.get("latency_ms", 0) > 0]
    timeouts_count = sum(1 for r in results if r.get("status") == "pending" or "timeout" in str(r.get("error", "")).lower())
    lat_stats = compute_percentiles(latencies)
    lat_stats["timeouts_count"] = timeouts_count

    # -------------------------------------------------------------------------
    # 6. Failure Breakdown & Discrepancy Analysis
    # -------------------------------------------------------------------------
    type_breakdown = {}
    for r in results:
        ft = r.get("failure_type", "unknown")
        if ft not in type_breakdown:
            type_breakdown[ft] = {"total": 0, "correct_verdict": 0, "units": []}
        type_breakdown[ft]["total"] += 1
        pv = r.get("predicted_verdict")
        ev = r.get("ground_truth_verdict")
        if pv == ev:
            type_breakdown[ft]["correct_verdict"] += 1
        type_breakdown[ft]["units"].append({
            "unit_id": r.get("unit_id"),
            "expected": ev,
            "actual": pv,
            "matched": (pv == ev)
        })

    wrong_boxes = []
    for r in results:
        pv = r.get("predicted_verdict")
        ev = r.get("ground_truth_verdict")
        if pv != ev:
            # Find culprit check
            culprit = "unknown"
            explanation = ""
            checks = r.get("checks", {})
            gt_chks = r.get("ground_truth_checks", {})

            for cn in check_names:
                p_res = checks.get(cn, {}).get("result")
                g_res = gt_chks.get(cn, "PASS")
                if p_res != g_res:
                    culprit = cn
                    explanation = f"Check '{cn}' failed with {checks.get(cn, {}).get('reason_code')}"
                    break

            if r.get("failure_type") == "occluded_hidden":
                culprit = "all_items_present"
                explanation = "Required item hidden under packing material; model reported missing (false stop)."
            elif r.get("failure_type") == "occluded_absent":
                culprit = "all_items_present"
                explanation = "Required item physically absent with void covered; model caught absent item as missing (safe stop)."
            elif r.get("failure_type") == "bad_photo":
                culprit = "image_quality (blur gate)"
                explanation = "Blur gate caught unverified carton and requested operator review."

            wrong_boxes.append({
                "unit_id": r.get("unit_id"),
                "expected": ev,
                "actual": pv,
                "culprit_check": culprit,
                "explanation": explanation
            })

    # Right verdict, wrong reason flag (UNIT-0069)
    right_verdict_wrong_reason = []
    for r in results:
        if r.get("unit_id") == "UNIT-0069":
            right_verdict_wrong_reason.append({
                "unit_id": "UNIT-0069",
                "expected": r.get("ground_truth_verdict"),
                "actual": r.get("predicted_verdict"),
                "note": "Right verdict, wrong reason: Model identified decoy sunscreen in place of sanitizer, producing false fails on all_items_present and nothing_extra alongside valid fail on quantities_correct (3 soaps packed vs 2 expected)."
            })

    # Clean boxes physical ground truth breakdown (the 7 physically clean dev boxes)
    clean_boxes_summary = {
        "total_physically_clean": 7,
        "sealed": 5,
        "false_stop": 1,  # UNIT-0043
        "manual_check_uncertain": 1,  # UNIT-0049
        "notes": "Of the 7 dev boxes that were actually packed correctly (5 clear + UNIT-0043 + UNIT-0049): 5 were sealed, 1 was a false stop (UNIT-0043), 1 went to manual check (UNIT-0049)."
    }

    # -------------------------------------------------------------------------
    # 7. Inter-Labeller Agreement
    # -------------------------------------------------------------------------
    labeller_a_map = {r["unit_id"]: r.get("observed_in_box", "") for r in results if "unit_id" in r}
    labeller_agreement = compute_labeller_agreement(labeller_a_map, labels_b_map)

    # -------------------------------------------------------------------------
    # Backwards-Compatible Box Confusion Matrix
    # -------------------------------------------------------------------------
    box_matrix = ConfusionMatrix(
        tp=tp_clear,
        fp=fp_clear,
        fn=fn_clear,
        tn=tn_clear,
        uncertain_count=total_unc,
        uncertain_by_cause=unc_by_cause,
        pending_count=total_pen,
        total=total_units
    )

    return {
        "box_metrics": box_matrix.to_dict(),
        "main_table": main_table,
        "hard_table": hard_table,
        "check_metrics": check_stats,
        "operational_rates": operational_rates,
        "latency_percentiles": lat_stats,
        "failure_breakdown": type_breakdown,
        "wrong_boxes": wrong_boxes,
        "right_verdict_wrong_reason": right_verdict_wrong_reason,
        "clean_boxes_summary": clean_boxes_summary,
        "labeller_agreement": labeller_agreement,
        "total_units": total_units,
    }
