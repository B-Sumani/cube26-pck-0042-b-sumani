"""Tests for all-missing items, wrong photos, and empty observation handling.

Validates backend safety and one-home-per-check rules:
1. All ordered items missing: all_items_present is FAIL (MISSING_ITEMS),
   quantities_correct is PASS with reason_code DEFERRED_TO_PRESENCE_CHECK,
   verdict is STOP_AND_FIX.
2. Wrong photo (items with matches_order_index null): verdict is STOP_AND_FIX,
   observed items are preserved in not_in_order / extra_objects with label,
   visible_attributes, and count.
3. Model reports no items at all: verdict is STOP_AND_FIX, record keeps empty
   observed list without crashing.
"""

import io
from PIL import Image
import pytest

from agent.main import set_adapter
from agent.models.base import ObservedItem, ImageQuality, ModelObservation
from agent.models.mock import MockVisionAdapter
from agent.rules.evaluator import evaluate_pack_box
from agent.db.repo import PackRepository


def create_test_image(format="JPEG", size=(60, 60), color=(200, 200, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color=color).save(buf, format=format)
    return buf.getvalue()


# ----------------------------------------------------------------------------
# 1. All ordered items missing
# ----------------------------------------------------------------------------
def test_all_ordered_items_missing_defers_quantity_check():
    """All ordered items missing, interior visible, no occlusion:
    - all_items_present: FAIL (MISSING_ITEMS)
    - quantities_correct: PASS (DEFERRED_TO_PRESENCE_CHECK, one-home-per-check rule)
    - nothing_extra: PASS
    - verdict: STOP_AND_FIX
    """
    obs = ModelObservation(
        observed_items=[],
        unrecognised_items=[],
        image_quality=ImageQuality(usable=True, issues=[]),
        occlusion_suspected=False
    )
    order_lines = "SKU-BOOK-GGGM:1;SKU-SANITIZER-DETTOL:2"
    checks, verdict, action = evaluate_pack_box(order_lines, obs)

    # all_items_present holds the missing defect
    assert checks["all_items_present"]["result"] == "FAIL"
    assert checks["all_items_present"]["reason_code"] == "MISSING_ITEMS"
    assert checks["all_items_present"]["cause"] == "recognition"
    assert "SKU-BOOK-GGGM" in checks["all_items_present"]["reason"]
    assert "SKU-SANITIZER-DETTOL" in checks["all_items_present"]["reason"]

    # quantities_correct keeps result PASS with DEFERRED_TO_PRESENCE_CHECK to avoid double-penalty
    assert checks["quantities_correct"]["result"] == "PASS"
    assert checks["quantities_correct"]["reason_code"] == "DEFERRED_TO_PRESENCE_CHECK"
    assert "Quantity check deferred" in checks["quantities_correct"]["reason"]

    # nothing_extra is clean
    assert checks["nothing_extra"]["result"] == "PASS"

    # Box verdict is safely stopped
    assert verdict == "STOP_AND_FIX"
    assert action == "STOP"


# ----------------------------------------------------------------------------
# 2. Wrong photo (items with matches_order_index is null)
# ----------------------------------------------------------------------------
def test_wrong_photo_all_unmatched_items(client):
    """When the uploaded photo contains only items with matches_order_index=None:
    - Verdict is STOP_AND_FIX
    - Observed items are preserved in not_in_order / extra_objects with label, attributes, count
    """
    obs = ModelObservation(
        observed_items=[
            ObservedItem(
                label="Unrelated Tennis Ball",
                visible_attributes="Fuzzy yellow sphere",
                matches_order_index=None,
                sku=None,
                count=2,
                count_confidence=0.92,
                identity_confidence=0.95,
                partially_occluded=False,
                bbox=[100.0, 100.0, 300.0, 300.0]
            ),
            ObservedItem(
                label="Wrong Product Bottle",
                visible_attributes="Tall blue cylinder with pump",
                matches_order_index=None,
                sku=None,
                count=1,
                count_confidence=0.88,
                identity_confidence=0.90,
                partially_occluded=False,
                bbox=[400.0, 400.0, 800.0, 800.0]
            )
        ],
        unrecognised_items=[],
        image_quality=ImageQuality(usable=True, issues=[]),
        occlusion_suspected=False
    )
    order_lines = "SKU-BOOK-GGGM:1"

    # Evaluator direct check
    checks, verdict, action = evaluate_pack_box(order_lines, obs)
    assert verdict == "STOP_AND_FIX"
    assert action == "STOP"
    assert checks["all_items_present"]["result"] == "FAIL"
    assert checks["all_items_present"]["reason_code"] == "MISSING_ITEMS"
    assert checks["nothing_extra"]["result"] == "FAIL"
    assert checks["nothing_extra"]["reason_code"] == "UNRECOGNISED_ITEMS_PRESENT"

    # Webapp integration check via client
    set_adapter(MockVisionAdapter(default_observation=obs))
    photo_bytes = create_test_image("JPEG")
    files = {"photo": ("wrong_box.jpg", photo_bytes, "image/jpeg")}
    data = {
        "order_id": "ORD-WRONG-PHOTO-1",
        "unit_id": "UNIT-WRONG-PHOTO-1",
        "order_lines": order_lines,
    }
    resp = client.post("/pack/verify", data=data, files=files)
    assert resp.status_code == 200
    html = resp.text

    # The UI still displays what the model identified in the photo under "Not in the order"
    assert "Unrelated Tennis Ball" in html
    assert "Fuzzy yellow sphere" in html
    assert "Wrong Product Bottle" in html
    assert "Tall blue cylinder with pump" in html
    assert "STOP" in html

    # The persisted record preserves the observed items in extra_objects
    repo = PackRepository(org_id="org_demo_alpha")
    records = repo.list_records(unit_id="UNIT-WRONG-PHOTO-1")
    assert len(records) == 1
    assert records[0]["verdict"] == "STOP_AND_FIX"
    extra_objects = records[0]["checks"]["_audit"]["extra_objects"]
    assert len(extra_objects) == 2
    assert extra_objects[0]["label"] == "Unrelated Tennis Ball"
    assert extra_objects[0]["attributes"] == "Fuzzy yellow sphere"
    assert extra_objects[0]["count"] == 2
    assert extra_objects[1]["label"] == "Wrong Product Bottle"
    assert extra_objects[1]["attributes"] == "Tall blue cylinder with pump"
    assert extra_objects[1]["count"] == 1


# ----------------------------------------------------------------------------
# 3. Model reports no items at all (empty observation)
# ----------------------------------------------------------------------------
def test_model_reports_no_items_at_all(client):
    """When the model reports no items at all (empty box / empty observed_items):
    - Verdict is STOP_AND_FIX
    - Record keeps empty observed list without crashing
    """
    obs = ModelObservation(
        observed_items=[],
        unrecognised_items=[],
        image_quality=ImageQuality(usable=True, issues=[]),
        occlusion_suspected=False
    )
    order_lines = "SKU-BOOK-GGGM:1"

    # Evaluator direct check
    checks, verdict, action = evaluate_pack_box(order_lines, obs)
    assert verdict == "STOP_AND_FIX"
    assert action == "STOP"

    # Webapp integration check via client
    set_adapter(MockVisionAdapter(default_observation=obs))
    photo_bytes = create_test_image("JPEG")
    files = {"photo": ("empty_box.jpg", photo_bytes, "image/jpeg")}
    data = {
        "order_id": "ORD-EMPTY-BOX-1",
        "unit_id": "UNIT-EMPTY-BOX-1",
        "order_lines": order_lines,
    }
    resp = client.post("/pack/verify", data=data, files=files)
    assert resp.status_code == 200
    html = resp.text

    assert "STOP" in html
    assert "All Items Present" in html

    # The persisted record keeps an empty observed list without crashing
    repo = PackRepository(org_id="org_demo_alpha")
    records = repo.list_records(unit_id="UNIT-EMPTY-BOX-1")
    assert len(records) == 1
    assert records[0]["verdict"] == "STOP_AND_FIX"
    assert records[0]["observed_in_box"] in ("", "NONE")
    assert records[0]["checks"]["_audit"]["extra_objects"] == []
    assert records[0]["checks"]["_audit"]["observations"] == []
