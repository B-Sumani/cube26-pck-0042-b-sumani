"""Unit tests for hardened deterministic rules layer (v1).

Validates:
1. One home per check (orthogonal failure partitioning: identity vs count vs extra).
2. Confidence gates FAIL & PASS (low confidence or occlusion gates to UNCERTAIN).
3. Every FAIL and UNCERTAIN carries reason_code, reason, and cause ('occlusion' | 'recognition').
4. Box verdict precedence (FAIL > UNCERTAIN > PASS).
5. Evidence-based UNCERTAIN: clear photos get PASS or FAIL in both directions (never forced/quota-based).
6. Configurable thresholds via RulesThresholdConfig.
"""

import pytest
from agent.models.base import ModelObservation, ObservedItem, UnrecognisedItem, ImageQuality
from agent.rules.config import RulesThresholdConfig
from agent.rules.evaluator import evaluate_pack_box, parse_order_lines


def test_parse_order_lines_formats():
    """Validates parsing semicolon, comma, and newline delimited order lines."""
    # Semicolon
    lines = parse_order_lines("SKU-A:1;SKU-B:2")
    assert lines == {"SKU-A": 1, "SKU-B": 2}

    # Comma with spaces
    lines = parse_order_lines("SKU-A: 1, SKU-B: 3")
    assert lines == {"SKU-A": 1, "SKU-B": 3}

    # Multiline
    lines = parse_order_lines("SKU-A:2\nSKU-B:1\nSKU-C:5")
    assert lines == {"SKU-A": 2, "SKU-B": 1, "SKU-C": 5}

    # Empty
    assert parse_order_lines("") == {}


def test_one_home_per_check_missing_item():
    """Defect: Required item completely missing.
    Home: all_items_present FAIL.
    quantities_correct does not double-fail.
    nothing_extra PASS.
    """
    obs = ModelObservation(
        observed_items=[
            ObservedItem(
                sku="SKU-PUZZLE-500",
                count=1,
                count_confidence=0.95,
                identity_confidence=0.98,
                partially_occluded=False,
                bbox=[10, 10, 100, 100]
            )
        ],
        unrecognised_items=[],
        image_quality=ImageQuality(usable=True, issues=[]),
        occlusion_suspected=False
    )
    # Order requires PUZZLE and BOTTLE
    order = "SKU-PUZZLE-500:1;SKU-BOTTLE-750:1"
    checks, verdict, action = evaluate_pack_box(order, obs)

    # 1. all_items_present holds the defect
    assert checks["all_items_present"]["result"] == "FAIL"
    assert checks["all_items_present"]["reason_code"] == "MISSING_ITEMS"
    assert checks["all_items_present"]["cause"] == "recognition"
    assert "SKU-BOTTLE-750" in checks["all_items_present"]["reason"]

    # 2. quantities_correct does not double-penalize
    assert checks["quantities_correct"]["result"] == "PASS"

    # 3. nothing_extra is clean
    assert checks["nothing_extra"]["result"] == "PASS"

    # Box verdict is STOP_AND_FIX
    assert verdict == "STOP_AND_FIX"
    assert action == "STOP"


def test_one_home_per_check_short_quantity():
    """Defect: Required item present, but piece count is short.
    Home: quantities_correct FAIL (SHORT_QUANTITY).
    all_items_present PASS.
    nothing_extra PASS.
    """
    obs = ModelObservation(
        observed_items=[
            ObservedItem(
                sku="SKU-TOWEL-BLU",
                count=1,
                count_confidence=0.95,
                identity_confidence=0.98,
                partially_occluded=False,
                bbox=[10, 10, 100, 100]
            )
        ],
        unrecognised_items=[],
        image_quality=ImageQuality(usable=True, issues=[]),
        occlusion_suspected=False
    )
    order = "SKU-TOWEL-BLU:2"  # Expected 2, observed 1
    checks, verdict, action = evaluate_pack_box(order, obs)

    assert checks["all_items_present"]["result"] == "PASS"
    assert checks["quantities_correct"]["result"] == "FAIL"
    assert checks["quantities_correct"]["reason_code"] == "SHORT_QUANTITY"
    assert checks["quantities_correct"]["cause"] == "recognition"
    assert "expected 2, observed 1" in checks["quantities_correct"]["reason"]
    assert checks["nothing_extra"]["result"] == "PASS"

    assert verdict == "STOP_AND_FIX"
    assert action == "STOP"


