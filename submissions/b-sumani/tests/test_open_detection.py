"""Tests for Open-Vocabulary Detection, Prompting, Parsing, and Evaluator Logic.

Validates all requirements under the open detection build:
1. Unknown object gives FAIL with description and bbox (UNRECOGNISED_ITEMS_PRESENT).
2. Low-confidence unknown gives UNCERTAIN (LOW_CONFIDENCE_EXTRA_ITEM).
3. Mixed confident and low-confidence extras gives FAIL (confident extra takes precedence).
4. Missing ordered item gives FAIL (MISSING_ITEMS).
5. Wrong quantity gives FAIL (SHORT_QUANTITY or SURPLUS_QUANTITY).
6. The prompt contains names but no quantities.
7. Multiple images make exactly ONE model call.
8. Occlusion downgrades a PASS to UNCERTAIN.
9. Malformed JSON and timeouts fail open to PENDING.
10. Minimum confidence used across detections matched to the same ordered row.
11. Multi-photo upload constraints (max 5 photos, Vercel 4.5 MB payload limit).
"""

import io
import json
import pytest
from PIL import Image
from starlette.testclient import TestClient

from agent.main import app, set_adapter, get_adapter, sign_session_org, COOKIE_NAME
from agent.models.base import (
    ObservedItem,
    ImageQuality,
    ModelObservation,
    ModelParsingError,
    ModelTimeoutError,
    PROMPT_VERSION,
)
from agent.models.mock import MockVisionAdapter
from agent.models.gemini import GeminiVisionAdapter
from agent.models.parser import parse_and_validate_observation
from agent.rules.evaluator import evaluate_pack_box


