"""Comprehensive unit tests for Pack Manager evaluation metrics, reports, and safety guards.

All test fixtures here use SYNTHETIC predictions (explicitly labelled synthetic fixtures)
to validate metric mathematics, confidence intervals, Cohen's Kappa, safety guards,
and report formatting without touching real eval photos or live models.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from agent.models.base import validate_eval_adapter
from agent.models.mock import MockVisionAdapter
from agent.eval.metrics import (
    wilson_score_interval,
    canonicalize_observed_contents,
    compute_cohens_kappa,
    compute_labeller_agreement,
    derive_ground_truth_checks,
    compute_eval_metrics,
    ConfusionMatrix,
)
from agent.eval.report import generate_markdown_report
from agent.eval.run_eval import check_and_update_eval_history, load_labels_b


# =============================================================================
# 1. Wilson 95% Score Confidence Interval Tests
# =============================================================================

def test_wilson_score_interval_standard_and_edge_cases():
    """Validates Wilson score confidence intervals for standard proportions and boundary conditions."""
    # Zero successes out of 10 (e.g. 0 FN out of 10 defective cartons)
    low, high = wilson_score_interval(0, 10)
    assert low == 0.0
    assert 0.27 <= high <= 0.29  # Approx [0.0, 0.283]

    # Full successes out of 15 (e.g. 15 of 15 clear cartons correct)
    low, high = wilson_score_interval(15, 15)
    assert 0.78 <= low <= 0.81   # Approx [0.796, 1.0]
    assert high == 1.0

    # 1 out of 18 (e.g. 1 of 18 UNCERTAIN)
    low, high = wilson_score_interval(1, 18)
    assert 0.005 <= low <= 0.015  # Approx [0.010, 0.258]
    assert 0.24 <= high <= 0.28

    # Edge case: empty sample size n=0
    low, high = wilson_score_interval(0, 0)
    assert (low, high) == (0.0, 0.0)


# =============================================================================
# 2. Observed Contents Normalization & Inter-Labeller Agreement Tests
# =============================================================================

def test_canonicalize_observed_contents():
    """Validates that observed contents strings are parsed and sorted canonically."""
    raw1 = "SKU-SOAP-MYSORE:2;SKU-PHONE-M36:1"
    raw2 = "SKU-PHONE-M36:1;SKU-SOAP-MYSORE:2"
    assert canonicalize_observed_contents(raw1) == canonicalize_observed_contents(raw2)
    assert canonicalize_observed_contents(raw1) == "SKU-PHONE-M36:1;SKU-SOAP-MYSORE:2"

    # Default count 1 when omitted
    raw_no_count = "SKU-PHONE-M36;SKU-SOAP-MYSORE"
    assert canonicalize_observed_contents(raw_no_count) == "SKU-PHONE-M36:1;SKU-SOAP-MYSORE:1"

    # Empty string
    assert canonicalize_observed_contents("") == ""
    assert canonicalize_observed_contents("   ") == ""


def test_cohens_kappa_perfect_and_partial_agreement():
    """Validates Cohen's Kappa coefficient calculations on categorical labels."""
    # Perfect agreement
    labels_a = ["A", "B", "A", "B", "C"]
    labels_b = ["A", "B", "A", "B", "C"]
    res = compute_cohens_kappa(labels_a, labels_b)
    assert res["raw_agreement"] == 1.0
    assert res["kappa"] == 1.0

    # Disagreement
    labels_c = ["A", "B", "A", "B", "B"]
    res_dis = compute_cohens_kappa(labels_a, labels_c)
    assert res_dis["raw_agreement"] == 0.8
    assert res_dis["kappa"] < 1.0

    # Mismatched lengths
    assert compute_cohens_kappa(["A"], ["A", "B"]) == {"raw_agreement": 0.0, "kappa": 0.0}


def test_labeller_agreement_missing_labels_b_skips_gracefully():
    """Validates that when LABELS_B is None, agreement analysis reports graceful skip."""
    truth_map = {"UNIT-0001": "SKU-A:1"}
    res = compute_labeller_agreement(truth_map, None)
    assert res["provided"] is False
    assert "skipped gracefully" in res["message"]
    assert res["raw_agreement"] is None
    assert res["kappa"] is None
    assert res["disagreements"] == []


