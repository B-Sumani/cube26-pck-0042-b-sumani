"""CLI script to run the development set evaluation.

Follows context.md Section 11 & 14:
- Runs strictly on the dev set (15 units)
- Uses real vision adapter (Gemini)
- Never runs on mock adapter
- Never touches the frozen 50-unit eval set until owner confirms freeze
- Generates submissions/b-sumani/eval/dev_report.md and dev_report.json
"""

import os
import csv
import sys
from pathlib import Path
from dotenv import load_dotenv

# Ensure root is on python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agent.models.gemini import GeminiVisionAdapter
from agent.eval.harness import EvaluationHarness
from agent.rules.config import DEFAULT_CONFIG

load_dotenv()


def run_dev_evaluation():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY is not configured in .env. Real vision adapter required for evaluation.")
        sys.exit(1)

    model_name = os.getenv("MODEL_NAME", "gemini-3-flash-preview")
    print(f"Initializing GeminiVisionAdapter with model: {model_name}...")
    adapter = GeminiVisionAdapter(api_key=api_key, model_name=model_name)

    data_dir = Path(__file__).parent.parent.parent / "data"
    csv_path = data_dir / "dev_set.csv"
    fixtures_dir = data_dir / "fixtures" / "dev"
    output_dir = Path(__file__).parent.parent.parent / "eval"

    if not csv_path.exists():
        print(f"ERROR: Dev set CSV not found at {csv_path}")
        sys.exit(1)

    # Read cases
    cases = []
    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cases.append(row)

    print(f"Loaded {len(cases)} dev cases from {csv_path}")

    # Image loader function
    def load_image(case_dict):
        unit_id = case_dict["unit_id"]
        img_path = fixtures_dir / f"{unit_id}_open_box.jpg"
        if not img_path.exists():
            raise FileNotFoundError(f"Fixture image missing: {img_path}")
        return img_path.read_bytes()

    # Initialize harness
    harness = EvaluationHarness(
        adapter=adapter,
        config=DEFAULT_CONFIG,
        is_frozen_eval=False,
        is_synthetic=True  # Synthetic fixtures labelled as required by context.md Section 7
    )

    print(f"Starting dev set evaluation across {len(cases)} units...")
    metrics = harness.run_suite(
        cases=cases,
        image_loader=load_image,
        dataset_name="dev_set_15_units",
        output_dir=str(output_dir)
    )

    # Copy report.md -> dev_report.md
    report_md = output_dir / "report.md"
    dev_report_md = output_dir / "dev_report.md"
    dev_report_json = output_dir / "dev_report.json"
    
    if report_md.exists():
        dev_report_md.write_text(report_md.read_text(encoding="utf-8"), encoding="utf-8")
        (output_dir / "report.json").rename(dev_report_json)

    print("\n================ EVALUATION COMPLETE ================")
    print(f"Total Units Evaluated: {metrics['total_units']}")
    print(f"Decided Accuracy:      {metrics['box_metrics']['accuracy'] * 100:.1f}%")
    print(f"Coverage:              {metrics['box_metrics']['coverage'] * 100:.1f}%")
    print(f"Uncertain Rate:        {metrics['box_metrics']['uncertain_rate'] * 100:.1f}%")
    print(f"Pending Rate:          {metrics['box_metrics']['pending_rate'] * 100:.1f}%")
    print(f"Median Latency (p50):  {metrics['latency_percentiles']['p50']} ms")
    print(f"95th Latency (p95):    {metrics['latency_percentiles']['p95']} ms")
    print(f"Report saved to:       {dev_report_md}")
    print("=====================================================")


if __name__ == "__main__":
    run_dev_evaluation()
