"""Real Development Set Evaluation Runner for Pack Manager.

Executes the real 18 dev boxes using the live Gemini Vision adapter:
- Reads units from data/dev_units.txt
- Loads real photographs from IMAGES_DIR (trying .jpeg, .jpg, .png)
- Evaluates each box under its own org_id
- Passes the full seller catalogue (with titles and descriptions)
- Paces requests by 5.0s to respect free-tier rate limits (zero PENDING fail-open)
- Computes per-check metrics, failure breakdown by failure_type, uncertain rate by cause,
  pending rate, and latency p50/p95.
"""

from __future__ import annotations
import os
import csv
import json
import time
import sys
from pathlib import Path
from typing import Dict, Any, List

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

from agent.models.gemini import GeminiVisionAdapter, load_catalogue
from agent.rules.evaluator import evaluate_pack_box
from agent.rules.config import DEFAULT_CONFIG
from agent.eval.metrics import compute_eval_metrics, compute_percentiles


def resolve_image_path(images_dir: Path, photo_stem: str) -> Path:
    """Finds image file trying .jpeg, .jpg, .png extensions."""
    for ext in (".jpeg", ".jpg", ".png"):
        p = images_dir / f"{photo_stem}{ext}"
        if p.exists():
            return p
    raise FileNotFoundError(f"Could not find photo for stem '{photo_stem}' in {images_dir}")


def derive_ground_truth_checks(failure_type: str, subtype: str) -> Dict[str, str]:
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
        # Wrong item means expected item is missing and substituted item is extra
        return {"all_items_present": "FAIL", "quantities_correct": "PASS", "nothing_extra": "FAIL"}
    elif failure_type in ("occluded_hidden", "occluded_absent"):
        return {"all_items_present": "UNCERTAIN", "quantities_correct": "PASS", "nothing_extra": "PASS"}
    elif failure_type == "bad_photo":
        return {"all_items_present": "UNCERTAIN", "quantities_correct": "UNCERTAIN", "nothing_extra": "UNCERTAIN"}
    else:
        return {"all_items_present": "PASS", "quantities_correct": "PASS", "nothing_extra": "PASS"}


