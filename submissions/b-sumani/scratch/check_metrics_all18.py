import json

with open('submissions/b-sumani/eval/real_dev_results_temp0_run2.json') as f:
    d = json.load(f)

for chk in ['all_items_present', 'quantities_correct', 'nothing_extra']:
    print(f"=== {chk} ===")
    tp, fp, fn, tn = 0, 0, 0, 0
    uncertain_count = 0
    for c in d['cases']:
        pred = c.get('checks', {}).get(chk, {}).get('result')
        gt = c.get('ground_truth_checks', {}).get(chk)
        uid = c['unit_id']
        ft = c['failure_type']
        
        # If pred is UNCERTAIN
        if pred == 'UNCERTAIN':
            uncertain_count += 1
            continue
            
        # Ground truth mapping:
        # For UNIT-0043 (occluded_hidden): ground truth all_items_present should have been PASS physically (all items packed), but gt was UNCERTAIN.
        # User says: "Include UNIT-0043 (false FAIL, item hidden) and UNIT-0081."
        # If UNIT-0043 is false FAIL, then physically it was PASS, so pred=FAIL means FP!
        # For UNIT-0081 (occluded_absent): item is absent, so physically it is FAIL. Pred=FAIL means TP!
        effective_gt = gt
        if chk == 'all_items_present':
            if uid == 'UNIT-0043':
                effective_gt = 'PASS' # physically complete box, item hidden
            elif uid == 'UNIT-0081':
                effective_gt = 'FAIL' # item absent
                
        if effective_gt == 'FAIL':
            if pred == 'FAIL':
                tp += 1
            else:
                fn += 1
        elif effective_gt == 'PASS':
            if pred == 'FAIL':
                fp += 1
                print(f"  FP in {chk}: {uid} (pred={pred}, gt={gt}, eff_gt={effective_gt})")
            else:
                tn += 1
                
    decided = tp + fp + fn + tn
    total = decided + uncertain_count
    acc = (tp + tn) / decided if decided else 0
    print(f"  Total: {total}, Decided: {decided}, Uncertain: {uncertain_count}")
    print(f"  TP: {tp}, FP: {fp}, FN: {fn}, TN: {tn}")
    print(f"  Accuracy: {acc:.4f} ({tp+tn}/{decided})")
