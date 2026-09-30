import json

with open('submissions/b-sumani/eval/real_dev_results_temp0_run1.json') as f:
    d1 = json.load(f)
with open('submissions/b-sumani/eval/real_dev_results_temp0_run2.json') as f:
    d2 = json.load(f)

u1_map = {u['unit_id']: u for u in d1['cases']}
u2_map = {u['unit_id']: u for u in d2['cases']}

verdict_diffs = []
count_diffs = []

for uid, r1 in u1_map.items():
    r2 = u2_map[uid]
    if r1.get('predicted_verdict') != r2.get('predicted_verdict'):
        verdict_diffs.append((uid, r1.get('predicted_verdict'), r2.get('predicted_verdict')))
    # compare per-sku counts
    obs1 = r1.get('observation', {}).get('observed_items', [])
    obs2 = r2.get('observation', {}).get('observed_items', [])
    c1 = {item['sku']: item.get('count') for item in obs1}
    c2 = {item['sku']: item.get('count') for item in obs2}
    if c1 != c2:
        count_diffs.append((uid, c1, c2))

print(f"Verdict diffs ({len(verdict_diffs)}): {verdict_diffs}")
print(f"Count diffs ({len(count_diffs)}): {count_diffs}")

print('\n=== ALL 18 UNITS IN FINAL RUN ===')
for uid, r in sorted(u2_map.items()):
    obs = r.get('observation', {}).get('observed_items', [])
    obs_dict = {item['sku']: item.get('count') for item in obs}
    checks = {k: v.get('result') for k, v in r.get('checks', {}).items()}
    pred = r.get('predicted_verdict')
    gt = r.get('ground_truth_verdict')
    match = (pred == gt)
    print(f"{uid} (type={r.get('failure_type'):<15} subtype={r.get('subtype', ''):<10}): pred={pred:<12} gt={gt:<12} match={str(match):<5} obs={obs_dict}")
