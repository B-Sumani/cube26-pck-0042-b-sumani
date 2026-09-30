import json

with open('submissions/b-sumani/eval/real_dev_results_temp0_run2.json') as f:
    d = json.load(f)

print("=== CHECK DISCREPANCIES ===")
for c in d['cases']:
    for chk in ['all_items_present', 'quantities_correct', 'nothing_extra']:
        pred = c.get('checks', {}).get(chk, {}).get('result')
        gt = c.get('ground_truth_checks', {}).get(chk)
        if pred != gt:
            print(f"{c['unit_id']} [{chk}]: pred={pred} (code={c.get('checks', {}).get(chk, {}).get('reason_code')}) gt={gt}")
