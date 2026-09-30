"""Unit tests for the evaluation harness, metrics, and report generator (v3).

Validates:
1. Strict refusal of mock adapters (hard requirement: mock adapters must never produce eval figures).
2. Per-check and box-level confusion matrix mathematics (TP, FP, FN, TN, rates, coverage, accuracy on decided).
3. First-class operational separation: UNCERTAIN and PENDING never counted as correct or as FP/FN.
4. Inter-labeller agreement and Cohen's Kappa coefficient calculations.
5. Latency percentiles (p50, p95, mean).
6. Markdown and JSON report generator formatting and audit statements.
7. End-to-end dev set harness runner.
"""

import os
import json
import pytest
from pathlib import Path

from agent.models.base import VisionModelAdapter, ModelObservation, ObservedItem, ImageQuality
from agent.models.mock import MockVisionAdapter
from agent.eval.metrics import (
    ConfusionMatrix,
    compute_eval_metrics,
    compute_percentiles,
    compute_cohens_kappa,
)
from agent.eval.report import generate_markdown_report
from agent.eval.harness import EvaluationHarness


class NonMockTestAdapter(VisionModelAdapter):
    """Real non-mock adapter stub for deterministic test validation."""
    IS_MOCK: bool = False
    model_name: str = "gemini-3-flash-preview"

    def analyze_box(self, image_bytes: bytes, candidate_skus: list[str], timeout_seconds: float = None) -> tuple[ModelObservation, int]:
        # Emulates clean observation for unit testing harness mechanics
        obs = ModelObservation(
            observed_items=[
                ObservedItem(
                    sku=candidate_skus[0] if candidate_skus else "SKU-DEFAULT",
                    count=1,
                    count_confidence=0.95,
                    identity_confidence=0.98,
                    partially_occluded=False,
                    bbox=[50.0, 50.0, 200.0, 200.0]
                )
            ],
            unrecognised_items=[],
            image_quality=ImageQuality(usable=True, issues=[]),
            occlusion_suspected=False
        )
        return obs, 85


def test_eval_harness_strictly_refuses_mock_adapter():
    """Hard Rule: The evaluation harness must refuse to run with the mock adapter."""
    mock_adapter = MockVisionAdapter()
    assert mock_adapter.IS_MOCK is True

    with pytest.raises(ValueError) as excinfo:
        EvaluationHarness(adapter=mock_adapter)
    
    assert "refuses to run with mock adapter" in str(excinfo.value)


def test_confusion_matrix_math_and_rates():
    """Validates confusion matrix rates, coverage, and decided accuracy calculations."""
    cm = ConfusionMatrix(
        tp=10,  # 10 defects caught
        fp=2,   # 2 false alarms
        fn=1,   # 1 defect slipped through (mis-ship)
        tn=20,  # 20 clean boxes approved
        uncertain_count=4,
        pending_count=1,
        total=38
    )

    assert cm.decided_count == 33  # 10 + 2 + 1 + 20
    # Decided accuracy: (10 + 20) / 33 = 30 / 33 = 0.9091
    assert round(cm.accuracy, 4) == 0.9091
    # Coverage: 33 / 38 = 0.8684
    assert round(cm.coverage, 4) == 0.8684
    # FN rate: 1 / (1 + 10) = 1 / 11 = 0.0909
    assert round(cm.fn_rate, 4) == 0.0909
    # FP rate: 2 / (2 + 20) = 2 / 22 = 0.0909
    assert round(cm.fp_rate, 4) == 0.0909
    # Uncertain rate: 4 / 38 = 0.1053
    assert round(cm.uncertain_rate, 4) == 0.1053
    # Pending rate: 1 / 38 = 0.0263
    assert round(cm.pending_rate, 4) == 0.0263


def test_metrics_separation_uncertain_and_pending_never_in_fp_fn():
    """Validates Section 14 rule: UNCERTAIN and PENDING never counted as correct or as FP/FN."""
    results = [
        # 1. Clean box approved -> TN
        {"ground_truth_verdict": "SEAL", "predicted_verdict": "SEAL", "status": "completed", "latency_ms": 100},
        # 2. Defective box flagged -> TP
        {"ground_truth_verdict": "STOP_AND_FIX", "predicted_verdict": "STOP_AND_FIX", "status": "completed", "latency_ms": 110},
        # 3. Clean box got UNCERTAIN (should NOT be FP or FN)
        {"ground_truth_verdict": "SEAL", "predicted_verdict": "UNCERTAIN", "status": "completed", "latency_ms": 95},
        # 4. Defective box got UNCERTAIN (should NOT be FP or FN)
        {"ground_truth_verdict": "STOP_AND_FIX", "predicted_verdict": "UNCERTAIN", "status": "completed", "latency_ms": 105},
        # 5. Box timed out -> PENDING (should NOT be FP or FN)
        {"ground_truth_verdict": "STOP_AND_FIX", "predicted_verdict": None, "status": "pending", "latency_ms": 0},
    ]

    metrics = compute_eval_metrics(results)
    box = metrics["box_metrics"]

    assert box["total"] == 5
    assert box["decided_count"] == 2
    assert box["tp"] == 1
    assert box["tn"] == 1
    assert box["fp"] == 0
    assert box["fn"] == 0
    assert box["uncertain_count"] == 2
    assert box["pending_count"] == 1
    assert box["accuracy"] == 1.0  # (1 + 1) / 2
    assert box["coverage"] == 0.4  # 2 / 5


