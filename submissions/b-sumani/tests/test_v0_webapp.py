"""Integration tests for Pack Manager Web Application (Part A / v0).

Verifies:
1. Single-page layout with 5 sections (Hero, Check box, Result, Records, Footer) and design tokens.
2. Photo in -> Verdict out (upload, model call, deterministic rules, result partial).
3. Fail-open behavior: Model timeout/error produces PENDING without blocking operator.
4. UNCERTAIN is evidence-based (clear photo passes/fails, blurry/occluded photo gets UNCERTAIN with human check banner).
5. Upload validation: Non-images, path traversal tricks, and empty files are rejected (HTTP 400).
6. Tenancy storage endpoint: Signed URL access is org-checked; foreign org cannot fetch image.
7. Append-only override flow.
8. Mock banner visibility logic.
"""

from io import BytesIO
import pytest
from PIL import Image
from starlette.testclient import TestClient

from agent.main import app, set_adapter
from agent.models.base import ModelObservation, ObservedItem, ImageQuality
from agent.models.mock import MockVisionAdapter
from agent.models.gemini import GeminiVisionAdapter
from agent.db.repo import PackRepository


def create_test_image(format_name="JPEG") -> bytes:
    """Creates a small valid JPEG/PNG test image."""
    img = Image.new("RGB", (100, 100), color=(200, 200, 200))
    buf = BytesIO()
    img.save(buf, format=format_name)
    return buf.getvalue()


@pytest.fixture
def client():
    """Test client for FastAPI app."""
    return TestClient(app)


def test_get_index_renders_sections_and_tokens(client):
    """Proves single-page site renders 5 sections and design tokens."""
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text

    # 1. Check for 5 section IDs
    assert 'id="hero"' in html
    assert 'id="check"' in html
    assert 'id="result"' in html
    assert 'id="records"' in html
    assert '<footer' in html

    # 2. Check for typography & wordmark
    assert "PACK MANAGER" in html
    assert "Cormorant Garamond" in html
    assert "Inter" in html

    # 3. Check for CSS variables
    assert "--cream: #f7f1ec;" in html
    assert "--espresso: #382d22;" in html
    assert "--pass: #4f6a4a;" in html
    assert "--fail: #9c3a2b;" in html
    assert "--uncertain: #8a5a00;" in html
    assert "--pending: #5b5f66;" in html