def create_test_image(format="JPEG", size=(60, 60), color=(200, 200, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color=color).save(buf, format=format)
    return buf.getvalue()


# ----------------------------------------------------------------------------
# 1. Unknown object gives FAIL with description and bbox
# ----------------------------------------------------------------------------
def test_unknown_object_gives_fail_with_description_and_bbox(client):
    """An extra object with matches_order_index=None and identity_confidence >= threshold gives FAIL, preserving description and bbox."""
    obs = ModelObservation(
        observed_items=[
            ObservedItem(
                label="Jigsaw Puzzle",
                visible_attributes="Blue box",
                matches_order_index=0,
                sku="SKU-PUZZLE-500",
                count=1,
                count_confidence=0.95,
                identity_confidence=0.95,
                partially_occluded=False,
                bbox=[10, 10, 100, 100],
            ),
            ObservedItem(
                label="Unknown Scissors",
                visible_attributes="Red handle metal blades",
                matches_order_index=None,
                sku=None,
                count=1,
                count_confidence=0.90,
                identity_confidence=0.88,  # >= 0.75 threshold
                partially_occluded=False,
                bbox=[120.0, 120.0, 200.0, 200.0],
            ),
        ],
        unrecognised_items=[],
        image_quality=ImageQuality(usable=True, issues=[]),
        occlusion_suspected=False,
    )
    # 1. Deterministic evaluator output check
    checks, verdict, action = evaluate_pack_box("SKU-PUZZLE-500:1", obs)

    assert checks["all_items_present"]["result"] == "PASS"
    assert checks["quantities_correct"]["result"] == "PASS"
    assert checks["nothing_extra"]["result"] == "FAIL"
    assert checks["nothing_extra"]["reason_code"] == "UNRECOGNISED_ITEMS_PRESENT"
    assert "Unknown Scissors" in checks["nothing_extra"]["reason"]
    assert verdict == "STOP_AND_FIX"
    assert action == "STOP"

    # 2. Persistence audit check via endpoint
    set_adapter(MockVisionAdapter(default_observation=obs))
    from agent.db.repo import PackRepository
    photo_bytes = create_test_image("JPEG")
    files = {"photo": ("box.jpg", photo_bytes, "image/jpeg")}
    data = {
        "order_id": "ORD-EXTRA-OBJ-1",
        "unit_id": "UNIT-EXTRA-OBJ-1",
        "order_lines": "SKU-PUZZLE-500:1",
    }
    resp = client.post("/pack/verify", data=data, files=files)
    assert resp.status_code == 200
    html = resp.text
    assert "Unknown Scissors" in html
    assert "STOP" in html

    repo = PackRepository(org_id="org_demo_alpha")
    records = repo.list_records(unit_id="UNIT-EXTRA-OBJ-1")
    assert len(records) == 1
    extra_objects = records[0]["checks"]["_audit"]["extra_objects"]
    assert len(extra_objects) == 1
    assert extra_objects[0]["label"] == "Unknown Scissors"
    assert extra_objects[0]["attributes"] == "Red handle metal blades"
    assert extra_objects[0]["confidence"]["identity_confidence"] == 0.88
    assert extra_objects[0]["confidence"]["count_confidence"] == 0.90


# ----------------------------------------------------------------------------
# 2. Low-confidence unknown gives UNCERTAIN
# ----------------------------------------------------------------------------
def test_low_confidence_unknown_gives_uncertain():
    """When all extra objects have identity_confidence < threshold (0.75), nothing_extra is UNCERTAIN."""
    obs = ModelObservation(
        observed_items=[
            ObservedItem(
                label="Jigsaw Puzzle",
                visible_attributes="Blue box",
                matches_order_index=0,
                sku="SKU-PUZZLE-500",
                count=1,
                count_confidence=0.95,
                identity_confidence=0.95,
                partially_occluded=False,
                bbox=[10, 10, 100, 100],
            ),
            ObservedItem(
                label="Faint blurry shadow",
                visible_attributes="Dark blob",
                matches_order_index=None,
                sku=None,
                count=1,
                count_confidence=0.50,
                identity_confidence=0.45,  # < 0.75 threshold
                partially_occluded=False,
                bbox=[200.0, 200.0, 300.0, 300.0],
            ),
        ],
        unrecognised_items=[],
        image_quality=ImageQuality(usable=True, issues=[]),
        occlusion_suspected=False,
    )
    checks, verdict, action = evaluate_pack_box("SKU-PUZZLE-500:1", obs)

    assert checks["all_items_present"]["result"] == "PASS"
    assert checks["quantities_correct"]["result"] == "PASS"
    assert checks["nothing_extra"]["result"] == "UNCERTAIN"
    assert checks["nothing_extra"]["reason_code"] == "LOW_CONFIDENCE_EXTRA_ITEM"
    assert verdict == "UNCERTAIN"
    assert action == "STOP"


# ----------------------------------------------------------------------------
# 3. Confident extra fails even if another extra is low confidence
# ----------------------------------------------------------------------------
def test_confident_extra_fails_even_if_another_extra_is_low_confidence():
    """Amendment 3: If ANY extra object is confident, the check is FAIL (UNRECOGNISED_ITEMS_PRESENT)."""
    obs = ModelObservation(
        observed_items=[
            ObservedItem(
                label="Jigsaw Puzzle",
                matches_order_index=0,
                sku="SKU-PUZZLE-500",
                count=1,
                count_confidence=0.95,
                identity_confidence=0.95,
                bbox=[10, 10, 100, 100],
            ),
            ObservedItem(
                label="Low confidence smudge",
                matches_order_index=None,
                count=1,
                count_confidence=0.40,
                identity_confidence=0.50,  # Low confidence
                bbox=[50, 50, 80, 80],
            ),
            ObservedItem(
                label="Clear Screwdriver",
                matches_order_index=None,
                count=1,
                count_confidence=0.92,
                identity_confidence=0.91,  # Confident extra!
                bbox=[300, 300, 400, 400],
            ),
        ],
        unrecognised_items=[],
        image_quality=ImageQuality(usable=True, issues=[]),
        occlusion_suspected=False,
    )
    checks, verdict, action = evaluate_pack_box("SKU-PUZZLE-500:1", obs)

    assert checks["nothing_extra"]["result"] == "FAIL"
    assert checks["nothing_extra"]["reason_code"] == "UNRECOGNISED_ITEMS_PRESENT"
    assert "Clear Screwdriver" in checks["nothing_extra"]["reason"]
    assert verdict == "STOP_AND_FIX"


# ----------------------------------------------------------------------------
# 4. Missing ordered item gives FAIL
# ----------------------------------------------------------------------------
def test_missing_ordered_item_gives_fail():
    """When an ordered item has 0 observed count, all_items_present is FAIL (MISSING_ITEMS)."""
    obs = ModelObservation(
        observed_items=[
            ObservedItem(
                label="Water Bottle",
                matches_order_index=0,
                sku="SKU-BOTTLE-750",
                count=1,
                count_confidence=0.95,
                identity_confidence=0.95,
                bbox=[10, 10, 100, 100],
            )
            # SKU-PUZZLE-500 at index 1 is not observed at all
        ],
        unrecognised_items=[],
        image_quality=ImageQuality(usable=True, issues=[]),
        occlusion_suspected=False,
    )
    order = "SKU-BOTTLE-750:1, SKU-PUZZLE-500:1"
    checks, verdict, action = evaluate_pack_box(order, obs)

    assert checks["all_items_present"]["result"] == "FAIL"
    assert checks["all_items_present"]["reason_code"] == "MISSING_ITEMS"
    assert "SKU-PUZZLE-500" in checks["all_items_present"]["reason"]
    assert verdict == "STOP_AND_FIX"
    assert action == "STOP"


# ----------------------------------------------------------------------------
# 5. Wrong quantity gives FAIL
# ----------------------------------------------------------------------------
def test_wrong_quantity_gives_fail():
    """Short count gives SHORT_QUANTITY; surplus count gives SURPLUS_QUANTITY."""
    # Case A: Short count (expected 2, observed 1)
    obs_short = ModelObservation(
        observed_items=[
            ObservedItem(
                label="Mug",
                matches_order_index=0,
                sku="SKU-MUG-11",
                count=1,
                count_confidence=0.95,
                identity_confidence=0.95,
                bbox=[10, 10, 100, 100],
            )
        ],
        unrecognised_items=[],
        image_quality=ImageQuality(usable=True, issues=[]),
        occlusion_suspected=False,
    )
    checks_a, verdict_a, _ = evaluate_pack_box("SKU-MUG-11:2", obs_short)
    assert checks_a["all_items_present"]["result"] == "PASS"
    assert checks_a["quantities_correct"]["result"] == "FAIL"
    assert checks_a["quantities_correct"]["reason_code"] == "SHORT_QUANTITY"
    assert verdict_a == "STOP_AND_FIX"

    # Case B: Surplus count (expected 1, observed 3)
    obs_surplus = ModelObservation(
        observed_items=[
            ObservedItem(
                label="Mug",
                matches_order_index=0,
                sku="SKU-MUG-11",
                count=3,
                count_confidence=0.95,
                identity_confidence=0.95,
                bbox=[10, 10, 100, 100],
            )
        ],
        unrecognised_items=[],
        image_quality=ImageQuality(usable=True, issues=[]),
        occlusion_suspected=False,
    )
    checks_b, verdict_b, _ = evaluate_pack_box("SKU-MUG-11:1", obs_surplus)
    assert checks_b["quantities_correct"]["result"] == "FAIL"
    assert checks_b["quantities_correct"]["reason_code"] == "SURPLUS_QUANTITY"
    assert verdict_b == "STOP_AND_FIX"


# ----------------------------------------------------------------------------
# 6. Prompt contains names but no quantities
# ----------------------------------------------------------------------------
def test_prompt_contains_names_but_no_quantities():
    """Proves the prompt builder includes item titles/names but never order quantities."""
    adapter = GeminiVisionAdapter(api_key="fake_key")
    ordered_names = [
        "Stainless Steel Insulated Water Bottle 750ml",
        "Landscape Jigsaw Puzzle 500 Pieces",
    ]
    prompt = adapter._build_prompt(ordered_names)

    # Names must be in the prompt
    assert "[0] Stainless Steel Insulated Water Bottle 750ml" in prompt
    assert "[1] Landscape Jigsaw Puzzle 500 Pieces" in prompt

    # Specific prompt requirements
    assert "In the 'notes' field, list every distinct visible item you see in the box in free text first." in prompt
    assert "NEVER assume an ordered item is present" in prompt
    assert "Multiple photographs (if provided) are different angles/views of the SAME box" in prompt
    assert "matches_order_index" in prompt

    # No order quantities or SKU count syntax (e.g. ':1', ':2', 'qty:', 'quantity:')
    assert ":1" not in prompt
    assert ":2" not in prompt
    assert "quantity" not in prompt.lower() or "quantities" not in prompt.lower()


# ----------------------------------------------------------------------------
# 7. Multiple images make exactly ONE model call
# ----------------------------------------------------------------------------
def test_multiple_images_make_exactly_one_model_call():
    """Passing a list of 3 images to the adapter makes exactly one call."""
    mock = MockVisionAdapter()
    assert mock.call_count == 0

    img1 = create_test_image(size=(50, 50))
    img2 = create_test_image(size=(60, 60))
    img3 = create_test_image(size=(70, 70))

    obs, latency = mock.analyze_box(
        image_bytes=[img1, img2, img3],
        ordered_item_names=["Water Bottle 750ml"],
    )

    assert mock.call_count == 1
    assert latency > 0
    assert obs is not None


# ----------------------------------------------------------------------------
# 8. Occlusion downgrades a PASS
# ----------------------------------------------------------------------------
def test_occlusion_downgrades_a_pass():
    """All items and quantities present, but partially_occluded=True downgrades PASS to UNCERTAIN."""
    obs = ModelObservation(
        observed_items=[
            ObservedItem(
                label="Jigsaw Puzzle",
                matches_order_index=0,
                sku="SKU-PUZZLE-500",
                count=1,
                count_confidence=0.95,
                identity_confidence=0.95,
                partially_occluded=True,  # Occlusion flagged on item!
                bbox=[10, 10, 100, 100],
            )
        ],
        unrecognised_items=[],
        image_quality=ImageQuality(usable=True, issues=[]),
        occlusion_suspected=False,
    )
    checks, verdict, action = evaluate_pack_box("SKU-PUZZLE-500:1", obs)

    assert checks["all_items_present"]["result"] == "UNCERTAIN"
    assert checks["all_items_present"]["cause"] == "occlusion"
    assert verdict == "UNCERTAIN"
    assert action == "STOP"


# ----------------------------------------------------------------------------
# 9. Malformed JSON and timeouts fail open to PENDING
# ----------------------------------------------------------------------------
def test_malformed_json_and_timeouts_fail_open(client):
    """Malformed JSON or ModelTimeoutError in /pack/verify produces PENDING status with STOP action."""
    # A. Malformed JSON
    mock_parsing_err = MockVisionAdapter()
    # Simulate adapter returning hopelessly corrupt text
    def raise_parse(*args, **kwargs):
        raise ModelParsingError("Unrecoverable corrupt JSON syntax")
    mock_parsing_err.analyze_box = raise_parse
    set_adapter(mock_parsing_err)

    photo_bytes = create_test_image("JPEG")
    files = {"photo": ("box.jpg", photo_bytes, "image/jpeg")}
    data = {
        "order_id": "ORD-PARSE-FAIL",
        "unit_id": "UNIT-PARSE-FAIL",
        "order_lines": "SKU-BOTTLE-750:1",
    }
    resp = client.post("/pack/verify", data=data, files=files)
    assert resp.status_code == 200
    html = resp.text
    assert "PENDING" in html
    assert "STOP" in html
    assert "Could not verify" in html or "fail-open" in html.lower()

    # B. Model timeout
    mock_timeout = MockVisionAdapter(simulate_timeout=True)
    set_adapter(mock_timeout)

    files_b = {"photo": ("box.jpg", photo_bytes, "image/jpeg")}
    data_b = {
        "order_id": "ORD-TIMEOUT-FAIL",
        "unit_id": "UNIT-TIMEOUT-FAIL",
        "order_lines": "SKU-BOTTLE-750:1",
    }
    resp_b = client.post("/pack/verify", data=data_b, files=files_b)
    assert resp_b.status_code == 200
    html_b = resp_b.text
    assert "PENDING" in html_b
    assert "STOP" in html_b


# ----------------------------------------------------------------------------
# 10. Minimum confidence across detections matched to same ordered row
# ----------------------------------------------------------------------------
def test_minimum_confidence_across_detections_matched_to_same_ordered_row():
    """Requirement 4: Minimum confidence across items matched to the same ordered row is used."""
    # Two detections match index 0 (e.g. 2 bottles detected separately)
    # One has count_confidence 0.95, other has 0.60 (< 0.70 threshold)
    obs = ModelObservation(
        observed_items=[
            ObservedItem(
                label="Bottle 1",
                matches_order_index=0,
                sku="SKU-BOTTLE-750",
                count=1,
                count_confidence=0.95,
                identity_confidence=0.95,
                bbox=[10, 10, 100, 100],
            ),
            ObservedItem(
                label="Bottle 2",
                matches_order_index=0,
                sku="SKU-BOTTLE-750",
                count=1,
                count_confidence=0.60,  # Below 0.70 threshold!
                identity_confidence=0.90,
                bbox=[120, 120, 200, 200],
            ),
        ],
        unrecognised_items=[],
        image_quality=ImageQuality(usable=True, issues=[]),
        occlusion_suspected=False,
    )
    checks, verdict, action = evaluate_pack_box("SKU-BOTTLE-750:2", obs)

    # Count adds up to 2 (quantities match), but min count confidence is 0.60 < 0.70 threshold
    assert checks["quantities_correct"]["result"] == "UNCERTAIN"
    assert checks["quantities_correct"]["reason_code"] == "LOW_COUNT_CONFIDENCE"
    assert verdict == "UNCERTAIN"
    assert action == "STOP"


# ----------------------------------------------------------------------------
# 11. Multi-photo upload constraints (max 5 photos, Vercel 4.5 MB limit)
# ----------------------------------------------------------------------------
def test_multi_photo_upload_max_count_enforced(client):
    """Uploading more than 5 photos is rejected with HTTP 400 and Vercel limit explanation."""
    img_bytes = create_test_image("JPEG")
    files = [("photos", (f"box_{i}.jpg", img_bytes, "image/jpeg")) for i in range(6)]
    data = {
        "order_id": "ORD-MULTI-6",
        "unit_id": "UNIT-MULTI-6",
        "order_lines": "SKU-BOTTLE-750:1",
    }
    resp = client.post("/pack/verify", data=data, files=files)
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "maximum 5 photos allowed" in detail
    assert "Vercel" in detail


def test_multi_photo_upload_valid_renders_two_tables(client):
    """Uploading multiple photos (<= 5) succeeds and result renders 'Matches the order' and 'Not in the order' tables."""
    mock_obs = ModelObservation(
        observed_items=[
            ObservedItem(
                label="Insulated Water Bottle",
                matches_order_index=0,
                sku="SKU-BOTTLE-750",
                count=1,
                count_confidence=0.95,
                identity_confidence=0.95,
                bbox=[10, 10, 100, 100],
            ),
            ObservedItem(
                label="Packing Tape Dispenser",
                matches_order_index=None,
                count=1,
                count_confidence=0.92,
                identity_confidence=0.90,
                bbox=[200, 200, 300, 300],
            ),
        ],
        unrecognised_items=[],
        image_quality=ImageQuality(usable=True, issues=[]),
        occlusion_suspected=False,
    )
    set_adapter(MockVisionAdapter(default_observation=mock_obs))

    img1 = create_test_image("JPEG")
    img2 = create_test_image("JPEG")
    files = [
        ("photos", ("view_top.jpg", img1, "image/jpeg")),
        ("photos", ("view_side.jpg", img2, "image/jpeg")),
    ]
    data = {
        "order_id": "ORD-MULTI-2",
        "unit_id": "UNIT-MULTI-2",
        "order_lines": "SKU-BOTTLE-750:1",
    }
    resp = client.post("/pack/verify", data=data, files=files)
    assert resp.status_code == 200
    html = resp.text

    # Both tables must be present in the output
    assert "Matches the order" in html
    assert "Not in the order" in html
    assert "Packing Tape Dispenser" in html
    assert "2 photos captured" in html