def test_one_home_per_check_surplus_quantity():
    """Defect: Required item present, but piece count has surplus.
    Home: quantities_correct FAIL (SURPLUS_QUANTITY).
    all_items_present PASS.
    nothing_extra PASS (surplus of ordered item belongs in count check, not foreign extra).
    """
    obs = ModelObservation(
        observed_items=[
            ObservedItem(
                sku="SKU-TOWEL-BLU",
                count=3,
                count_confidence=0.95,
                identity_confidence=0.98,
                partially_occluded=False,
                bbox=[10, 10, 100, 100]
            )
        ],
        unrecognised_items=[],
        image_quality=ImageQuality(usable=True, issues=[]),
        occlusion_suspected=False
    )
    order = "SKU-TOWEL-BLU:2"  # Expected 2, observed 3
    checks, verdict, action = evaluate_pack_box(order, obs)

    assert checks["all_items_present"]["result"] == "PASS"
    assert checks["quantities_correct"]["result"] == "FAIL"
    assert checks["quantities_correct"]["reason_code"] == "SURPLUS_QUANTITY"
    assert checks["quantities_correct"]["cause"] == "recognition"
    assert "expected 2, observed 3" in checks["quantities_correct"]["reason"]
    assert checks["nothing_extra"]["result"] == "PASS"

    assert verdict == "STOP_AND_FIX"
    assert action == "STOP"


def test_one_home_per_check_decoy_item_present():
    """Defect: Authorized decoy SKU observed in box.
    Home: nothing_extra FAIL (DECOY_ITEM_PRESENT).
    all_items_present PASS.
    quantities_correct PASS.
    """
    obs = ModelObservation(
        observed_items=[
            ObservedItem(
                sku="SKU-PUZZLE-500",
                count=1,
                count_confidence=0.95,
                identity_confidence=0.98,
                partially_occluded=False,
                bbox=[10, 10, 100, 100]
            ),
            ObservedItem(
                sku="SKU-CABLE-USBC",  # Decoy!
                count=1,
                count_confidence=0.92,
                identity_confidence=0.95,
                partially_occluded=False,
                bbox=[150, 150, 200, 200]
            )
        ],
        unrecognised_items=[],
        image_quality=ImageQuality(usable=True, issues=[]),
        occlusion_suspected=False
    )
    order = "SKU-PUZZLE-500:1"
    candidates = ["SKU-PUZZLE-500", "SKU-CABLE-USBC"]
    checks, verdict, action = evaluate_pack_box(order, obs, candidate_skus=candidates)

    assert checks["all_items_present"]["result"] == "PASS"
    assert checks["quantities_correct"]["result"] == "PASS"
    assert checks["nothing_extra"]["result"] == "FAIL"
    assert checks["nothing_extra"]["reason_code"] == "DECOY_ITEM_PRESENT"
    assert checks["nothing_extra"]["cause"] == "recognition"
    assert "SKU-CABLE-USBC" in checks["nothing_extra"]["reason"]

    assert verdict == "STOP_AND_FIX"
    assert action == "STOP"


def test_one_home_per_check_unrecognised_item_present():
    """Defect: Unrecognised foreign item in box.
    Home: nothing_extra FAIL (UNRECOGNISED_ITEMS_PRESENT).
    """
    obs = ModelObservation(
        observed_items=[
            ObservedItem(
                sku="SKU-BOTTLE-750",
                count=1,
                count_confidence=0.95,
                identity_confidence=0.98,
                partially_occluded=False,
                bbox=[10, 10, 100, 100]
            )
        ],
        unrecognised_items=[
            UnrecognisedItem(
                description="loose metal wrench",
                bbox=[200, 200, 300, 300]
            )
        ],
        image_quality=ImageQuality(usable=True, issues=[]),
        occlusion_suspected=False
    )
    order = "SKU-BOTTLE-750:1"
    checks, verdict, action = evaluate_pack_box(order, obs)

    assert checks["all_items_present"]["result"] == "PASS"
    assert checks["quantities_correct"]["result"] == "PASS"
    assert checks["nothing_extra"]["result"] == "FAIL"
    assert checks["nothing_extra"]["reason_code"] == "UNRECOGNISED_ITEMS_PRESENT"
    assert checks["nothing_extra"]["cause"] == "recognition"
    assert "loose metal wrench" in checks["nothing_extra"]["reason"]

    assert verdict == "STOP_AND_FIX"


