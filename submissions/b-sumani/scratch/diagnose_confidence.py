import json
import statistics
from pathlib import Path

files = [
    ("Final Run 1 (temp=0)", Path("submissions/b-sumani/eval/real_dev_results_temp0_run1.json")),
    ("Final Run 2 (temp=0)", Path("submissions/b-sumani/eval/real_dev_results_temp0_run2.json")),
    ("Iteration B", Path("submissions/b-sumani/eval/real_dev_results_iter_b.json")),
]

for label, fpath in files:
    if not fpath.exists():
        continue
    data = json.load(open(fpath, encoding="utf-8"))
    cases = data.get("cases", [])
    
    count_confs = []
    ident_confs = []
    
    # Store per box
    correct_boxes_count_confs = []
    correct_boxes_ident_confs = []
    incorrect_boxes_count_confs = [] # where predicted != ground_truth or hard boxes
    incorrect_boxes_ident_confs = []
    
    # Per-SKU records
    sku_details = []

    for c in cases:
        uid = c["unit_id"]
        pred = c["predicted_verdict"]
        gt = c["ground_truth_verdict"]
        is_correct = (pred == gt)
        obs = c.get("observation") or {}
        items = obs.get("observed_items") or []
        
        for it in items:
            cc = it.get("count_confidence")
            ic = it.get("identity_confidence")
            if cc is not None:
                count_confs.append(cc)
                if is_correct:
                    correct_boxes_count_confs.append(cc)
                else:
                    incorrect_boxes_count_confs.append(cc)
            if ic is not None:
                ident_confs.append(ic)
                if is_correct:
                    correct_boxes_ident_confs.append(ic)
                else:
                    incorrect_boxes_ident_confs.append(ic)
            sku_details.append((uid, it.get("sku"), cc, ic, is_correct, pred, gt))

    print(f"\n=======================================================")
    print(f"Dataset: {label} ({len(cases)} boxes, {len(count_confs)} observed SKU entries)")
    print(f"=======================================================")
    
    print("\n--- COUNT CONFIDENCE ---")
    print(f"Min:    {min(count_confs) if count_confs else 'N/A'}")
    print(f"Median: {statistics.median(count_confs) if count_confs else 'N/A'}")
    print(f"Max:    {max(count_confs) if count_confs else 'N/A'}")
    ge_99_cc = sum(1 for x in count_confs if x >= 0.99)
    print(f">= 0.99 count: {ge_99_cc} / {len(count_confs)} ({ge_99_cc/len(count_confs)*100:.1f}%)")
    values_dist_cc = {}
    for x in count_confs:
        values_dist_cc[x] = values_dist_cc.get(x, 0) + 1
    print(f"Value distribution: {sorted(values_dist_cc.items())}")

    print("\n--- IDENTITY CONFIDENCE ---")
    print(f"Min:    {min(ident_confs) if ident_confs else 'N/A'}")
    print(f"Median: {statistics.median(ident_confs) if ident_confs else 'N/A'}")
    print(f"Max:    {max(ident_confs) if ident_confs else 'N/A'}")
    ge_99_ic = sum(1 for x in ident_confs if x >= 0.99)
    print(f">= 0.99 count: {ge_99_ic} / {len(ident_confs)} ({ge_99_ic/len(ident_confs)*100:.1f}%)")
    values_dist_ic = {}
    for x in ident_confs:
        values_dist_ic[x] = values_dist_ic.get(x, 0) + 1
    print(f"Value distribution: {sorted(values_dist_ic.items())}")

    print("\n--- CORRECT VS INCORRECT / HARD BOXES ---")
    print(f"Correct boxes ({len(correct_boxes_count_confs)} items):")
    print(f"  Count conf min/median/max: {min(correct_boxes_count_confs) if correct_boxes_count_confs else None} / {statistics.median(correct_boxes_count_confs) if correct_boxes_count_confs else None} / {max(correct_boxes_count_confs) if correct_boxes_count_confs else None}")
    print(f"  Ident conf min/median/max: {min(correct_boxes_ident_confs) if correct_boxes_ident_confs else None} / {statistics.median(correct_boxes_ident_confs) if correct_boxes_ident_confs else None} / {max(correct_boxes_ident_confs) if correct_boxes_ident_confs else None}")
    print(f"Incorrect / mismatch boxes ({len(incorrect_boxes_count_confs)} items):")
    print(f"  Count conf min/median/max: {min(incorrect_boxes_count_confs) if incorrect_boxes_count_confs else None} / {statistics.median(incorrect_boxes_count_confs) if incorrect_boxes_count_confs else None} / {max(incorrect_boxes_count_confs) if incorrect_boxes_count_confs else None}")
    print(f"  Ident conf min/median/max: {min(incorrect_boxes_ident_confs) if incorrect_boxes_ident_confs else None} / {statistics.median(incorrect_boxes_ident_confs) if incorrect_boxes_ident_confs else None} / {max(incorrect_boxes_ident_confs) if incorrect_boxes_ident_confs else None}")

    print("\n--- SAMPLE RECORDS (3 records raw vs displayed) ---")
    sample_uids = ["UNIT-0017", "UNIT-0029", "UNIT-0049"]
    for s_uid in sample_uids:
        c_match = [c for c in cases if c["unit_id"] == s_uid]
        if c_match:
            c = c_match[0]
            obs = c.get("observation") or {}
            items = obs.get("observed_items") or []
            print(f"Unit: {s_uid} (Predicted: {c['predicted_verdict']}, Ground Truth: {c['ground_truth_verdict']})")
            for it in items:
                raw_cc = it.get('count_confidence')
                raw_ic = it.get('identity_confidence')
                disp_cc = f"{raw_cc * 100:.0f}%" if raw_cc is not None else "N/A"
                disp_ic = f"{raw_ic * 100:.0f}%" if raw_ic is not None else "N/A"
                print(f"  SKU: {it.get('sku')} | Raw count_conf: {raw_cc} (Displayed: {disp_cc}) | Raw ident_conf: {raw_ic} (Displayed: {disp_ic})")
