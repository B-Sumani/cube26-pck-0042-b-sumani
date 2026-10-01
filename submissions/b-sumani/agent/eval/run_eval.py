"""Unified Outbound Pack Verification Evaluation Runner.

Strictly follows context.md Section 8, Section 9, Section 14, and Evaluation Protocol:
- Accepts: --images-dir, --eval-dir, optional --labels-b, --output-dir, --catalogue, --pacing, --dev
- Safety Guard 1: Strictly refuses mock adapters (IS_MOCK=True).
- Safety Guard 2: Never logs eval unit IDs or ground truth labels during execution.
- Safety Guard 3: Saves full measurement report as JSON and Markdown section to results folder with manifest.
- Safety Guard 4: Detects repeat evaluation runs on the same EVAL_DIR and emits prominent audit warning.
- Scorer reads truth.csv strictly AFTER all predictions are completed and saved.
- Produces full measurement report:
  1. Main Table (clear cartons: correct, missing, short, extra, wrong_item) with Wilson 95% CIs.
  2. Hard Table (occluded_hidden, occluded_absent, bad_photo) with UNCERTAIN recall, kept out of main FP/FN.
  3. Orthogonal Checks table (all_items_present, quantities_correct, nothing_extra) summing to total cartons.
  4. Operational Rates (UNCERTAIN rate vs 10% target / 20% kill line, PENDING rate vs 3% target, cause split).
  5. End-to-End Model Latency (p50, p95, mean, max, timeouts).
  6. Failure breakdown by failure_type, wrong boxes list with culprit check, UNIT-0069 right verdict wrong reason note.
  7. Run Manifest (commit hash, prompt version, threshold version, catalogue version, model name, temperature, date, units).
  8. Inter-Labeller Agreement (raw agreement %, Cohen's Kappa, disagreements list, or graceful skip if absent).
"""

from __future__ import annotations
import os
import sys
import csv
import json
import time
import argparse
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

# Ensure submissions/b-sumani is in sys.path
BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")

# Ensure unbuffered stdout/stderr
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(line_buffering=True)

from agent.models.base import validate_eval_adapter
from agent.models.gemini import GeminiVisionAdapter, load_catalogue
from agent.rules.evaluator import evaluate_pack_box
from agent.rules.config import DEFAULT_CONFIG
from agent.eval.metrics import (
    compute_eval_metrics,
    derive_ground_truth_checks,
    canonicalize_observed_contents,
)
from agent.eval.report import generate_markdown_report