def test_confidence_gates_fail_for_missing_item_when_occlusion_suspected():
    """Item appears missing, but occlusion is suspected in box.
    Confidence gate prevents false FAIL: verdict becomes UNCERTAIN with cause='occlusion'.
    """
    obs = ModelObservation(
        observed_items=[],  # Nothing seen
        unrecognised_items=[],
        image_quality=ImageQuality(usable=True, issues=[]),
        occlusion_suspected=True  # Flaps / items obscuring bottom
    )
    order = "SKU-PUZZLE-500:1"
    checks, verdict, action = evaluate_pack_box(order, obs)

    assert checks["all_items_present"]["result"] == "UNCERTAIN"
    assert checks["all_items_present"]["reason_code"] == "ITEM_OCCLUDED"
    assert checks["all_items_present"]["cause"] == "occlusion"

    assert verdict == "UNCERTAIN"
    assert action == "STOP"


def test_confidence_gates_fail_for_low_identity_confidence():
    """Item reported, but identity confidence is below threshold (e.g. 0.60 < 0.75).
    Cannot PASS and cannot confidently FAIL: gates to UNCERTAIN with cause='recognition'.
    """
    obs = ModelObservation(
        observed_items=[
            ObservedItem(
                sku="SKU-BOTTLE-750",
                count=1,
                count_confidence=0.90,
                identity_confidence=0.60,  # Below 0.75 threshold
                partially_occluded=False,
                bbox=[10, 10, 100, 100]
            )
        ],
        unrecognised_items=[],
        image_quality=ImageQuality(usable=True, issues=[]),
        occlusion_suspected=False
    )
    order = "SKU-BOTTLE-750:1"
    checks, verdict, action = evaluate_pack_box(order, obs)

    assert checks["all_items_present"]["result"] == "UNCERTAIN"
    assert checks["all_items_present"]["reason_code"] == "LOW_IDENTITY_CONFIDENCE"
    assert checks["all_items_present"]["cause"] == "recognition"
    assert "0.60" in checks["all_items_present"]["reason"]

    assert verdict == "UNCERTAIN"
    assert action == "STOP"


def test_confidence_gates_fail_for_low_count_confidence():
    """Item reported, but count confidence is below threshold (e.g. 0.55 < 0.70).
    Count mismatch is gated from FAIL to UNCERTAIN.
    """
    obs = ModelObservation(
        observed_items=[
            ObservedItem(
                sku="SKU-BOTTLE-750",
                count=1,
                count_confidence=0.55,  # Below 0.70 threshold
                identity_confidence=0.95,
                partially_occluded=False,
                bbox=[10, 10, 100, 100]
            )
        ],
        unrecognised_items=[],
        image_quality=ImageQuality(usable=True, issues=[]),
        occlusion_suspected=False
    )
    order = "SKU-BOTTLE-750:2"  # Expected 2, observed 1 with low count confidence
    checks, verdict, action = evaluate_pack_box(order, obs)

    assert checks["all_items_present"]["result"] == "PASS"
    assert checks["quantities_correct"]["result"] == "UNCERTAIN"
    assert checks["quantities_correct"]["reason_code"] == "LOW_COUNT_CONFIDENCE"
    assert checks["quantities_correct"]["cause"] == "recognition"

    assert verdict == "UNCERTAIN"
    assert action == "STOP"