def test_labeller_agreement_with_labels_b_disagreements():
    """Validates agreement computation and disagreement reporting between Labeller A and B."""
    lab_a = {
        "UNIT-0001": "SKU-A:1;SKU-B:2",
        "UNIT-0002": "SKU-A:1",
        "UNIT-0003": "SKU-C:1"
    }
    lab_b = {
        "UNIT-0001": "SKU-B:2;SKU-A:1",  # Same, different order
        "UNIT-0002": "SKU-A:2",          # Disagreement on count
        "UNIT-0003": "SKU-C:1"           # Same
    }
    res = compute_labeller_agreement(lab_a, lab_b)
    assert res["provided"] is True
    assert res["total_compared"] == 3
    assert res["agreed_count"] == 2
    assert round(res["raw_agreement"], 4) == round(2 / 3, 4)
    assert len(res["disagreements"]) == 1
    assert res["disagreements"][0]["unit_id"] == "UNIT-0002"


# =============================================================================
# 3. Main Table & Hard Table Metric Mathematics (Synthetic Fixtures)
# =============================================================================

def test_full_eval_metrics_synthetic_suite():
    """Validates metrics calculations on a synthetic 18-box suite matching dev structure."""
    synthetic_results = [
        # 5 Clear Correct (SEAL -> TN)
        {"unit_id": "SYNTH-0001", "failure_type": "correct", "ground_truth_verdict": "SEAL", "predicted_verdict": "SEAL", "status": "completed", "latency_ms": 3200, "checks": {"all_items_present": {"result": "PASS"}, "quantities_correct": {"result": "PASS"}, "nothing_extra": {"result": "PASS"}}, "ground_truth_checks": {"all_items_present": "PASS", "quantities_correct": "PASS", "nothing_extra": "PASS"}},
        {"unit_id": "SYNTH-0002", "failure_type": "correct", "ground_truth_verdict": "SEAL", "predicted_verdict": "SEAL", "status": "completed", "latency_ms": 3100, "checks": {"all_items_present": {"result": "PASS"}, "quantities_correct": {"result": "PASS"}, "nothing_extra": {"result": "PASS"}}, "ground_truth_checks": {"all_items_present": "PASS", "quantities_correct": "PASS", "nothing_extra": "PASS"}},
        {"unit_id": "SYNTH-0003", "failure_type": "correct", "ground_truth_verdict": "SEAL", "predicted_verdict": "SEAL", "status": "completed", "latency_ms": 3300, "checks": {"all_items_present": {"result": "PASS"}, "quantities_correct": {"result": "PASS"}, "nothing_extra": {"result": "PASS"}}, "ground_truth_checks": {"all_items_present": "PASS", "quantities_correct": "PASS", "nothing_extra": "PASS"}},
        {"unit_id": "SYNTH-0004", "failure_type": "correct", "ground_truth_verdict": "SEAL", "predicted_verdict": "SEAL", "status": "completed", "latency_ms": 3400, "checks": {"all_items_present": {"result": "PASS"}, "quantities_correct": {"result": "PASS"}, "nothing_extra": {"result": "PASS"}}, "ground_truth_checks": {"all_items_present": "PASS", "quantities_correct": "PASS", "nothing_extra": "PASS"}},
        {"unit_id": "SYNTH-0005", "failure_type": "correct", "ground_truth_verdict": "SEAL", "predicted_verdict": "SEAL", "status": "completed", "latency_ms": 3500, "checks": {"all_items_present": {"result": "PASS"}, "quantities_correct": {"result": "PASS"}, "nothing_extra": {"result": "PASS"}}, "ground_truth_checks": {"all_items_present": "PASS", "quantities_correct": "PASS", "nothing_extra": "PASS"}},

        # 3 Missing (STOP_AND_FIX -> TP)
        {"unit_id": "SYNTH-0006", "failure_type": "missing", "ground_truth_verdict": "STOP_AND_FIX", "predicted_verdict": "STOP_AND_FIX", "status": "completed", "latency_ms": 3600, "checks": {"all_items_present": {"result": "FAIL", "reason_code": "MISSING_ITEMS"}, "quantities_correct": {"result": "PASS"}, "nothing_extra": {"result": "PASS"}}, "ground_truth_checks": {"all_items_present": "FAIL", "quantities_correct": "PASS", "nothing_extra": "PASS"}},
        {"unit_id": "SYNTH-0007", "failure_type": "missing", "ground_truth_verdict": "STOP_AND_FIX", "predicted_verdict": "STOP_AND_FIX", "status": "completed", "latency_ms": 3700, "checks": {"all_items_present": {"result": "FAIL", "reason_code": "MISSING_ITEMS"}, "quantities_correct": {"result": "PASS"}, "nothing_extra": {"result": "PASS"}}, "ground_truth_checks": {"all_items_present": "FAIL", "quantities_correct": "PASS", "nothing_extra": "PASS"}},
        {"unit_id": "SYNTH-0008", "failure_type": "missing", "ground_truth_verdict": "STOP_AND_FIX", "predicted_verdict": "STOP_AND_FIX", "status": "completed", "latency_ms": 3800, "checks": {"all_items_present": {"result": "FAIL", "reason_code": "MISSING_ITEMS"}, "quantities_correct": {"result": "PASS"}, "nothing_extra": {"result": "PASS"}}, "ground_truth_checks": {"all_items_present": "FAIL", "quantities_correct": "PASS", "nothing_extra": "PASS"}},

        # 3 Short Quantity (STOP_AND_FIX -> TP)
        {"unit_id": "SYNTH-0009", "failure_type": "short_quantity", "ground_truth_verdict": "STOP_AND_FIX", "predicted_verdict": "STOP_AND_FIX", "status": "completed", "latency_ms": 3900, "checks": {"all_items_present": {"result": "PASS"}, "quantities_correct": {"result": "FAIL", "reason_code": "SHORT_QUANTITY"}, "nothing_extra": {"result": "PASS"}}, "ground_truth_checks": {"all_items_present": "PASS", "quantities_correct": "FAIL", "nothing_extra": "PASS"}},
        {"unit_id": "SYNTH-0010", "failure_type": "short_quantity", "ground_truth_verdict": "STOP_AND_FIX", "predicted_verdict": "STOP_AND_FIX", "status": "completed", "latency_ms": 4000, "checks": {"all_items_present": {"result": "PASS"}, "quantities_correct": {"result": "FAIL", "reason_code": "SHORT_QUANTITY"}, "nothing_extra": {"result": "PASS"}}, "ground_truth_checks": {"all_items_present": "PASS", "quantities_correct": "FAIL", "nothing_extra": "PASS"}},
        {"unit_id": "SYNTH-0011", "failure_type": "short_quantity", "ground_truth_verdict": "STOP_AND_FIX", "predicted_verdict": "STOP_AND_FIX", "status": "completed", "latency_ms": 4100, "checks": {"all_items_present": {"result": "PASS"}, "quantities_correct": {"result": "FAIL", "reason_code": "SURPLUS_QUANTITY"}, "nothing_extra": {"result": "PASS"}}, "ground_truth_checks": {"all_items_present": "PASS", "quantities_correct": "FAIL", "nothing_extra": "PASS"}},

        # 2 Extra (STOP_AND_FIX -> TP)
        {"unit_id": "SYNTH-0012", "failure_type": "extra", "ground_truth_verdict": "STOP_AND_FIX", "predicted_verdict": "STOP_AND_FIX", "status": "completed", "latency_ms": 4200, "checks": {"all_items_present": {"result": "PASS"}, "quantities_correct": {"result": "PASS"}, "nothing_extra": {"result": "FAIL", "reason_code": "EXTRA_ITEMS"}}, "ground_truth_checks": {"all_items_present": "PASS", "quantities_correct": "PASS", "nothing_extra": "FAIL"}},
        {"unit_id": "SYNTH-0013", "failure_type": "extra", "ground_truth_verdict": "STOP_AND_FIX", "predicted_verdict": "STOP_AND_FIX", "status": "completed", "latency_ms": 4300, "checks": {"all_items_present": {"result": "PASS"}, "quantities_correct": {"result": "PASS"}, "nothing_extra": {"result": "FAIL", "reason_code": "EXTRA_ITEMS"}}, "ground_truth_checks": {"all_items_present": "PASS", "quantities_correct": "PASS", "nothing_extra": "FAIL"}},

        # 2 Wrong Item (STOP_AND_FIX -> TP)
        {"unit_id": "SYNTH-0014", "failure_type": "wrong_item", "ground_truth_verdict": "STOP_AND_FIX", "predicted_verdict": "STOP_AND_FIX", "status": "completed", "latency_ms": 4400, "checks": {"all_items_present": {"result": "FAIL", "reason_code": "MISSING_ITEMS"}, "quantities_correct": {"result": "PASS"}, "nothing_extra": {"result": "FAIL", "reason_code": "EXTRA_ITEMS"}}, "ground_truth_checks": {"all_items_present": "FAIL", "quantities_correct": "PASS", "nothing_extra": "FAIL"}},
        {"unit_id": "SYNTH-0015", "failure_type": "wrong_item", "ground_truth_verdict": "STOP_AND_FIX", "predicted_verdict": "STOP_AND_FIX", "status": "completed", "latency_ms": 4500, "checks": {"all_items_present": {"result": "FAIL", "reason_code": "MISSING_ITEMS"}, "quantities_correct": {"result": "PASS"}, "nothing_extra": {"result": "FAIL", "reason_code": "EXTRA_ITEMS"}}, "ground_truth_checks": {"all_items_present": "FAIL", "quantities_correct": "PASS", "nothing_extra": "FAIL"}},

        # 3 Hard Boxes (Kept out of main table FP/FN)
        # SYNTH-0016: bad_photo (blur -> UNCERTAIN)
        {"unit_id": "SYNTH-0016", "failure_type": "bad_photo", "subtype": "blur", "ground_truth_verdict": "UNCERTAIN", "predicted_verdict": "UNCERTAIN", "status": "completed", "latency_ms": 4600, "checks": {"all_items_present": {"result": "UNCERTAIN", "cause": "recognition"}, "quantities_correct": {"result": "UNCERTAIN", "cause": "recognition"}, "nothing_extra": {"result": "UNCERTAIN", "cause": "recognition"}}, "ground_truth_checks": {"all_items_present": "PASS", "quantities_correct": "PASS", "nothing_extra": "PASS"}},
        # SYNTH-0017: occluded_hidden (item hidden -> model stopped on missing item, false stop)
        {"unit_id": "SYNTH-0017", "failure_type": "occluded_hidden", "ground_truth_verdict": "UNCERTAIN", "predicted_verdict": "STOP_AND_FIX", "status": "completed", "latency_ms": 4700, "checks": {"all_items_present": {"result": "FAIL", "reason_code": "MISSING_ITEMS"}, "quantities_correct": {"result": "PASS"}, "nothing_extra": {"result": "PASS"}}, "ground_truth_checks": {"all_items_present": "PASS", "quantities_correct": "PASS", "nothing_extra": "PASS"}},
        # SYNTH-0018: occluded_absent (item absent -> model stopped on missing item, safe stop)
        {"unit_id": "SYNTH-0018", "failure_type": "occluded_absent", "ground_truth_verdict": "UNCERTAIN", "predicted_verdict": "STOP_AND_FIX", "status": "completed", "latency_ms": 4800, "checks": {"all_items_present": {"result": "FAIL", "reason_code": "MISSING_ITEMS"}, "quantities_correct": {"result": "PASS"}, "nothing_extra": {"result": "PASS"}}, "ground_truth_checks": {"all_items_present": "FAIL", "quantities_correct": "PASS", "nothing_extra": "PASS"}},
    ]

    metrics = compute_eval_metrics(synthetic_results)

    # 1. Main Table Checks (15 Clear Units)
    main_tbl = metrics["main_table"]
    assert main_tbl["total_clear"] == 15
    assert main_tbl["decided_clear"] == 15
    assert main_tbl["tp"] == 10  # 10 defects stopped
    assert main_tbl["tn"] == 5   # 5 clean sealed
    assert main_tbl["fp"] == 0   # 0 clean stopped
    assert main_tbl["fn"] == 0   # 0 defects escaped
    assert main_tbl["accuracy"] == 1.0
    assert main_tbl["coverage"] == 1.0
    assert main_tbl["fn_rate"] == 0.0
    assert main_tbl["fp_rate"] == 0.0
    # Wilson CIs
    assert main_tbl["accuracy_ci"][0] > 0.75
    assert main_tbl["fn_ci"][0] == 0.0
    assert main_tbl["fp_ci"][0] == 0.0

    # 2. Hard Table Checks (3 Hard Units)
    hard_tbl = metrics["hard_table"]
    assert hard_tbl["total_hard"] == 3
    assert hard_tbl["uncertain_count"] == 1  # SYNTH-0016
    assert hard_tbl["uncertain_recall_raw"] == "1 of 3"
    assert round(hard_tbl["uncertain_recall_rate"], 3) == 0.333
    assert len(hard_tbl["boxes"]) == 3

    # Confirm hard boxes did NOT leak into main table
    assert main_tbl["total_clear"] == 15
    assert main_tbl["tp"] == 10  # Not 11 or 12

    # 3. Per-Check Totals Match 18 Cartons Exactly
    for cname in ("all_items_present", "quantities_correct", "nothing_extra"):
        chk = metrics["check_metrics"][cname]
        assert chk["confirmed_total_matches"] is True
        assert chk["total"] == 18

    # Check exact counts on all_items_present:
    # TP: 3 missing + 2 wrong_item + 1 occluded_absent = 6
    # FP: 1 occluded_hidden = 1 (in synthetic suite, SYNTH-0017 has gt=PASS, pred=FAIL)
    # TN: 5 correct + 3 short + 2 extra = 10
    # Uncertain: 1 bad_photo = 1
    # Total: 6 + 1 + 0 + 10 + 1 + 0 = 18!
    assert metrics["check_metrics"]["all_items_present"]["tp"] == 6
    assert metrics["check_metrics"]["all_items_present"]["fp"] == 1
    assert metrics["check_metrics"]["all_items_present"]["tn"] == 10
    assert metrics["check_metrics"]["all_items_present"]["uncertain_count"] == 1

    # 4. Operational Rates & Targets
    rates = metrics["operational_rates"]
    assert rates["uncertain_count"] == 1
    assert round(rates["uncertain_rate"], 4) == round(1 / 18, 4)
    assert rates["uncertain_target_status"] == "PASSED (<= 10.0%)"
    assert rates["pending_count"] == 0
    assert rates["pending_rate"] == 0.0
    assert rates["pending_target_status"] == "PASSED (<= 3.0%)"
    assert rates["uncertain_by_cause"]["recognition"] == 1
    assert rates["uncertain_by_cause"]["occlusion"] == 0

    # 5. Latency Percentiles
    lat = metrics["latency_percentiles"]
    assert lat["min"] == 3100.0
    assert lat["max"] == 4800.0
    assert lat["p50"] > 3500.0
    assert lat["timeouts_count"] == 0