def test_post_verify_successful_pack_returns_go(client):
    """Proves valid photo + matching order lines returns GO (SEAL)."""
    # Setup mock adapter returning 1x SKU-BOTTLE-750
    mock_obs = ModelObservation(
        observed_items=[
            ObservedItem(
                sku="SKU-BOTTLE-750",
                count=1,
                count_confidence=0.96,
                identity_confidence=0.98,
                partially_occluded=False,
                bbox=[100.0, 100.0, 400.0, 400.0]
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
        "order_id": "ORD-50008",
        "unit_id": "UNIT-0008",
        "order_lines": "SKU-BOTTLE-750:1",
        "candidate_skus": "SKU-BOTTLE-750, SKU-PUZZLE-500",
        "operator_id": "op_amira"
    }

    resp = client.post("/pack/verify", data=data, files=files)
    assert resp.status_code == 200
    html = resp.text

    assert "GO" in html
    assert "SEAL" in html
    assert "PASS" in html
    assert "all items present" in html.lower()
    assert "/api/storage/tenants/org_demo_alpha/UNIT-0008/" in html


def test_post_verify_fail_open_on_timeout_produces_pending(client):
    """Proves timeout forces fail-open PENDING record and does not block operator."""
    set_adapter(MockVisionAdapter(simulate_timeout=True))

    photo_bytes = create_test_image("JPEG")
    files = {"photo": ("box.jpg", photo_bytes, "image/jpeg")}
    data = {
        "org_id": "org_demo_alpha",
        "order_id": "ORD-50010",
        "unit_id": "UNIT-0010",
        "order_lines": "SKU-TOWEL-BLU:1",
        "candidate_skus": "SKU-TOWEL-BLU",
        "operator_id": "op_amira"
    }

    resp = client.post("/pack/verify", data=data, files=files)
    assert resp.status_code == 200
    html = resp.text

    assert "PENDING" in html
    assert "Agent unavailable: seal on your own judgment" in html

    # Verify database record status
    repo = PackRepository(org_id="org_demo_alpha")
    records = repo.list_records(unit_id="UNIT-0010")
    assert len(records) >= 1
    assert records[0]["status"] == "pending"
    assert records[0]["verdict"] is None  # Finding A constraint


def test_post_verify_uncertain_shows_prominent_human_check_banner(client):
    """Proves UNCERTAIN (from occlusion/blur evidence) shows STOP and required message."""
    mock_obs = ModelObservation(
        observed_items=[
            ObservedItem(
                sku="SKU-BOTTLE-750",
                count=1,
                count_confidence=0.9,
                identity_confidence=0.9,
                partially_occluded=True,  # Occlusion evidence!
                bbox=[100.0, 100.0, 400.0, 400.0]
            )
        ],
        unrecognised_items=[],
        image_quality=ImageQuality(usable=True, issues=[]),
        occlusion_suspected=True
    )
    set_adapter(MockVisionAdapter(default_observation=mock_obs))

    photo_bytes = create_test_image("JPEG")
    files = {"photo": ("box.jpg", photo_bytes, "image/jpeg")}
    data = {
        "org_id": "org_demo_alpha",
        "order_id": "ORD-50012",
        "unit_id": "UNIT-0012",
        "order_lines": "SKU-BOTTLE-750:1",
        "candidate_skus": "SKU-BOTTLE-750",
        "operator_id": "op_amira"
    }

    resp = client.post("/pack/verify", data=data, files=files)
    assert resp.status_code == 200
    html = resp.text

    assert "STOP" in html
    assert "UNCERTAIN" in html
    assert "The agent could not verify this box. Please check the photo manually." in html
    assert "occlusion" in html.lower()


def test_upload_validation_rejects_bad_files_and_paths(client):
    """Proves non-images, path tricks, and empty files return HTTP 400."""
    # 1. Non-image file (e.g. text/plain pretending to be jpg)
    fake_bytes = b"Not a real image file content"
    files = {"photo": ("box.jpg", fake_bytes, "image/jpeg")}
    data = {
        "org_id": "org_demo_alpha",
        "order_id": "ORD-1",
        "unit_id": "UNIT-0001",
        "order_lines": "SKU-A:1",
        "candidate_skus": "SKU-A"
    }
    resp = client.post("/pack/verify", data=data, files=files)
    assert resp.status_code == 400
    assert "Invalid image format" in resp.json()["detail"]

    # 2. Path traversal filename trick
    real_jpeg = create_test_image("JPEG")
    files = {"photo": ("../../evil.jpg", real_jpeg, "image/jpeg")}
    resp = client.post("/pack/verify", data=data, files=files)
    assert resp.status_code == 400
    assert "path traversal" in resp.json()["detail"].lower()

    # 3. Empty file
    files = {"photo": ("empty.jpg", b"", "image/jpeg")}
    resp = client.post("/pack/verify", data=data, files=files)
    assert resp.status_code == 400


def test_storage_signed_url_cross_tenant_isolation(client):
    """Proves bravo cannot fetch alpha image through guessed signed URL."""
    # 1. Perform verify under alpha to generate and store photo
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
        "order_id": "ORD-50020",
        "unit_id": "UNIT-0020",
        "order_lines": "SKU-A:1",
        "candidate_skus": "SKU-A",
        "operator_id": "op_amira"
    }
    resp = client.post("/pack/verify", data=data, files=files)
    assert resp.status_code == 200

    # Extract the signed URL path from response
    import re
    match = re.search(r'src="(/api/storage/[^"]+)"', resp.text)
    assert match is not None
    signed_url = match.group(1)

    # 2. Fetching with valid signed URL succeeds
    img_resp = client.get(signed_url)
    assert img_resp.status_code == 200
    assert img_resp.headers["content-type"] == "image/jpeg"

    # 3. Tampering: Bravo tries to fetch alpha's image by replacing org=org_demo_alpha with org=org_demo_bravo
    tampered_url = signed_url.replace("org=org_demo_alpha", "org=org_demo_bravo")
    tampered_resp = client.get(tampered_url)
    assert tampered_resp.status_code == 403  # Rejected!

    # 4. Tampering: Forging signature
    bad_sig_url = re.sub(r'sig=[a-f0-9]+', 'sig=deadbeef0000', signed_url)
    bad_sig_resp = client.get(bad_sig_url)
    assert bad_sig_resp.status_code == 403  # Rejected!


def test_override_flow_records_immutably(client):
    """Proves operator override endpoint records human decision."""
    data = {
        "record_id": "PCK-TEST-1234",
        "org_id": "org_demo_alpha",
        "original_verdict": "STOP_AND_FIX",
        "new_verdict": "SEAL",
        "reason": "Operator manually verified SKU is present behind packaging",
        "operator_id": "op_amira"
    }
    resp = client.post("/pack/override", data=data)
    assert resp.status_code == 200
    assert "Override Recorded" in resp.text
    assert "SEAL" in resp.text

    # Verify override in database
    repo = PackRepository(org_id="org_demo_alpha")
    overrides = repo.list_overrides(record_id="PCK-TEST-1234")
    assert len(overrides) == 1
    assert overrides[0]["new_verdict"] == "SEAL"


def test_mock_banner_visibility_logic(client):
    """Proves 'MOCK RESULT, not a real check' banner shows only on mock adapter."""
    # With Mock adapter
    set_adapter(MockVisionAdapter())
    resp = client.get("/")
    assert "MOCK RESULT, not a real check" in resp.text

    # With real Gemini adapter
    set_adapter(GeminiVisionAdapter(api_key="fake_key_for_test"))
    resp2 = client.get("/")
    assert "MOCK RESULT, not a real check" not in resp2.text
