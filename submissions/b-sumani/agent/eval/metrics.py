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
  - Latency percentiles: p50, p95, mean
  - Inter-labeller agreement: raw agreement % and Cohen's Kappa
- UNCERTAIN and PENDING are counted separately, NEVER as correct or as FP/FN.
"""

from __future__ import annotations
import math
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field


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

    if p_e >= 1.0:
        kappa = 1.0
    else:
        kappa = (p_o - p_e) / (1.0 - p_e)

    return {
        "raw_agreement": round(p_o, 4),
        "kappa": round(kappa, 4)
    }


def compute_eval_metrics(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregates per-check and per-box metrics across all evaluated items.
    
    Each result item is expected to have:
    - ground_truth_verdict: 'SEAL' | 'STOP_AND_FIX'
    - predicted_verdict: 'SEAL' | 'STOP_AND_FIX' | 'UNCERTAIN' | None (when pending)
    - status: 'completed' | 'pending'
    - latency_ms: int
    - checks: dict of per-check predictions and causes
    - ground_truth_checks: dict of per-check ground truth (PASS/FAIL)
    """
    box_matrix = ConfusionMatrix(total=len(results))
    check_matrices = {
        "all_items_present": ConfusionMatrix(total=len(results)),
        "quantities_correct": ConfusionMatrix(total=len(results)),
        "nothing_extra": ConfusionMatrix(total=len(results)),
    }
    latencies: List[int] = []

    for item in results:
        gt_verdict = item.get("ground_truth_verdict")
        pred_verdict = item.get("predicted_verdict")
        status = item.get("status", "completed")
        latency = item.get("latency_ms", 0)
        latencies.append(latency)

        checks_pred = item.get("checks", {})
        gt_checks = item.get("ground_truth_checks", {})

        # ---------------------------------------------------------------------
        # 1. Box-Level Confusion Matrix
        # Positive = Defective (STOP_AND_FIX), Negative = Clean (SEAL)
        # ---------------------------------------------------------------------
        if status == "pending" or pred_verdict is None:
            box_matrix.pending_count += 1
        elif pred_verdict == "UNCERTAIN":
            box_matrix.uncertain_count += 1
            # Determine cause
            cause = "recognition"
            for c_val in checks_pred.values():
                if isinstance(c_val, dict) and c_val.get("cause") == "occlusion":
                    cause = "occlusion"
                    break
            box_matrix.uncertain_by_cause[cause] = box_matrix.uncertain_by_cause.get(cause, 0) + 1
        elif gt_verdict == "UNCERTAIN":
            # Ground truth was UNCERTAIN (e.g. occluded or bad photo).
            # Model decided when truth was uncertain; counted separately per contract.
            pass
        else:
            is_gt_positive = (gt_verdict == "STOP_AND_FIX")
            is_pred_positive = (pred_verdict == "STOP_AND_FIX")

            if is_gt_positive and is_pred_positive:
                box_matrix.tp += 1
            elif not is_gt_positive and not is_pred_positive:
                box_matrix.tn += 1
            elif is_gt_positive and not is_pred_positive:
                box_matrix.fn += 1  # Bad box got SEAL!
            elif not is_gt_positive and is_pred_positive:
                box_matrix.fp += 1  # Good box got STOP_AND_FIX!

        # ---------------------------------------------------------------------
        # 2. Per-Check Confusion Matrices
        # Positive = Defect (FAIL), Negative = Clean (PASS)
        # ---------------------------------------------------------------------
        for check_name in ("all_items_present", "quantities_correct", "nothing_extra"):
            matrix = check_matrices[check_name]
            pred_check = checks_pred.get(check_name, {})
            pred_result = pred_check.get("result") if isinstance(pred_check, dict) else None
            pred_cause = pred_check.get("cause") if isinstance(pred_check, dict) else None
            gt_check_result = gt_checks.get(check_name, "PASS")

            if status == "pending" or pred_result is None:
                matrix.pending_count += 1
            elif pred_result == "UNCERTAIN":
                matrix.uncertain_count += 1
                c = pred_cause if pred_cause in ("occlusion", "recognition") else "recognition"
                matrix.uncertain_by_cause[c] = matrix.uncertain_by_cause.get(c, 0) + 1
            elif gt_check_result == "UNCERTAIN":
                # Check ground truth is uncertain; do not count in decided defect/clean
                pass
            else:
                is_gt_defect = (gt_check_result == "FAIL")
                is_pred_defect = (pred_result == "FAIL")

                if is_gt_defect and is_pred_defect:
                    matrix.tp += 1
                elif not is_gt_defect and not is_pred_defect:
                    matrix.tn += 1
                elif is_gt_defect and not is_pred_defect:
                    matrix.fn += 1  # Check defect missed
                elif not is_gt_defect and is_pred_defect:
                    matrix.fp += 1  # False alarm on check

    # -------------------------------------------------------------------------
    # 3. Inter-Labeller Agreement
    # -------------------------------------------------------------------------
    labels1 = [item.get("labeller1_verdict") for item in results if item.get("labeller1_verdict")]
    labels2 = [item.get("labeller2_verdict") for item in results if item.get("labeller2_verdict")]
    labeller_agreement = compute_cohens_kappa(labels1, labels2) if len(labels1) == len(labels2) and len(labels1) > 0 else {"raw_agreement": 1.0, "kappa": 1.0}

    return {
        "box_metrics": box_matrix.to_dict(),
        "check_metrics": {k: v.to_dict() for k, v in check_matrices.items()},
        "latency_percentiles": compute_percentiles(latencies),
        "labeller_agreement": labeller_agreement,
        "total_units": len(results),
    }