def run_real_dev_evaluation(run_tag: str = "iter_a"):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY is not configured in .env.")
        sys.exit(1)

    model_name = os.getenv("MODEL_NAME", "gemini-3.1-flash-lite-preview")
    images_dir = Path(os.getenv("IMAGES_DIR", r"C:\Users\user\Desktop\Pack Manager\images"))
    if not images_dir.exists():
        print(f"ERROR: Images directory not found: {images_dir}")
        sys.exit(1)

    data_dir = BASE_DIR / "data"
    dev_units_file = data_dir / "dev_units.txt"
    inputs_file = data_dir / "dev" / "inputs.csv"
    truth_file = data_dir / "dev" / "truth.csv"
    catalogue_file = data_dir / "catalogue.csv"

    # Load 18 dev unit IDs
    with open(dev_units_file, "r", encoding="utf-8") as f:
        dev_unit_ids = set(line.strip() for line in f if line.strip())

    print(f"Loaded {len(dev_unit_ids)} dev unit IDs from {dev_unit_ids}")

    # Load inputs
    inputs_map = {}
    with open(inputs_file, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["unit_id"] in dev_unit_ids:
                inputs_map[row["unit_id"]] = row

    # Load ground truth
    truth_map = {}
    with open(truth_file, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["unit_id"] in dev_unit_ids:
                truth_map[row["unit_id"]] = row

    # Load catalogue
    catalogue = load_catalogue(catalogue_file)
    candidate_skus = list(catalogue.keys())
    print(f"Loaded {len(candidate_skus)} candidate SKUs from catalogue: {candidate_skus}")

    # Initialize Adapter
    adapter = GeminiVisionAdapter(
        api_key=api_key,
        model_name=model_name,
        catalogue=catalogue,
        total_timeout_budget=35.0
    )
    print(f"\n=======================================================")
    print(f"Starting Real Dev Set Run ({run_tag}) across 18 Boxes")
    print(f"Model: {adapter.model_name}")
    print(f"Images Dir: {images_dir}")
    print(f"=======================================================\n")

    results = []
    sorted_units = sorted(list(dev_unit_ids))

    for idx, unit_id in enumerate(sorted_units, 1):
        inp = inputs_map[unit_id]
        tru = truth_map[unit_id]
        org_id = inp["org_id"]
        order_lines = inp["order_lines"]
        photo_stem = inp["photo_stem"]
        expected_verdict = tru["expected_verdict"]
        failure_type = tru["failure_type"]
        subtype = tru.get("subtype", "")

        img_path = resolve_image_path(images_dir, photo_stem)
        image_bytes = img_path.read_bytes()

        gt_checks = derive_ground_truth_checks(failure_type, subtype)

        print(f"[{idx}/18] Unit: {unit_id} | Org: {org_id} | Type: {failure_type} | Expected: {expected_verdict}")
        
        status = "completed"
        obs = None
        latency_ms = 0
        checks = {}
        predicted_verdict = None
        error_msg = None

        try:
            obs, latency_ms = adapter.analyze_box(image_bytes, candidate_skus)
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
            print(f"   --> FAILED/PENDING: {e}")

        # Summary of checks
        chk_summary = {}
        for cname, cdata in checks.items():
            res = cdata.get("result")
            rc = cdata.get("reason_code")
            chk_summary[cname] = f"{res} ({rc})" if rc else res

        print(f"   Result: {predicted_verdict} (latency: {latency_ms}ms)")
        print(f"   Checks: {chk_summary}")
        if obs:
            print(f"   Observed: {[(it.sku, it.count, it.identity_confidence) for it in obs.observed_items]}")
            if obs.image_quality.issues:
                print(f"   Image Quality Issues: {obs.image_quality.issues}")
            if obs.occlusion_suspected:
                print(f"   Occlusion Suspected: True")

        results.append({
            "unit_id": unit_id,
            "org_id": org_id,
            "order_lines": order_lines,
            "failure_type": failure_type,
            "subtype": subtype,
            "ground_truth_verdict": expected_verdict,
            "ground_truth_checks": gt_checks,
            "predicted_verdict": predicted_verdict,
            "status": status,
            "latency_ms": latency_ms,
            "checks": checks,
            "observation": obs.model_dump() if obs else None,
            "error": error_msg
        })

        # Rate-limiting sleep between requests (free-tier safety)
        if idx < len(sorted_units):
            print("   Pacing delay (7s)...\n")
            time.sleep(7.0)

    # Compute Metrics
    metrics = compute_eval_metrics(results)
    latencies = [r["latency_ms"] for r in results if r["latency_ms"] > 0]
    perc = compute_percentiles(latencies)

    # Breakdown by failure_type
    type_breakdown = {}
    for r in results:
        ft = r["failure_type"]
        if ft not in type_breakdown:
            type_breakdown[ft] = {"total": 0, "correct_verdict": 0, "verdicts": []}
        type_breakdown[ft]["total"] += 1
        pv = r["predicted_verdict"]
        ev = r["ground_truth_verdict"]
        is_match = (pv == ev)
        if is_match:
            type_breakdown[ft]["correct_verdict"] += 1
        type_breakdown[ft]["verdicts"].append((r["unit_id"], ev, pv))

    # Save Results
    eval_dir = BASE_DIR / "eval"
    eval_dir.mkdir(parents=True, exist_ok=True)
    out_file = eval_dir / f"real_dev_results_{run_tag}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "model_name": adapter.model_name,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "total_units": len(results),
            "metrics": metrics,
            "latency": perc,
            "type_breakdown": type_breakdown,
            "cases": results
        }, f, indent=2)

    print(f"\n=======================================================")
    print(f"             REAL DEV RUN SUMMARY                     ")
    print(f"=======================================================")
    print(f"Model Name:              {adapter.model_name}")
    print(f"Total Units:             {len(results)}")
    print(f"Decided Cases:           {metrics['box_metrics']['decided_count']} / {len(results)}")
    print(f"Decided Accuracy:        {metrics['box_metrics']['accuracy'] * 100:.1f}%")
    print(f"Coverage:                {metrics['box_metrics']['coverage'] * 100:.1f}%")
    print(f"Uncertain Rate:          {metrics['box_metrics']['uncertain_rate'] * 100:.1f}% ({metrics['box_metrics']['uncertain_count']} units)")
    print(f"  - Occlusion Cause:     {metrics['box_metrics']['uncertain_by_cause'].get('occlusion', 0)}")
    print(f"  - Recognition Cause:   {metrics['box_metrics']['uncertain_by_cause'].get('recognition', 0)}")
    print(f"Pending Rate:            {metrics['box_metrics']['pending_rate'] * 100:.1f}% ({metrics['box_metrics']['pending_count']} units)")
    print(f"Latency p50:             {perc['p50']} ms")
    print(f"Latency p95:             {perc['p95']} ms")
    print(f"\nConfusion Matrix (Box Level):")
    print(f"  TP (Defect flagged):   {metrics['box_metrics']['tp']}")
    print(f"  TN (Clean sealed):     {metrics['box_metrics']['tn']}")
    print(f"  FP (Clean stopped):    {metrics['box_metrics']['fp']}")
    print(f"  FN (Defect sealed):    {metrics['box_metrics']['fn']}")
    print(f"  FN Rate (Mis-ship):    {metrics['box_metrics']['fn_rate'] * 100:.1f}%")
    print(f"  FP Rate (False alarm): {metrics['box_metrics']['fp_rate'] * 100:.1f}%")

    print(f"\nPer-Check Results:")
    for chk, cm in metrics["check_metrics"].items():
        print(f"  {chk}:")
        print(f"    TP: {cm['tp']}, TN: {cm['tn']}, FP: {cm['fp']}, FN: {cm['fn']}")
        print(f"    Uncertain: {cm['uncertain_count']}, Pending: {cm['pending_count']}")

    print(f"\nFailures Grouped by Physical Failure Type:")
    for ft, data in sorted(type_breakdown.items()):
        acc = data['correct_verdict'] / data['total'] * 100
        print(f"  {ft} (n={data['total']}): {data['correct_verdict']}/{data['total']} matched verdict ({acc:.0f}%)")
        for uid, ev, pv in data['verdicts']:
            status_mark = "OK" if ev == pv else "MISMATCH"
            print(f"    - {uid}: Expected={ev}, Got={pv} [{status_mark}]")

    print(f"\nSaved raw results to: {out_file}")
    print(f"=======================================================\n")
    return results, metrics, perc, type_breakdown


if __name__ == "__main__":
    tag = sys.argv[1] if len(sys.argv) > 1 else "iter_a"
    run_real_dev_evaluation(tag)
