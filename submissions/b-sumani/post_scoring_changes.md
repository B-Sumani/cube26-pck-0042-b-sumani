# Post-Scoring Changes Log

| Date | Change | Reason | Dev Result (`dev_post_photoquality`) | Status |
|---|---|---|---|---|
| **2026-10-09** | Image-quality wording in `gemini.py` (clipped or cut-off frame edges and reflective glare now set `usable=false` with `box_not_in_frame` / `glare`) | Exam units `UNIT-0011` (`cut_off`) and `UNIT-0026` (`glare`) were sealed with no quality flag | False-PASS 0/10, UNCERTAIN 1/18, missing boxes still STOP_AND_FIX, clear boxes 15/15; the `UNIT-0021` flip from STOP_AND_FIX to SEAL is likely run-to-run variation, not an effect of this change; dev has no glare or cut_off cases (per step 2), so the effect on those is untested | Post-scoring change, not validated on held-out data; `exam_final` results unchanged and remain the official score |
| **2026-10-09** | matches_order_index wording in `gemini.py` (item must match the printed title/brand/product name, otherwise null; label must be the exact printed text) | Exam unit `UNIT-0037` (`wrong_item`) was sealed because the model read "A Good Girl's Guide to Murder" but matched it to the ordered "Good Girl Bad Blood" | (`dev_post_lookalike`): False-PASS 0/10, UNCERTAIN 1/18, missing boxes still STOP_AND_FIX, clear boxes 15/15, zero verdict changes versus dev_post_photoquality; look-alike books in dev boxes were matched correctly; dev has no look-alike swap case, so the effect on UNIT-0037-type errors is untested | Post-scoring change, not validated on held-out data; `exam_final` results unchanged and remain the official score |
| **2026-10-09** | tests and migration notes only, no code change | live page showed Quantities Correct PASS for an all-missing box; verified backend verdict is STOP_AND_FIX and the display is a template matter | N/A (regression tests pass: 84 passed, 5 skipped) | no behaviour change |

## Known limits
- UNIT-0093: extra Nivea Body Milk not detected; the model did not see the extra item. Needs a stronger model, not a prompt change.
- UNIT-0046: partially hidden item not detected; the model reported no occlusion. Needs a stronger model, not a prompt change.
