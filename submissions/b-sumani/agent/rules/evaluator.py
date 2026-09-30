"""Deterministic Rules Layer for Pack Manager.

Turns model observations into per-check results (PASS / FAIL / UNCERTAIN)
and synthesizes the box-level record verdict (SEAL / STOP_AND_FIX / UNCERTAIN).

RULES & SPECIFICATIONS (v1 Rules Hardening):
1. Deterministic code decides, never the model.
2. One home per check (orthogonal failure partitioning):
   - all_items_present: strictly presence/identity of all ordered SKUs (observed count >= 1).
   - quantities_correct: strictly piece count accuracy for ordered SKUs (short or surplus).
   - nothing_extra: strictly absence of foreign, decoy, or unrecognised items.
3. Confidence gates FAIL & PASS:
   - A check cannot PASS with low confidence (low-confidence pass is forbidden).
   - A check cannot FAIL without meeting confidence thresholds; low confidence or occlusion yields UNCERTAIN.
4. UNCERTAIN is a first-class verdict, never a low-confidence PASS.
5. Every FAIL and UNCERTAIN carries:
   - a machine-readable reason_code
   - a human-readable reason
   - a failure cause: 'occlusion' or 'recognition'
6. Box-level precedence: FAIL > UNCERTAIN > PASS.
   - Any FAIL -> STOP_AND_FIX (Operator sees STOP).
   - No FAIL and any UNCERTAIN -> UNCERTAIN (Operator sees STOP, record keeps true UNCERTAIN).
   - All 3 PASS -> SEAL (Operator sees go).
7. Thresholds live in config, not scattered across code.
"""

from __future__ import annotations
import re
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from agent.models.base import ModelObservation, ObservedItem
from agent.rules.config import RulesThresholdConfig, DEFAULT_CONFIG


@dataclass
class CheckResult:
    result: str  # "PASS", "FAIL", "UNCERTAIN"
    reason_code: str
    reason: str
    cause: Optional[str] = None  # "occlusion", "recognition", or None


def parse_order_lines(order_lines_str: str) -> Dict[str, int]:
    """Parses order lines string into a dictionary of SKU -> quantity.
    
    Accepts formats:
    - 'SKU-PUZZLE-500:1;SKU-BOTTLE-750:2'
    - 'SKU-PUZZLE-500: 1, SKU-BOTTLE-750: 2'
    - Multiline 'SKU-PUZZLE-500:1\nSKU-BOTTLE-750:2'
    """
    lines: Dict[str, int] = {}
    if not order_lines_str or not order_lines_str.strip():
        return lines

    raw_tokens = re.split(r"[;,\n\r]+", order_lines_str.strip())
    for token in raw_tokens:
        token = token.strip()
        if not token:
            continue
        if ":" in token:
            sku_part, qty_part = token.split(":", 1)
            sku = sku_part.strip()
            try:
                qty = int(qty_part.strip())
            except ValueError:
                qty = 1
            if sku:
                lines[sku] = lines.get(sku, 0) + qty
        else:
            sku = token.strip()
            if sku:
                lines[sku] = lines.get(sku, 0) + 1
    return lines


