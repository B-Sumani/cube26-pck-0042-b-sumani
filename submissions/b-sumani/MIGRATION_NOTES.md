# Migration Notes

- **Files to carry over**: `gemini.py` (prompt changes from commits `1e52743` and `0350436`), `evaluator.py`, the tests, `post_scoring_changes.md`, `PROVENANCE.md`, `README` section 8
- **Behaviour to know**: `quantities_correct` returns `PASS`/`DEFERRED_TO_PRESENCE_CHECK` when all items are missing; the failure is shown by `all_items_present` and the verdict is `STOP_AND_FIX`
- **Optional display fixes (NOT applied here)**: in `result_partial.html` and `record_detail.html` show a neutral "N/A" badge when `quantities_correct.reason_code == 'DEFERRED_TO_PRESENCE_CHECK'`; show "No items detected in the photograph" instead of the green "No extra or unauthorized objects" tick when nothing was observed; add a notice when no ordered item matched but items were detected
- **Known limits**: `UNIT-0093` and `UNIT-0046` need a stronger model