# =============================================================================
# 4. Safety Guard Tests
# =============================================================================

def test_safety_guard_rejects_mock_adapter():
    """Safety Guard 1: Verify eval harness strictly rejects mock adapters."""
    mock_adapter = MockVisionAdapter()
    assert mock_adapter.IS_MOCK is True
    with pytest.raises((ValueError, RuntimeError)) as excinfo:
        validate_eval_adapter(mock_adapter)
    assert "refuses to run with mock adapter" in str(excinfo.value)


def test_safety_guard_repeat_eval_dir_warning(tmp_path, capsys):
    """Safety Guard 4: Verify that running twice against the same EVAL_DIR emits audit warning."""
    eval_dir = tmp_path / "sealed_eval_test"
    eval_dir.mkdir()
    history_file = tmp_path / "eval_history.json"

    # First run: records run time without warning
    check_and_update_eval_history(eval_dir, history_file)
    captured = capsys.readouterr()
    assert "WARNING: EVALUATION REPEAT DETECTED" not in captured.out

    # Second run against same directory: emits prominent warning
    check_and_update_eval_history(eval_dir, history_file)
    captured2 = capsys.readouterr()
    assert "WARNING: EVALUATION REPEAT DETECTED" in captured2.out
    assert "held-out evaluation set must NOT be tuned against" in captured2.out