def evaluate_pack_box(
    order_lines_str: str,
    observation: ModelObservation,
    candidate_skus: Optional[List[str]] = None,
    config: Optional[RulesThresholdConfig] = None
) -> Tuple[Dict[str, Any], str, str]:
    """Compares ModelObservation against expected order lines with hardened deterministic rules.
    
    Enforces 'one home per check' and confidence gates on all decisions.
    
    Returns:
        tuple: (checks_dict, verdict, operator_action)
        - checks_dict: JSON-serializable dict of per-check results
        - verdict: 'SEAL', 'STOP_AND_FIX', or 'UNCERTAIN'
        - operator_action: 'go' (SEAL) or 'STOP' (STOP_AND_FIX / UNCERTAIN)
    """
    cfg = config or DEFAULT_CONFIG
    expected_lines = parse_order_lines(order_lines_str)
    
    # Map observed items by SKU
    observed_by_sku: Dict[str, List[ObservedItem]] = {}
    for item in observation.observed_items:
        observed_by_sku.setdefault(item.sku, []).append(item)

    # -------------------------------------------------------------------------
    # Global Image Quality Gate
    # -------------------------------------------------------------------------
    image_usable = observation.image_quality.usable
    quality_issues = ", ".join(observation.image_quality.issues) if observation.image_quality.issues else "unusable image"

    # =========================================================================
    # CHECK 1: all_items_present (Identity / Presence)
    # Home: Are all required order SKUs present in the box (observed count >= 1)?
    # =========================================================================
    if not image_usable:
        check_identity = CheckResult(
            result="UNCERTAIN",
            reason_code="IMAGE_UNUSABLE",
            reason=f"Photo quality is insufficient to verify item presence: {quality_issues}",
            cause="recognition"
        )
    else:
        missing_skus: List[str] = []
        occluded_skus: List[str] = []
        low_conf_skus: List[Tuple[str, float]] = []

        for sku in expected_lines.keys():
            obs_list = observed_by_sku.get(sku, [])
            total_count = sum(item.count for item in obs_list)

            if total_count == 0:
                # Item not observed: check if occlusion in the box could be hiding it
                if observation.occlusion_suspected:
                    occluded_skus.append(sku)
                else:
                    missing_skus.append(sku)
            else:
                # Item was observed: check identity confidence and occlusion
                for item in obs_list:
                    if item.partially_occluded:
                        occluded_skus.append(sku)
                        break
                    elif item.identity_confidence < cfg.identity_confidence_threshold:
                        low_conf_skus.append((sku, item.identity_confidence))
                        break

        # Decision logic for Check 1:
        # Confidence gates FAIL: if occlusion suspected or low confidence, gate FAIL to UNCERTAIN
        if occluded_skus:
            check_identity = CheckResult(
                result="UNCERTAIN",
                reason_code="ITEM_OCCLUDED",
                reason=f"Cannot confirm presence of {', '.join(set(occluded_skus))} due to occlusion in box",
                cause="occlusion"
            )
        elif low_conf_skus:
            sku_name, conf = low_conf_skus[0]
            check_identity = CheckResult(
                result="UNCERTAIN",
                reason_code="LOW_IDENTITY_CONFIDENCE",
                reason=f"Identity confidence for {sku_name} ({conf:.2f}) is below threshold ({cfg.identity_confidence_threshold:.2f})",
                cause="recognition"
            )
        elif missing_skus:
            check_identity = CheckResult(
                result="FAIL",
                reason_code="MISSING_ITEMS",
                reason=f"Required item(s) missing from open box: {', '.join(missing_skus)}",
                cause="recognition"
            )
        else:
            check_identity = CheckResult(
                result="PASS",
                reason_code="ALL_ITEMS_PRESENT",
                reason="All required order SKUs are clearly present in the box"
            )

    # =========================================================================
    # CHECK 2: quantities_correct (Piece Count)
    # Home: Do the piece counts of ordered items match the expected quantities?
    # One home per check: Missing items (count == 0) are handled in Check 1.
    # =========================================================================
    if not image_usable:
        check_count = CheckResult(
            result="UNCERTAIN",
            reason_code="IMAGE_UNUSABLE",
            reason=f"Photo quality is insufficient to count quantities: {quality_issues}",
            cause="recognition"
        )
    else:
        short_items: List[str] = []
        surplus_items: List[str] = []
        count_occluded: List[str] = []
        count_low_conf: List[Tuple[str, float]] = []
        present_count = 0

        for sku, expected_qty in expected_lines.items():
            obs_list = observed_by_sku.get(sku, [])
            total_observed = sum(item.count for item in obs_list)

            # If completely missing, its defect home is all_items_present
            if total_observed == 0:
                continue

            present_count += 1

            # Check for occlusion and count confidence
            for item in obs_list:
                if item.partially_occluded:
                    count_occluded.append(sku)
                    break
                if item.count_confidence < cfg.count_confidence_threshold:
                    count_low_conf.append((sku, item.count_confidence))
                    break

            if total_observed < expected_qty:
                short_items.append(f"{sku} (expected {expected_qty}, observed {total_observed})")
            elif total_observed > expected_qty:
                surplus_items.append(f"{sku} (expected {expected_qty}, observed {total_observed})")

        # Decision logic for Check 2:
        # Confidence gates FAIL: occlusion or low count confidence produces UNCERTAIN
        if count_occluded:
            check_count = CheckResult(
                result="UNCERTAIN",
                reason_code="COUNT_OCCLUDED",
                reason=f"Occlusion prevents accurate piece count for {', '.join(set(count_occluded))}",
                cause="occlusion"
            )
        elif count_low_conf:
            sku_name, conf = count_low_conf[0]
            check_count = CheckResult(
                result="UNCERTAIN",
                reason_code="LOW_COUNT_CONFIDENCE",
                reason=f"Count confidence for {sku_name} ({conf:.2f}) is below threshold ({cfg.count_confidence_threshold:.2f})",
                cause="recognition"
            )
        elif short_items:
            check_count = CheckResult(
                result="FAIL",
                reason_code="SHORT_QUANTITY",
                reason=f"Short quantity for required item(s): {', '.join(short_items)}",
                cause="recognition"
            )
        elif surplus_items:
            check_count = CheckResult(
                result="FAIL",
                reason_code="SURPLUS_QUANTITY",
                reason=f"Excess quantity packed for ordered item(s): {', '.join(surplus_items)}",
                cause="recognition"
            )
        elif present_count == 0 and len(expected_lines) > 0:
            # All items were missing: defect is owned by Check 1
            check_count = CheckResult(
                result="PASS",
                reason_code="DEFERRED_TO_PRESENCE_CHECK",
                reason="Quantity check deferred: all items missing, evaluated under identity check"
            )
        else:
            check_count = CheckResult(
                result="PASS",
                reason_code="QUANTITIES_MATCH",
                reason="Observed item counts exactly match the order line quantities"
            )

    # =========================================================================
    # CHECK 3: nothing_extra (Surplus / Decoys / Foreign Items)
    # Home: Are there unauthorized items (decoys or unrecognised items) in the box?
    # One home per check: Surplus of an ordered SKU is handled in Check 2.
    # =========================================================================
    if not image_usable:
        check_extra = CheckResult(
            result="UNCERTAIN",
            reason_code="IMAGE_UNUSABLE",
            reason=f"Photo quality is insufficient to verify absence of extra items: {quality_issues}",
            cause="recognition"
        )
    else:
        unrecognised_found: List[str] = []
        decoys_found: List[str] = []
        low_conf_extra: List[Tuple[str, float]] = []

        # 1. Unrecognised items (foreign items outside candidate catalogue)
        if observation.unrecognised_items:
            for unrec in observation.unrecognised_items:
                desc = unrec.description or "unrecognised object"
                unrecognised_found.append(desc)

        # 2. Decoy items (candidate SKUs that are NOT in the order lines)
        for item in observation.observed_items:
            if item.sku not in expected_lines and item.count > 0:
                if item.identity_confidence < cfg.identity_confidence_threshold:
                    low_conf_extra.append((item.sku, item.identity_confidence))
                else:
                    decoys_found.append(f"{item.sku} (count: {item.count})")

        # Decision logic for Check 3:
        if low_conf_extra:
            sku_name, conf = low_conf_extra[0]
            check_extra = CheckResult(
                result="UNCERTAIN",
                reason_code="LOW_CONFIDENCE_EXTRA_ITEM",
                reason=f"Low confidence ({conf:.2f}) identifying possible extra item {sku_name}",
                cause="recognition"
            )
        elif unrecognised_found:
            check_extra = CheckResult(
                result="FAIL",
                reason_code="UNRECOGNISED_ITEMS_PRESENT",
                reason=f"Unrecognised foreign item(s) found in box: {', '.join(unrecognised_found)}",
                cause="recognition"
            )
        elif decoys_found:
            check_extra = CheckResult(
                result="FAIL",
                reason_code="DECOY_ITEM_PRESENT",
                reason=f"Unauthorized decoy SKU(s) found in box: {', '.join(decoys_found)}",
                cause="recognition"
            )
        else:
            check_extra = CheckResult(
                result="PASS",
                reason_code="NO_EXTRA_ITEMS",
                reason="No extra, decoy, or foreign items observed in the box"
            )

    # -------------------------------------------------------------------------
    # Box Verdict Synthesis
    # Precedence: FAIL > UNCERTAIN > PASS
    # -------------------------------------------------------------------------
    checks = {
        "all_items_present": {
            "result": check_identity.result,
            "reason_code": check_identity.reason_code,
            "reason": check_identity.reason,
            "cause": check_identity.cause
        },
        "quantities_correct": {
            "result": check_count.result,
            "reason_code": check_count.reason_code,
            "reason": check_count.reason,
            "cause": check_count.cause
        },
        "nothing_extra": {
            "result": check_extra.result,
            "reason_code": check_extra.reason_code,
            "reason": check_extra.reason,
            "cause": check_extra.cause
        }
    }

    all_results = [check_identity.result, check_count.result, check_extra.result]

    if "FAIL" in all_results:
        verdict = "STOP_AND_FIX"
        operator_action = "STOP"
    elif "UNCERTAIN" in all_results:
        verdict = "UNCERTAIN"
        operator_action = "STOP"  # Operator sees STOP; record keeps true UNCERTAIN
    else:
        verdict = "SEAL"
        operator_action = "go"

    return checks, verdict, operator_action