def test_confidence_gates_fail_for_low_confidence_extra_item():
    """Extra item suspected, but identity confidence is low (0.50 < 0.75).
    Gates to UNCERTAIN rather than false alarm FAIL.
    """
    obs = ModelObservation(
        observed_items=[
            ObservedItem(
                sku="SKU-PUZZLE-500",
                count=1,
                count_confidence=0.95,
                identity_confidence=0.95,
                partially_occluded=False,
                bbox=[10, 10, 100, 100]
            ),
            ObservedItem(
                sku="SKU-CABLE-USBC",
                count=1,
                count_confidence=0.80,
                identity_confidence=0.50,  # Below threshold
                partially_occluded=False,
                bbox=[150, 150, 200, 200]
            )
        ],
        unrecognised_items=[],
        image_quality=ImageQuality(usable=True, issues=[]),
        occlusion_suspected=False
    )
    order = "SKU-PUZZLE-500:1"
    checks, verdict, action = evaluate_pack_box(order, obs)

    assert checks["all_items_present"]["result"] == "PASS"
    assert checks["quantities_correct"]["result"] == "PASS"
    assert checks["nothing_extra"]["result"] == "UNCERTAIN"
    assert checks["nothing_extra"]["reason_code"] == "LOW_CONFIDENCE_EXTRA_ITEM"
    assert checks["nothing_extra"]["cause"] == "recognition"

    assert verdict == "UNCERTAIN"
    assert action == "STOP"


def test_partially_occluded_item_produces_uncertain_with_cause_occlusion():
    """Item in box is partially occluded by packing material or another item."""
    obs = ModelObservation(
        observed_items=[
            ObservedItem(
                sku="SKU-PUZZLE-500",
                count=1,
                count_confidence=0.90,
                identity_confidence=0.90,
                partially_occluded=True,  # Occlusion tag
                bbox=[10, 10, 100, 100]
            )
        ],
        unrecognised_items=[],
        image_quality=ImageQuality(usable=True, issues=[]),
        occlusion_suspected=False
    )
    order = "SKU-PUZZLE-500:1"
    checks, verdict, action = evaluate_pack_box(order, obs)

    assert checks["all_items_present"]["result"] == "UNCERTAIN"
    assert checks["all_items_present"]["cause"] == "occlusion"
    assert checks["quantities_correct"]["result"] == "UNCERTAIN"
    assert checks["quantities_correct"]["cause"] == "occlusion"

    assert verdict == "UNCERTAIN"
    assert action == "STOP"


def test_unusable_image_quality_produces_uncertain_with_cause_recognition():
    """Unusable image quality (blurry, glare) produces UNCERTAIN across all checks."""
    obs = ModelObservation(
        observed_items=[],
        unrecognised_items=[],
        image_quality=ImageQuality(usable=False, issues=["blur", "dark", "box_not_in_frame"]),
        occlusion_suspected=False
    )
    order = "SKU-BOTTLE-750:1"
    checks, verdict, action = evaluate_pack_box(order, obs)

    for check_key in ["all_items_present", "quantities_correct", "nothing_extra"]:
        assert checks[check_key]["result"] == "UNCERTAIN"
        assert checks[check_key]["reason_code"] == "IMAGE_UNUSABLE"
        assert checks[check_key]["cause"] == "recognition"
        assert "blur" in checks[check_key]["reason"]

    assert verdict == "UNCERTAIN"
    assert action == "STOP"


def test_fail_takes_precedence_over_uncertain():
    """Proves priority: FAIL > UNCERTAIN > PASS.
    If one check is FAIL (e.g. unrecognised item) and another is UNCERTAIN (low confidence),
    the box verdict is STOP_AND_FIX.
    """
    obs = ModelObservation(
        observed_items=[
            ObservedItem(
                sku="SKU-BOTTLE-750",
                count=1,
                count_confidence=0.95,
                identity_confidence=0.50,  # Low confidence -> UNCERTAIN on presence
                partially_occluded=False,
                bbox=[10, 10, 100, 100]
            )
        ],
        unrecognised_items=[
            UnrecognisedItem(
                description="illegal battery",
                bbox=[200, 200, 300, 300]
            )
        ],  # Clear FAIL on extra
        image_quality=ImageQuality(usable=True, issues=[]),
        occlusion_suspected=False
    )
    order = "SKU-BOTTLE-750:1"
    checks, verdict, action = evaluate_pack_box(order, obs)

    assert checks["all_items_present"]["result"] == "UNCERTAIN"
    assert checks["nothing_extra"]["result"] == "FAIL"

    # Precedence: FAIL overrides UNCERTAIN for box verdict
    assert verdict == "STOP_AND_FIX"
    assert action == "STOP"