def test_derive_ground_truth_checks_physical_defects():
    """Validates physical mapping to orthogonal checks."""
    assert derive_ground_truth_checks("correct") == {"all_items_present": "PASS", "quantities_correct": "PASS", "nothing_extra": "PASS"}
    assert derive_ground_truth_checks("missing") == {"all_items_present": "FAIL", "quantities_correct": "PASS", "nothing_extra": "PASS"}
    assert derive_ground_truth_checks("short_quantity") == {"all_items_present": "PASS", "quantities_correct": "FAIL", "nothing_extra": "PASS"}
    assert derive_ground_truth_checks("extra") == {"all_items_present": "PASS", "quantities_correct": "PASS", "nothing_extra": "FAIL"}
    assert derive_ground_truth_checks("wrong_item") == {"all_items_present": "FAIL", "quantities_correct": "PASS", "nothing_extra": "FAIL"}
    assert derive_ground_truth_checks("occluded_hidden") == {"all_items_present": "PASS", "quantities_correct": "PASS", "nothing_extra": "PASS"}
    assert derive_ground_truth_checks("occluded_absent") == {"all_items_present": "FAIL", "quantities_correct": "PASS", "nothing_extra": "PASS"}
    assert derive_ground_truth_checks("bad_photo") == {"all_items_present": "PASS", "quantities_correct": "PASS", "nothing_extra": "PASS"}