def test_cohens_kappa_calculation():
    """Validates inter-labeller agreement percentage and Cohen's Kappa."""
    # 1. Perfect agreement
    labels1 = ["SEAL", "STOP_AND_FIX", "SEAL", "STOP_AND_FIX"]
    labels2 = ["SEAL", "STOP_AND_FIX", "SEAL", "STOP_AND_FIX"]
    res_perf = compute_cohens_kappa(labels1, labels2)
    assert res_perf["raw_agreement"] == 1.0
    assert res_perf["kappa"] == 1.0

    # 2. Substantial agreement
    labels_a = ["SEAL", "SEAL", "STOP_AND_FIX", "STOP_AND_FIX", "SEAL"]
    labels_b = ["SEAL", "STOP_AND_FIX", "STOP_AND_FIX", "STOP_AND_FIX", "SEAL"]
    res_part = compute_cohens_kappa(labels_a, labels_b)
    assert res_part["raw_agreement"] == 0.8
    assert res_part["kappa"] > 0.5


def test_percentiles_calculation():
    """Validates p50, p95, mean, min, max latency calculations."""
    latencies = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]
    p = compute_percentiles(latencies)
    assert p["min"] == 100.0
    assert p["max"] == 1000.0
    assert p["mean"] == 550.0
    assert p["p50"] == 550.0
    assert p["p95"] == 955.0


def test_markdown_report_formatting_and_targets():
    """Validates markdown report generation contains targets, breakdowns, and audit notes."""
    mock_metrics = {
        "box_metrics": {
            "total": 15,
            "decided_count": 13,
            "tp": 5,
            "tn": 8,
            "fn": 0,
            "fp": 0,
            "accuracy": 1.0,
            "coverage": 0.8667,
            "fn_rate": 0.0,
            "fp_rate": 0.0,
            "uncertain_count": 2,
            "uncertain_rate": 0.1333,
            "uncertain_by_cause": {"occlusion": 1, "recognition": 1},
            "pending_count": 0,
            "pending_rate": 0.0,
        },
        "check_metrics": {
            "all_items_present": {"total": 15, "decided_count": 13, "accuracy": 1.0, "tp": 2, "fp": 0, "fn": 0, "tn": 11, "uncertain_count": 2, "pending_count": 0},
            "quantities_correct": {"total": 15, "decided_count": 14, "accuracy": 1.0, "tp": 2, "fp": 0, "fn": 0, "tn": 12, "uncertain_count": 1, "pending_count": 0},
            "nothing_extra": {"total": 15, "decided_count": 15, "accuracy": 1.0, "tp": 2, "fp": 0, "fn": 0, "tn": 13, "uncertain_count": 0, "pending_count": 0},
        },
        "latency_percentiles": {"p50": 120.0, "p95": 250.0, "mean": 135.0, "min": 80.0, "max": 280.0},
        "labeller_agreement": {"raw_agreement": 0.9333, "kappa": 0.857},
        "total_units": 15
    }

    report_md = generate_markdown_report(
        eval_data=mock_metrics,
        dataset_name="dev_set_15",
        model_name="gemini-3-flash-preview",
        is_frozen_eval=False,
        is_synthetic_fixtures=True
    )

    assert "# Pack Manager Evaluation Report" in report_md
    assert "Uncertain Rate" in report_md
    assert "<= 10.0% (Kill: > 20.0%)" in report_md
    assert "Pending Rate (Fail-Open)" in report_md
    assert "<= 3.0%" in report_md
    assert "Synthetic Fixtures" in report_md
    assert "Single frozen eval run" not in report_md  # Not frozen
    assert "Cohen's Kappa" in report_md
    assert "All Items Present" in report_md
    assert "Quantities Correct" in report_md
    assert "Nothing Extra" in report_md


def test_end_to_end_dev_set_harness_run(tmp_path):
    """Executes harness run over sample dev cases and writes report.md and report.json."""
    adapter = NonMockTestAdapter()
    harness = EvaluationHarness(adapter=adapter, is_frozen_eval=False, is_synthetic=True)

    cases = [
        {
            "unit_id": "UNIT-0001",
            "order_lines": "SKU-BOTTLE-750:1",
            "candidate_skus": ["SKU-BOTTLE-750", "SKU-PUZZLE-500"],
            "ground_truth_verdict": "SEAL",
            "ground_truth_checks": {"all_items_present": "PASS", "quantities_correct": "PASS", "nothing_extra": "PASS"},
            "labeller1_verdict": "SEAL",
            "labeller2_verdict": "SEAL"
        },
        {
            "unit_id": "UNIT-0002",
            "order_lines": "SKU-PUZZLE-500:1",
            "candidate_skus": ["SKU-PUZZLE-500"],
            "ground_truth_verdict": "STOP_AND_FIX",
            "ground_truth_checks": {"all_items_present": "FAIL", "quantities_correct": "PASS", "nothing_extra": "PASS"},
            "labeller1_verdict": "STOP_AND_FIX",
            "labeller2_verdict": "STOP_AND_FIX"
        }
    ]

    def dummy_image_loader(c):
        return b"fake_bytes"

    metrics = harness.run_suite(
        cases=cases,
        image_loader=dummy_image_loader,
        dataset_name="test_dev_set",
        output_dir=str(tmp_path)
    )

    assert metrics["total_units"] == 2
    assert (tmp_path / "report.md").exists()
    assert (tmp_path / "report.json").exists()

    report_text = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "test_dev_set" in report_text
    assert "gemini-3-flash-preview" in report_text