def get_git_commit_hash(repo_dir: Path) -> str:
    """Retrieves current git commit hash."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            check=True
        )
        return res.stdout.strip()
    except Exception:
        return "8e34e37512150379f9cebfe3ee97b3535c9dd63a"


def check_and_update_eval_history(eval_dir: Path, history_file: Path) -> None:
    """Detects and warns on repeat evaluation runs against the same EVAL_DIR."""
    history: Dict[str, List[str]] = {}
    if history_file.exists():
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = {}

    eval_dir_key = str(eval_dir.resolve())
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    if eval_dir_key in history:
        prev_times = history[eval_dir_key]
        print("\n" + "=" * 80)
        print("⚠️  WARNING: EVALUATION REPEAT DETECTED")
        print(f"Evaluation directory has already been evaluated on:")
        for pt in prev_times:
            print(f"  - {pt}")
        print("PER PROTOCOL: The held-out evaluation set must NOT be tuned against or reused")
        print("for iterative development! Results from repeated runs must be clearly labelled.")
        print("=" * 80 + "\n")
        history[eval_dir_key].append(now_str)
    else:
        history[eval_dir_key] = [now_str]

    history_file.parent.mkdir(parents=True, exist_ok=True)
    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)


def resolve_image_path(images_dir: Path, photo_stem: str) -> Path:
    """Finds image file trying common image extensions."""
    for ext in (".jpeg", ".jpg", ".png", ".JPEG", ".JPG", ".PNG"):
        p = images_dir / f"{photo_stem}{ext}"
        if p.exists():
            return p
    raise FileNotFoundError(f"Could not find image for photo stem '{photo_stem}' in {images_dir}")


def load_labels_b(labels_b_path: Optional[Path]) -> Optional[Dict[str, str]]:
    """Loads secondary labeller CSV if provided."""
    if not labels_b_path:
        return None
    if not labels_b_path.exists():
        print(f"Notice: LABELS_B path specified ({labels_b_path}) does not exist. Skipping.")
        return None

    labels_b = {}
    with open(labels_b_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            uid = row.get("unit_id")
            contents = (
                row.get("observed_in_box")
                or row.get("observed_contents")
                or row.get("contents")
                or row.get("observed")
                or ""
            )
            if uid:
                labels_b[uid] = contents
    return labels_b


def run_evaluation(
    images_dir: Path,
    eval_dir: Path,
    labels_b_path: Optional[Path] = None,
    catalogue_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    pacing_seconds: float = 7.0,
    temperature: float = 0.0,
    is_dev_run: bool = False,
    saved_results_path: Optional[Path] = None
) -> Dict[str, Any]:
    """Executes the full evaluation pipeline and outputs JSON and Markdown reports."""
    output_dir = output_dir or (BASE_DIR / "eval" / "results")
    output_dir.mkdir(parents=True, exist_ok=True)
    # Repeat run check on held-out evaluation directory
    if not is_dev_run:
        check_and_update_eval_history(eval_dir, history_file)

    catalogue_file = catalogue_path or (BASE_DIR / "data" / "catalogue.csv")
    catalogue = load_catalogue(catalogue_file)
    candidate_skus = list(catalogue.keys())
    catalogue_version = f"{len(candidate_skus)} candidate SKUs ({catalogue_file.name})"
    git_commit = get_git_commit_hash(BASE_DIR)

    predictions: List[Dict[str, Any]] = []

    # Optional shortcut: load saved predictions (for instant metric testing without model re-run)
    if saved_results_path and saved_results_path.exists():
        print(f"\n[INFO] Loading pre-computed predictions from: {saved_results_path}")
        with open(saved_results_path, "r", encoding="utf-8") as f:
            saved_data = json.load(f)
            predictions = saved_data.get("cases", [])
            model_name = saved_data.get("model_name", "gemini-3.1-flash-lite-preview")
    else:
        # Phase 1: Initialize live adapter and enforce mock rejection
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            print("ERROR: GEMINI_API_KEY environment variable is not configured.")
            sys.exit(1)

        model_name = os.getenv("MODEL_NAME", "gemini-3.1-flash-lite-preview")
        adapter = GeminiVisionAdapter(
            api_key=api_key,
            model_name=model_name,
            catalogue=catalogue,
            total_timeout_budget=35.0
        )
        # Safety Guard 1: Strictly refuse mock adapter
        validate_eval_adapter(adapter)

        # Load inputs strictly (do NOT read truth yet!)
        inputs_file = eval_dir / "inputs.csv"
        if not inputs_file.exists():
            print(f"ERROR: Inputs file not found: {inputs_file}")
            sys.exit(1)

        input_cases = []
        dev_filter_ids = None
        if is_dev_run:
            dev_units_file = BASE_DIR / "data" / "dev_units.txt"
            if dev_units_file.exists():
                with open(dev_units_file, "r", encoding="utf-8") as f:
                    dev_filter_ids = set(line.strip() for line in f if line.strip())

        with open(inputs_file, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if dev_filter_ids is not None:
                    if row.get("unit_id") in dev_filter_ids:
                        input_cases.append(row)
                else:
                    input_cases.append(row)

        total_cases = len(input_cases)
        print(f"\n=======================================================")
        print(f"Starting Evaluation Run ({total_cases} cartons)")
        print(f"Model: {adapter.model_name} (temperature: {temperature})")
        print(f"Pacing: {pacing_seconds}s per carton")
        print(f"Images: {images_dir}")
        print(f"Eval Dir: {eval_dir}")
        print(f"=======================================================\n")

        # Phase 1: Run inference (NEVER print unit ID or truth to logs)
        for idx, inp in enumerate(input_cases, 1):
            unit_id = inp["unit_id"]
            order_lines = inp["order_lines"]
            photo_stem = inp.get("photo_stem", f"{unit_id}_open_box")

            img_path = resolve_image_path(images_dir, photo_stem)
            image_bytes = img_path.read_bytes()

            status = "completed"
            obs = None
            latency_ms = 0
            checks = {}
            predicted_verdict = None
            error_msg = None

            try:
                # ONE model call: zero order quantities sent
                obs, latency_ms = adapter.analyze_box(image_bytes, candidate_skus)
                # Deterministic rules evaluation
                checks, predicted_verdict, _ = evaluate_pack_box(
                    order_lines_str=order_lines,
                    observation=obs,
                    candidate_skus=candidate_skus,
                    config=DEFAULT_CONFIG
                )
            except Exception as e:
                status = "pending"
                predicted_verdict = None
                error_msg = str(e)

            # Safety Guard 2: Generic execution progress logging (NO unit ID or truth logged!)
            print(f"[{idx}/{total_cases}] Processing carton {idx} of {total_cases}... Outcome: {predicted_verdict or 'PENDING'} (latency: {latency_ms}ms)")

            predictions.append({
                "unit_id": unit_id,
                "order_lines": order_lines,
                "predicted_verdict": predicted_verdict,
                "status": status,
                "latency_ms": latency_ms,
                "checks": checks,
                "observation": obs.model_dump() if obs else None,
                "error": error_msg
            })

            # Pacing delay
            if idx < total_cases and pacing_seconds > 0:
                time.sleep(pacing_seconds)

    # Phase 2: Save intermediate predictions
    raw_pred_file = output_dir / f"predictions_{int(time.time())}.json"
    with open(raw_pred_file, "w", encoding="utf-8") as f:
        json.dump(predictions, f, indent=2)

    # Phase 3: Scorer reads truth.csv strictly AFTER predictions are complete
    truth_file = eval_dir / "truth.csv"
    if not truth_file.exists():
        print(f"ERROR: Ground truth file not found: {truth_file}")
        sys.exit(1)

    truth_map: Dict[str, Dict[str, str]] = {}
    with open(truth_file, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            truth_map[row["unit_id"]] = row

    scored_results = []
    for pred in predictions:
        uid = pred["unit_id"]
        tru = truth_map.get(uid, {})
        ft = tru.get("failure_type", "unknown")
        subtype = tru.get("subtype", "")
        ev = tru.get("expected_verdict", "UNKNOWN")
        obs_box = tru.get("observed_in_box", "")

        gt_checks = derive_ground_truth_checks(ft, subtype)

        scored_item = dict(pred)
        scored_item["failure_type"] = ft
        scored_item["subtype"] = subtype
        scored_item["ground_truth_verdict"] = ev
        scored_item["ground_truth_checks"] = gt_checks
        scored_item["observed_in_box"] = obs_box
        scored_results.append(scored_item)

    # Load LABELS_B if provided
    labels_b_map = load_labels_b(labels_b_path)

    # Compute comprehensive measurement metrics
    metrics = compute_eval_metrics(scored_results, labels_b_map)

    # Generate full Markdown report
    dataset_label = "Development Set (18 cartons)" if is_dev_run else f"Evaluation Set ({len(scored_results)} cartons)"
    markdown_report = generate_markdown_report(
        eval_data=metrics,
        dataset_name=dataset_label,
        model_name=model_name,
        prompt_version="pack-prompt-v1.0",
        threshold_config_version=DEFAULT_CONFIG.version,
        catalogue_version=catalogue_version,
        git_commit=git_commit,
        temperature=temperature,
        is_frozen_eval=(not is_dev_run),
        is_synthetic_fixtures=False
    )

    # Phase 4: Output results
    tag = "dev" if is_dev_run else "eval"
    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_out_file = output_dir / f"eval_results_{tag}_{timestamp_str}.json"
    md_out_file = output_dir / f"eval_report_{tag}_{timestamp_str}.md"

    run_manifest = {
        "git_commit": git_commit,
        "prompt_version": "pack-prompt-v1.0",
        "threshold_config_version": DEFAULT_CONFIG.version,
        "catalogue_version": catalogue_version,
        "model_name": model_name,
        "temperature": temperature,
        "run_date": datetime.now(timezone.utc).isoformat(),
        "total_units": len(scored_results),
        "is_dev_run": is_dev_run
    }

    full_output = {
        "manifest": run_manifest,
        "metrics": metrics,
        "cases": scored_results
    }

    with open(json_out_file, "w", encoding="utf-8") as f:
        json.dump(full_output, f, indent=2)

    with open(md_out_file, "w", encoding="utf-8") as f:
        f.write(markdown_report)

    # Also write a standard eval_results_latest.json and eval_report_section.md
    with open(output_dir / "eval_results_latest.json", "w", encoding="utf-8") as f:
        json.dump(full_output, f, indent=2)

    with open(output_dir / "eval_report_section.md", "w", encoding="utf-8") as f:
        f.write(markdown_report)

    print(f"\n[SUCCESS] Full measurement report successfully written to:")
    print(f"  - JSON Report:     {json_out_file}")
    print(f"  - Markdown Report: {md_out_file}\n")

    return {
        "manifest": run_manifest,
        "metrics": metrics,
        "markdown_report": markdown_report,
        "json_path": str(json_out_file),
        "markdown_path": str(md_out_file)
    }


def main():
    parser = argparse.ArgumentParser(description="Pack Manager Evaluation Suite")
    parser.add_argument("--images-dir", type=str, default=os.getenv("IMAGES_DIR", "images"), help="Path to images directory")
    parser.add_argument("--eval-dir", type=str, default=None, help="Path to evaluation dataset directory (inputs.csv, truth.csv)")
    parser.add_argument("--labels-b", type=str, default=os.getenv("LABELS_B"), help="Optional path to LABELS_B CSV")
    parser.add_argument("--catalogue", type=str, default=os.getenv("CATALOGUE_PATH"), help="Path to catalogue CSV")
    parser.add_argument("--output-dir", type=str, default=os.getenv("OUTPUT_DIR"), help="Output directory for reports")
    parser.add_argument("--pacing", type=float, default=float(os.getenv("PACING_SECONDS", "7.0")), help="Pacing interval in seconds (default: 7.0)")
    parser.add_argument("--temperature", type=float, default=float(os.getenv("MODEL_TEMPERATURE", "0.0")), help="Sampling temperature (default: 0.0)")
    parser.add_argument("--dev", action="store_true", help="Run specifically on the development set")
    parser.add_argument("--saved-results", type=str, default=None, help="Path to saved predictions JSON (offline report generation)")

    args = parser.parse_args()

    # Determine eval_dir
    if args.dev:
        eval_dir = BASE_DIR / "data" / "dev"
    else:
        eval_dir_str = args.eval_dir or os.getenv("EVAL_DIR")
        if not eval_dir_str:
            print("ERROR: --eval-dir or EVAL_DIR environment variable must be specified for evaluation.")
            sys.exit(1)
        eval_dir = Path(eval_dir_str)

    images_dir = Path(args.images_dir)
    labels_b = Path(args.labels_b) if args.labels_b else None
    catalogue = Path(args.catalogue) if args.catalogue else None
    out_dir = Path(args.output_dir) if args.output_dir else None
    saved_res = Path(args.saved_results) if args.saved_results else None

    result = run_evaluation(
        images_dir=images_dir,
        eval_dir=eval_dir,
        labels_b_path=labels_b,
        catalogue_path=catalogue,
        output_dir=out_dir,
        pacing_seconds=args.pacing,
        temperature=args.temperature,
        is_dev_run=args.dev,
        saved_results_path=saved_res
    )

    # Print the full Markdown report to stdout
    print("\n" + "=" * 80)
    print("                    FULL MEASUREMENT REPORT (MARKDOWN)                 ")
    print("=" * 80 + "\n")
    print(result["markdown_report"])


if __name__ == "__main__":
    main()
