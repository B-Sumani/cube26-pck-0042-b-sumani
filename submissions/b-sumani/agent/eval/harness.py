"""Evaluation harness for Pack Manager.

Strictly follows context.md Section 8 and Section 14:
- Evaluates box verification against double-labelled ground truth.
- Refuses to run with mock adapter (hard requirement: mock adapters must never produce eval figures).
- Measures per-check and per-box TP/FP/FN/TN, accuracy on decided cases, coverage,
  uncertain rate by cause (occlusion vs recognition), pending rate, latency percentiles,
  and inter-labeller agreement.
- Generates Markdown and JSON reports.
"""

from __future__ import annotations
import os
import csv
import json
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

from agent.models.base import (
    VisionModelAdapter,
    validate_eval_adapter,
    ModelObservation,
    ModelTimeoutError,
    ModelProviderError,
    ModelParsingError,
    PROMPT_VERSION,
)
from agent.rules.evaluator import evaluate_pack_box, parse_order_lines
from agent.rules.config import RulesThresholdConfig, DEFAULT_CONFIG
from agent.eval.metrics import compute_eval_metrics
from agent.eval.report import generate_markdown_report


class EvaluationHarness:
    """Orchestrates model evaluation runs against labelled ground truth datasets."""

    def __init__(
        self,
        adapter: VisionModelAdapter,
        config: Optional[RulesThresholdConfig] = None,
        is_frozen_eval: bool = False,
        is_synthetic: bool = False
    ):
        # Strict guard: refuse mock adapters
        validate_eval_adapter(adapter)
        self.adapter = adapter
        self.config = config or DEFAULT_CONFIG
        self.is_frozen_eval = is_frozen_eval
        self.is_synthetic = is_synthetic

    def run_eval_case(
        self,
        case: Dict[str, Any],
        image_bytes: bytes
    ) -> Dict[str, Any]:
        """Executes a single test case through the one-call vision adapter + deterministic rules layer."""
        unit_id = case.get("unit_id", "UNIT-UNKNOWN")
        order_lines = case.get("order_lines", "")
        order_dict = parse_order_lines(order_lines)
        ordered_skus = list(order_dict.keys())
        cat = getattr(self.adapter, "catalogue", {}) or {}
        ordered_item_names = [
            cat.get(sku, {}).get("title", "").strip() or sku
            for sku in ordered_skus
        ]

        status = "completed"
        verdict = None
        checks = {}
        latency_ms = 0
        observation = None

        try:
            # ONE model call per unit (zero order quantities sent)
            observation, latency_ms = self.adapter.analyze_box(
                image_bytes=image_bytes,
                ordered_item_names=ordered_item_names
            )
            # Deterministic rules evaluation
            checks, verdict, _ = evaluate_pack_box(
                order_lines_str=order_lines,
                observation=observation,
                config=self.config
            )
        except (ModelTimeoutError, ModelProviderError, ModelParsingError, Exception) as err:
            status = "pending"
            verdict = None
            checks = {}
            latency_ms = latency_ms or 0

        # Ground truth checks
        gt_checks_raw = case.get("ground_truth_checks", {})
        if isinstance(gt_checks_raw, str):
            try:
                gt_checks_raw = json.loads(gt_checks_raw)
            except Exception:
                gt_checks_raw = {}

        return {
            "unit_id": unit_id,
            "order_lines": order_lines,
            "predicted_verdict": verdict,
            "ground_truth_verdict": case.get("ground_truth_verdict"),
            "labeller1_verdict": case.get("labeller1_verdict"),
            "labeller2_verdict": case.get("labeller2_verdict"),
            "status": status,
            "latency_ms": latency_ms,
            "checks": checks,
            "ground_truth_checks": gt_checks_raw,
            "defect_type": case.get("defect_type", "none"),
        }

    def run_suite(
        self,
        cases: List[Dict[str, Any]],
        image_loader: Any,
        dataset_name: str = "dev_set",
        output_dir: Optional[str] = None
    ) -> Dict[str, Any]:
        """Runs evaluation across all cases in the suite and generates reports."""
        results: List[Dict[str, Any]] = []

        for case in cases:
            unit_id = case.get("unit_id")
            image_bytes = image_loader(case)
            res = self.run_eval_case(case, image_bytes)
            results.append(res)

        # Compute full metrics
        metrics_summary = compute_eval_metrics(results)
        metrics_summary["model_name"] = getattr(self.adapter, "model_name", "unknown_model")
        metrics_summary["dataset_name"] = dataset_name
        metrics_summary["is_frozen_eval"] = self.is_frozen_eval
        metrics_summary["is_synthetic"] = self.is_synthetic
        metrics_summary["results"] = results

        # Generate reports
        markdown_report = generate_markdown_report(
            eval_data=metrics_summary,
            dataset_name=dataset_name,
            model_name=metrics_summary["model_name"],
            prompt_version=PROMPT_VERSION,
            threshold_config_version=self.config.version,
            is_frozen_eval=self.is_frozen_eval,
            is_synthetic_fixtures=self.is_synthetic
        )

        if output_dir:
            out_path = Path(output_dir)
            out_path.mkdir(parents=True, exist_ok=True)
            report_md_file = out_path / "report.md"
            report_json_file = out_path / "report.json"
            
            report_md_file.write_text(markdown_report, encoding="utf-8")
            report_json_file.write_text(json.dumps(metrics_summary, indent=2), encoding="utf-8")

        return metrics_summary
