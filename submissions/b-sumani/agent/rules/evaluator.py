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
    ordered_skus = list(expected_lines.keys())
    sku_to_idx = {sku.strip().upper(): idx for idx, sku in enumerate(ordered_skus)}
    
    # Resolve matches_order_index and SKU for all observed items
    for item in observation.observed_items:
        if item.matches_order_index is not None:
            if 0 <= item.matches_order_index < len(ordered_skus):
                item.sku = ordered_skus[item.matches_order_index]
            else:
                item.matches_order_index = None
        elif item.sku and item.sku.strip().upper() in sku_to_idx:
            # Fallback for directly set SKU (e.g. in test fixtures)
            item.matches_order_index = sku_to_idx[item.sku.strip().upper()]

    # Aggregate matched items per ordered row index
    row_stats: Dict[int, Dict[str, Any]] = {}
    for idx, sku in enumerate(ordered_skus):
        matched = [it for it in observation.observed_items if it.matches_order_index == idx]
        if matched:
            row_stats[idx] = {
                "total_count": sum(it.count for it in matched),
                "min_ident_conf": min(it.identity_confidence for it in matched),
                "min_count_conf": min(it.count_confidence for it in matched),
                "is_occluded": any(it.partially_occluded for it in matched),
                "items": matched
            }
        else:
            row_stats[idx] = {
                "total_count": 0,
                "min_ident_conf": 0.0,
                "min_count_conf": 0.0,
                "is_occluded": False,
                "items": []
            }

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

        for idx, sku in enumerate(ordered_skus):
            stats = row_stats[idx]
            total_count = stats["total_count"]

            if total_count == 0:
                if observation.occlusion_suspected:
                    occluded_skus.append(sku)
                else:
                    missing_skus.append(sku)
            else:
                if stats["is_occluded"]:
                    occluded_skus.append(sku)
                elif stats["min_ident_conf"] < cfg.identity_confidence_threshold:
                    low_conf_skus.append((sku, stats["min_ident_conf"]))

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

        for idx, sku in enumerate(ordered_skus):
            expected_qty = expected_lines[sku]
            stats = row_stats[idx]
            total_observed = stats["total_count"]

            if total_observed == 0:
                continue

            present_count += 1

            if stats["is_occluded"]:
                count_occluded.append(sku)
            elif stats["min_count_conf"] < cfg.count_confidence_threshold:
                count_low_conf.append((sku, stats["min_count_conf"]))
            elif total_observed < expected_qty:
                short_items.append(f"{sku} (expected {expected_qty}, observed {total_observed})")
            elif total_observed > expected_qty:
                surplus_items.append(f"{sku} (expected {expected_qty}, observed {total_observed})")

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
    # Home: Are there unauthorized items (null match) in the box?
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
        extra_items = [
            it for it in observation.observed_items
            if it.matches_order_index is None and it.count > 0
        ]
        legacy_extras = [
            it.description for it in observation.unrecognised_items
        ]

        if not extra_items and not legacy_extras:
            check_extra = CheckResult(
                result="PASS",
                reason_code="NO_EXTRA_ITEMS",
                reason="No extra, decoy, or foreign items observed in the box"
            )
        else:
            # If any extra object is confident, the check is FAIL (UNRECOGNISED_ITEMS_PRESENT).
            # UNCERTAIN only when all extras are low confidence. Use identity_confidence for extras.
            confident_extras = [
                it for it in extra_items
                if it.identity_confidence >= cfg.identity_confidence_threshold
            ]

            if confident_extras or legacy_extras:
                descriptions = [
                    f"{it.label or 'unrecognised item'} (count: {it.count}, bbox: {it.bbox})"
                    for it in confident_extras
                ] + legacy_extras
                check_extra = CheckResult(
                    result="FAIL",
                    reason_code="UNRECOGNISED_ITEMS_PRESENT",
                    reason=f"Unrecognised extra item(s) found in box: {', '.join(descriptions)}",
                    cause="recognition"
                )
            else:
                low_conf_extras = [
                    f"{it.label or 'unknown object'} ({it.identity_confidence:.2f})"
                    for it in extra_items
                ]
                check_extra = CheckResult(
                    result="UNCERTAIN",
                    reason_code="LOW_CONFIDENCE_EXTRA_ITEM",
                    reason=f"Low confidence ({extra_items[0].identity_confidence:.2f}) identifying possible extra item: {', '.join(low_conf_extras)}",
                    cause="recognition"
                )

    # -------------------------------------------------------------------------
    # Gating Rule (Iteration B): Ambiguity / Quality Downgrade
    # If image_quality.issues contains blur, glare, or box_not_in_frame,
    # or occlusion_suspected is true, then a missing-item FAIL and any PASS
    # become UNCERTAIN.
    # -------------------------------------------------------------------------
    quality_issues_lower = {iss.lower().strip() for iss in observation.image_quality.issues}
    quality_defect = bool(quality_issues_lower & {"blur", "glare", "box_not_in_frame"})
    occlusion_defect = bool(observation.occlusion_suspected)

    if quality_defect or occlusion_defect:
        gate_cause = "occlusion" if occlusion_defect else "recognition"
        gate_reason_prefix = "Occlusion suspected in carton" if occlusion_defect else f"Image quality issues observed ({quality_issues})"

        # 1. missing-item FAIL in all_items_present becomes UNCERTAIN
        if check_identity.result == "FAIL" and check_identity.reason_code == "MISSING_ITEMS":
            check_identity = CheckResult(
                result="UNCERTAIN",
                reason_code="ITEM_OCCLUDED" if occlusion_defect else "UNVERIFIED_UNDER_QUALITY_DEFECT",
                reason=f"{gate_reason_prefix}: cannot verify if missing item(s) are absent or concealed",
                cause=gate_cause
            )
        # Any PASS in all_items_present becomes UNCERTAIN
        elif check_identity.result == "PASS":
            check_identity = CheckResult(
                result="UNCERTAIN",
                reason_code="UNVERIFIED_UNDER_OCCLUSION" if occlusion_defect else "UNVERIFIED_UNDER_QUALITY_DEFECT",
                reason=f"{gate_reason_prefix}: item presence cannot be verified",
                cause=gate_cause
            )

        # 2. Any PASS in quantities_correct becomes UNCERTAIN
        if check_count.result == "PASS":
            check_count = CheckResult(
                result="UNCERTAIN",
                reason_code="UNVERIFIED_UNDER_OCCLUSION" if occlusion_defect else "UNVERIFIED_UNDER_QUALITY_DEFECT",
                reason=f"{gate_reason_prefix}: item quantities cannot be verified",
                cause=gate_cause
            )

        # 3. Any PASS in nothing_extra becomes UNCERTAIN
        if check_extra.result == "PASS":
            check_extra = CheckResult(
                result="UNCERTAIN",
                reason_code="UNVERIFIED_UNDER_OCCLUSION" if occlusion_defect else "UNVERIFIED_UNDER_QUALITY_DEFECT",
                reason=f"{gate_reason_prefix}: carton contents cannot be verified as free of extra items",
                cause=gate_cause
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
