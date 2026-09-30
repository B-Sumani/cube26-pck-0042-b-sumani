import json
from pathlib import Path

eval_dir = Path("submissions/b-sumani/eval")
for fname in ["real_dev_results.json", "real_dev_results_iter_a.json"]:
    fpath = eval_dir / fname
    if not fpath.exists():
        continue
    data = json.loads(fpath.read_text(encoding="utf-8"))
    print("=" * 10, fname, "=" * 10)
    for c in data["cases"]:
        obs = c.get("observation") or {}
        iq = obs.get("image_quality") or {}
        occ = obs.get("occlusion_suspected", False)
        issues = iq.get("issues", [])
        usable = iq.get("usable", True)
        uid = c["unit_id"]
        ft = c["failure_type"]
        pv = c["predicted_verdict"]
        ev = c["ground_truth_verdict"]
        print(f"{uid} ({ft:15s}): Expected={ev:12s} Predicted={str(pv):12s} Usable={usable} Issues={issues} Occ={occ}")
