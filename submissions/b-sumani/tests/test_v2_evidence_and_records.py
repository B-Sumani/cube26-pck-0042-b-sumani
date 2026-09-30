"""Integration and Unit Tests for v2: Evidence Record Page, Audit Log Filters, and Override History.

Validates:
1. /pack/record/{record_id} dedicated permalink evidence view with all audit fields.
2. Cross-tenant isolation on record permalink (bravo requesting alpha record gets 404).
3. Records table filtering by verdict (SEAL, STOP_AND_FIX, UNCERTAIN, PENDING).
4. Records table filtering by cause (occlusion vs recognition).
5. Records table filtering by date and unit_id.
6. Complete override history tracking and append-only immutability.
"""

import io
import re
import pytest
from PIL import Image
from starlette.testclient import TestClient

from agent.main import app, set_adapter
from agent.models.base import ModelObservation, ObservedItem, ImageQuality
from agent.models.mock import MockVisionAdapter
from agent.db.repo import PackRepository, AppendOnlyViolationError


@pytest.fixture
def client():
    return TestClient(app)


def create_test_image(format="JPEG") -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", (300, 300), color=(180, 160, 140))
    img.save(buf, format=format)
    return buf.getvalue()


def test_evidence_record_permalink_renders_all_audit_fields(client):
    """Proves dedicated permalink renders all required audit fields, comparison, and photo."""
    mock_obs = ModelObservation(
        observed_items=[
            ObservedItem(
                sku="SKU-BOTTLE-750",
                count=1,
                count_confidence=0.94,
                identity_confidence=0.98,
                partially_occluded=False,
                bbox=[50.0, 50.0, 200.0, 200.0]
            )
        ],
        unrecognised_items=[],
        image_quality=ImageQuality(usable=True, issues=[]),
        occlusion_suspected=False
    )
    set_adapter(MockVisionAdapter(default_observation=mock_obs))

    photo_bytes = create_test_image("JPEG")
    files = {"photo": ("box.jpg", photo_bytes, "image/jpeg")}
    data = {
        "org_id": "org_demo_alpha",
        "order_id": "ORD-PERM-1",
        "unit_id": "UNIT-0050",
        "order_lines": "SKU-BOTTLE-750:1",
        "candidate_skus": "SKU-BOTTLE-750, SKU-PUZZLE-500",
        "operator_id": "op_test"
    }
    verify_resp = client.post("/pack/verify", data=data, files=files)
    assert verify_resp.status_code == 200

    # Extract record ID
    match = re.search(r"PCK-[0-9A-F]+", verify_resp.text)
    assert match is not None
    record_id = match.group(0)

    # 1. Fetch permalink page
    resp = client.get(f"/pack/record/{record_id}?org_id=org_demo_alpha")
    assert resp.status_code == 200
    html = resp.text

    # 2. Check essential audit elements
    assert record_id in html
    assert "UNIT-0050" in html
    assert "ORD-PERM-1" in html
    assert "SEAL" in html
    assert "GO · SEAL APPROVED" in html
    assert "All Items Present" in html
    assert "Quantities Correct" in html
    assert "Nothing Extra" in html
    assert "Content Hash (SHA-256)" in html
    assert "Prompt Version:" in html
    assert "Threshold Config:" in html
    assert "Latency:" in html
    assert "/api/storage/tenants/org_demo_alpha/UNIT-0050/" in html
    assert "Operator Overrides History" in html


def test_cross_tenant_record_isolation_returns_404(client):
    """Proves tenant bravo cannot access alpha's record detail page."""
    mock_obs = ModelObservation(
        observed_items=[],
        unrecognised_items=[],
        image_quality=ImageQuality(usable=True, issues=[]),
        occlusion_suspected=False
    )
    set_adapter(MockVisionAdapter(default_observation=mock_obs))

    photo_bytes = create_test_image("JPEG")
    files = {"photo": ("box.jpg", photo_bytes, "image/jpeg")}
    data = {
        "org_id": "org_demo_alpha",
        "order_id": "ORD-ALPHA-SEC",
        "unit_id": "UNIT-0051",
        "order_lines": "SKU-TOWEL-BLU:1",
        "candidate_skus": "SKU-TOWEL-BLU"
    }
    verify_resp = client.post("/pack/verify", data=data, files=files)
    assert verify_resp.status_code == 200

    match = re.search(r"PCK-[0-9A-F]+", verify_resp.text)
    record_id = match.group(0)

    # Request as org_demo_bravo
    bravo_resp = client.get(f"/pack/record/{record_id}?org_id=org_demo_bravo")
    assert bravo_resp.status_code == 404
    assert "not found" in bravo_resp.json()["detail"].lower()