def test_evidence_based_uncertain_clear_photo_both_directions():
    """Validates context.md Section 14 rule:
    'UNCERTAIN must come only from evidence, never forced or quota-based.
     A clear photo must still get PASS or FAIL. Add tests for both directions.'
    """
    # Direction 1: Clear matching photo MUST produce PASS (SEAL), never UNCERTAIN
    good_obs = ModelObservation(
        observed_items=[
            ObservedItem(
                sku="SKU-SERUM-30",
                count=1,
                count_confidence=0.96,
                identity_confidence=0.99,
                partially_occluded=False,
                bbox=[50, 50, 250, 250]
            )
        ],
        unrecognised_items=[],
        image_quality=ImageQuality(usable=True, issues=[]),
        occlusion_suspected=False
    )
    checks_pass, verdict_pass, action_pass = evaluate_pack_box("SKU-SERUM-30:1", good_obs)
    assert checks_pass["all_items_present"]["result"] == "PASS"
    assert checks_pass["quantities_correct"]["result"] == "PASS"
    assert checks_pass["nothing_extra"]["result"] == "PASS"
    assert verdict_pass == "SEAL"
    assert action_pass == "go"

    # Direction 2: Clear mismatch photo MUST produce FAIL (STOP_AND_FIX), never UNCERTAIN
    bad_obs = ModelObservation(
        observed_items=[
            ObservedItem(
                sku="SKU-SERUM-30",
                count=2,  # Clear surplus count
                count_confidence=0.98,
                identity_confidence=0.99,
                partially_occluded=False,
                bbox=[50, 50, 250, 250]
            )
        ],
        unrecognised_items=[],
        image_quality=ImageQuality(usable=True, issues=[]),
        occlusion_suspected=False
    )
    checks_fail, verdict_fail, action_fail = evaluate_pack_box("SKU-SERUM-30:1", bad_obs)
    assert checks_fail["all_items_present"]["result"] == "PASS"
    assert checks_fail["quantities_correct"]["result"] == "FAIL"
    assert checks_fail["nothing_extra"]["result"] == "PASS"
    assert verdict_fail == "STOP_AND_FIX"
    assert action_fail == "STOP"


def test_custom_config_thresholds_override():
    """Proves that passing custom RulesThresholdConfig strictly controls decision boundaries."""
    strict_config = RulesThresholdConfig(
        count_confidence_threshold=0.90,
        identity_confidence_threshold=0.95,
        version="v1.custom"
    )

    # Observation with 0.85 confidence: passes default (0.75), but fails strict (0.95)
    obs = ModelObservation(
        observed_items=[
            ObservedItem(
                sku="SKU-LAMP-LED",
                count=1,
                count_confidence=0.88,
                identity_confidence=0.85,  # 0.85 < 0.95 strict threshold
                partially_occluded=False,
                bbox=[10, 10, 100, 100]
            )
        ],
        unrecognised_items=[],
        image_quality=ImageQuality(usable=True, issues=[]),
        occlusion_suspected=False
    )
    order = "SKU-LAMP-LED:1"

    # Default config: 0.85 >= 0.75 -> PASS
    checks_default, verdict_default, _ = evaluate_pack_box(order, obs)
    assert checks_default["all_items_present"]["result"] == "PASS"
    assert verdict_default == "SEAL"

    # Strict config: 0.85 < 0.95 -> UNCERTAIN
    checks_strict, verdict_strict, _ = evaluate_pack_box(order, obs, config=strict_config)
    assert checks_strict["all_items_present"]["result"] == "UNCERTAIN"
    assert verdict_strict == "UNCERTAIN"
