import json

with open('submissions/b-sumani/eval/real_dev_results_temp0_run2.json') as f:
    d = json.load(f)

for chk in ['all_items_present', 'quantities_correct', 'nothing_extra']:
    print(f'=== {chk} ===')
    preds = {}
    for c in sorted(d['cases'], key=lambda x: x['unit_id']):
        pred = c.get('checks', {}).get(chk, {}).get('result')
        gt = c.get('ground_truth_checks', {}).get(chk)
        preds[pred] = preds.get(pred, 0) + 1
        print(f"{c['unit_id']}: pred={pred} (gt={gt}) type={c['failure_type']}")
    print(f"Summary for {chk}: {preds}, total={sum(preds.values())}")
