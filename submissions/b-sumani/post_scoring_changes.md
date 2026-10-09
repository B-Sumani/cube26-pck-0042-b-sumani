# Post-Scoring Changes Log

| Date | Change | Reason | Dev Result (`dev_post_photoquality`) | Status |
|---|---|---|---|---|
| **2026-10-09** | Image-quality wording in `gemini.py` (clipped or cut-off frame edges and reflective glare now set `usable=false` with `box_not_in_frame` / `glare`) | Exam units `UNIT-0011` (`cut_off`) and `UNIT-0026` (`glare`) were sealed with no quality flag | False-PASS 0/10, UNCERTAIN 1/18, missing boxes still STOP_AND_FIX, clear boxes 15/15; the `UNIT-0021` flip from STOP_AND_FIX to SEAL is likely run-to-run variation, not an effect of this change; dev has no glare or cut_off cases (per step 2), so the effect on those is untested | Post-scoring change, not validated on held-out data; `exam_final` results unchanged and remain the official score |