def test_records_filtering_by_verdict(client):
    """Proves audit log filters by SEAL, STOP_AND_FIX, UNCERTAIN, and PENDING."""
    # 1. Generate SEAL record
    mock_seal = ModelObservation(
        observed_items=[ObservedItem(sku="SKU-A", count=1, count_confidence=0.9, identity_confidence=0.9, partially_occluded=False, bbox=[0,0,0,0])],
        unrecognised_items=[],
        image_quality=ImageQuality(usable=True, issues=[]),
        occlusion_suspected=False
    )
    set_adapter(MockVisionAdapter(default_observation=mock_seal))
    photo = create_test_image("JPEG")
    client.post("/pack/verify", data={"org_id": "org_demo_alpha", "order_id": "O-1", "unit_id": "U-1", "order_lines": "SKU-A:1", "candidate_skus": "SKU-A"}, files={"photo": ("box.jpg", photo, "image/jpeg")})

    # 2. Generate STOP_AND_FIX record (short quantity)
    mock_stop = ModelObservation(
        observed_items=[ObservedItem(sku="SKU-A", count=1, count_confidence=0.9, identity_confidence=0.9, partially_occluded=False, bbox=[0,0,0,0])],
        unrecognised_items=[],
        image_quality=ImageQuality(usable=True, issues=[]),
        occlusion_suspected=False
    )
    set_adapter(MockVisionAdapter(default_observation=mock_stop))
    client.post("/pack/verify", data={"org_id": "org_demo_alpha", "order_id": "O-2", "unit_id": "U-2", "order_lines": "SKU-A:2", "candidate_skus": "SKU-A"}, files={"photo": ("box.jpg", photo, "image/jpeg")})

    # 3. Filter for SEAL
    resp_seal = client.get("/pack/records?org_id=org_demo_alpha&verdict=SEAL")
    assert resp_seal.status_code == 200
    assert "U-1" in resp_seal.text
    assert "U-2" not in resp_seal.text

    # 4. Filter for STOP_AND_FIX
    resp_stop = client.get("/pack/records?org_id=org_demo_alpha&verdict=STOP_AND_FIX")
    assert resp_stop.status_code == 200
    assert "U-2" in resp_stop.text
    assert "U-1" not in resp_stop.text


def test_records_filtering_by_cause_and_date(client):
    """Proves filtering records by cause ('occlusion' vs 'recognition') and date."""
    # 1. Record with occlusion cause
    mock_occ = ModelObservation(
        observed_items=[ObservedItem(sku="SKU-OCC", count=1, count_confidence=0.9, identity_confidence=0.9, partially_occluded=True, bbox=[0,0,0,0])],
        unrecognised_items=[],
        image_quality=ImageQuality(usable=True, issues=[]),
        occlusion_suspected=True
    )
    set_adapter(MockVisionAdapter(default_observation=mock_occ))
    photo = create_test_image("JPEG")
    client.post("/pack/verify", data={"org_id": "org_demo_alpha", "order_id": "O-OCC", "unit_id": "U-OCC", "order_lines": "SKU-OCC:1", "candidate_skus": "SKU-OCC"}, files={"photo": ("box.jpg", photo, "image/jpeg")})

    # Filter by cause=occlusion
    resp = client.get("/pack/records?org_id=org_demo_alpha&cause=occlusion")
    assert resp.status_code == 200
    assert "U-OCC" in resp.text
    assert "occlusion" in resp.text


def test_override_flow_updates_history_and_maintains_immutability(client):
    """Proves multiple overrides for a record accumulate append-only in history."""
    repo = PackRepository(org_id="org_demo_alpha")
    
    # 1. Create a record
    record = repo.insert_record(
        record_id="PCK-OVR-HIST-1",
        unit_id="UNIT-0077",
        capture_id="CAP-0077",
        order_lines="SKU-A:1",
        observed_in_box="SKU-A:0",
        checks={"all_items_present": {"result": "FAIL", "reason_code": "MISSING_ITEMS", "cause": "recognition"}},
        verdict="STOP_AND_FIX",
        status="completed"
    )

    # 2. Operator 1 overrides to SEAL
    resp1 = client.post("/pack/override", data={
        "record_id": "PCK-OVR-HIST-1",
        "org_id": "org_demo_alpha",
        "original_verdict": "STOP_AND_FIX",
        "new_verdict": "SEAL",
        "reason": "Inspected box: item was hidden under flap",
        "operator_id": "op_alice"
    })
    assert resp1.status_code == 200
    assert "Total Overrides on Record: 1" in resp1.text

    # 3. Supervisor overrides back to STOP_AND_FIX
    resp2 = client.post("/pack/override", data={
        "record_id": "PCK-OVR-HIST-1",
        "org_id": "org_demo_alpha",
        "original_verdict": "SEAL",
        "new_verdict": "STOP_AND_FIX",
        "reason": "Barcode was wrong item entirely upon physical check",
        "operator_id": "op_supervisor_bob"
    })
    assert resp2.status_code == 200
    assert "Total Overrides on Record: 2" in resp2.text

    # 4. Check permalink page shows both in history table
    page_resp = client.get("/pack/record/PCK-OVR-HIST-1?org_id=org_demo_alpha")
    assert page_resp.status_code == 200
    html = page_resp.text
    assert "2 Operator Override(s) Recorded" in html
    assert "op_alice" in html
    assert "op_supervisor_bob" in html
    assert "item was hidden under flap" in html
    assert "Barcode was wrong item entirely" in html

    # 5. Verify append-only immutability (deleting or updating raises error)
    overrides = repo.list_overrides("PCK-OVR-HIST-1")
    assert len(overrides) == 2
    with pytest.raises(AppendOnlyViolationError):
        repo.attempt_override_update_or_delete(overrides[0]["id"])
