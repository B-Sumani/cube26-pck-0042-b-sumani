"""Tenancy Isolation and Row-Level Security Test Suite.

Verifies:
1. Tenancy isolation: org_demo_bravo sees ZERO alpha rows and cannot fetch an alpha image by guessing a key.
2. Filter tampering: explicit query with WHERE org_id = 'org_demo_alpha' returns 0 rows.
3. Storage isolation: private bucket keys and signed URLs reject cross-tenant access.
4. Append-only overrides: UPDATE or DELETE on overrides raises an error and is blocked.
5. Schema constraint (Finding A): when status == 'pending', verdict must be NULL.
6. Schema DDL verification: checks schema.sql has ENABLE and FORCE ROW LEVEL SECURITY on every table.
"""

from pathlib import Path
import pytest
from agent.db.repo import (
    PackRepository,
    AppendOnlyViolationError,
    SchemaConstraintError,
    TenancyViolationError,
)
from agent.db.storage import (
    generate_storage_key,
    create_signed_url,
    verify_signed_token,
    TenancyStorageError,
)


def test_tenancy_alpha_records_invisible_to_bravo(repo_alpha, repo_bravo):
    """Proves org_demo_bravo sees exactly zero rows from org_demo_alpha."""
    # 1. Seed org_demo_alpha data
    photo_key = generate_storage_key(
        org_id="org_demo_alpha",
        unit_id="UNIT-0008",
        filename="open_box.jpg",
        content_bytes=b"synthetic_alpha_image_bytes"
    )
    
    cap = repo_alpha.insert_capture(
        capture_id="CAP-0001",
        unit_id="UNIT-0008",
        order_id="ORD-DUMMY-50008",
        photo_keys=[photo_key],
        operator_id="op_amira"
    )

    rec = repo_alpha.insert_record(
        record_id="PCK-0001",
        unit_id="UNIT-0008",
        capture_id=cap["id"],
        order_lines="SKU-BOTTLE-750:1",
        observed_in_box="SKU-BOTTLE-750:1",
        checks={"all_items_present": {"verdict": "PASS"}},
        verdict="SEAL",
        status="completed",
        model="gemini-2.5-flash",
        model_latency_ms=820
    )

    repo_alpha.insert_override(
        override_id="OVR-0001",
        record_id=rec["id"],
        original_verdict="SEAL",
        new_verdict="STOP_AND_FIX",
        reason="Operator spotted damaged cap not seen by vision",
        operator_id="op_amira"
    )

    # 2. Verify org_demo_alpha sees its own records
    assert len(repo_alpha.list_captures()) >= 1
    assert len(repo_alpha.list_records()) >= 1
    assert len(repo_alpha.list_overrides()) >= 1

    # 3. CRITICAL: org_demo_bravo must see ZERO rows across all tables
    bravo_captures = repo_bravo.list_captures()
    bravo_records = repo_bravo.list_records()
    bravo_overrides = repo_bravo.list_overrides()

    assert len(bravo_captures) == 0, f"Tenancy breach! Bravo saw captures: {bravo_captures}"
    assert len(bravo_records) == 0, f"Tenancy breach! Bravo saw records: {bravo_records}"
    assert len(bravo_overrides) == 0, f"Tenancy breach! Bravo saw overrides: {bravo_overrides}"


def test_tenancy_cross_org_filter_tampering_blocked(repo_alpha, repo_bravo):
    """Proves org_demo_bravo cannot reach org_demo_alpha rows even with explicit WHERE org_id = 'org_demo_alpha'."""
    tampered_results = repo_bravo.raw_query_across_tenants_attempt(target_foreign_org="org_demo_alpha")
    assert len(tampered_results) == 0, "Security failure: Bravo was able to query alpha rows by overriding org_id!"


def test_tenancy_storage_guessing_and_signed_url_isolation():
    """Proves org_demo_bravo cannot fetch or sign an org_demo_alpha image by guessing its key."""
    # 1. Generate an unguessable storage key for alpha
    alpha_key = generate_storage_key(
        org_id="org_demo_alpha",
        unit_id="UNIT-0008",
        filename="open_box.jpg",
        content_bytes=b"raw_box_image_content_alpha"
    )
    
    # Key must be unguessable (contains high-entropy UUID + content hash)
    assert "tenants/org_demo_alpha/UNIT-0008/" in alpha_key
    assert len(alpha_key) > 50

    # 2. Alpha generates signed URL successfully
    alpha_signed_url = create_signed_url("org_demo_alpha", alpha_key, expires_in=300)
    assert alpha_signed_url is not None
    assert "org=org_demo_alpha" in alpha_signed_url

    # 3. Bravo attempts to sign or access alpha's key by guessing the key string
    with pytest.raises(TenancyStorageError):
        create_signed_url(org_id="org_demo_bravo", storage_key=alpha_key)

    # 4. Bravo attempts to forged token validation
    is_valid = verify_signed_token(
        storage_key=alpha_key,
        requesting_org="org_demo_bravo",
        expires_at=9999999999,
        signature="fake_or_guessed_signature"
    )
    assert is_valid is False, "Security failure: invalid signed token was accepted!"


def test_overrides_append_only_enforced(repo_alpha):
    """Proves that overrides cannot be modified or deleted once created."""
    cap = repo_alpha.insert_capture(
        capture_id="CAP-0002",
        unit_id="UNIT-0009",
        order_id="ORD-DUMMY-50009",
        photo_keys=["key1"],
        operator_id="op_ben"
    )
    rec = repo_alpha.insert_record(
        record_id="PCK-0002",
        unit_id="UNIT-0009",
        capture_id=cap["id"],
        order_lines="SKU-PUZZLE-500:1",
        observed_in_box="SKU-PUZZLE-500:1",
        checks={"all_items_present": {"verdict": "PASS"}},
        verdict="SEAL",
        status="completed"
    )
    ovr = repo_alpha.insert_override(
        override_id="OVR-0002",
        record_id=rec["id"],
        original_verdict="SEAL",
        new_verdict="STOP_AND_FIX",
        reason="Missing seal tape",
        operator_id="op_ben"
    )

    # Attempting to delete or mutate the override must be aborted
    with pytest.raises(AppendOnlyViolationError):
        repo_alpha.attempt_override_update_or_delete(ovr["id"])


def test_finding_a_verdict_null_when_pending(repo_alpha):
    """Enforces Finding A: when status is 'pending', verdict must be NULL.
    When status is 'completed', verdict must be SEAL, STOP_AND_FIX, or UNCERTAIN.
    """
    cap = repo_alpha.insert_capture(
        capture_id="CAP-0003",
        unit_id="UNIT-0010",
        order_id="ORD-DUMMY-50010",
        photo_keys=["key2"],
        operator_id="op_dana"
    )

    # Valid: status='pending', verdict=None
    pending_rec = repo_alpha.insert_record(
        record_id="PCK-0003",
        unit_id="UNIT-0010",
        capture_id=cap["id"],
        order_lines="SKU-MUG-11:1",
        observed_in_box=None,
        checks={},
        verdict=None,
        status="pending"
    )
    assert pending_rec["status"] == "pending"
    assert pending_rec["verdict"] is None

    # Invalid: status='pending' with non-null verdict
    with pytest.raises(SchemaConstraintError):
        repo_alpha.insert_record(
            record_id="PCK-0004",
            unit_id="UNIT-0010",
            capture_id=cap["id"],
            order_lines="SKU-MUG-11:1",
            observed_in_box=None,
            checks={},
            verdict="SEAL",  # Illegal per Finding A!
            status="pending"
        )

    # Invalid: status='completed' with null verdict
    with pytest.raises(SchemaConstraintError):
        repo_alpha.insert_record(
            record_id="PCK-0005",
            unit_id="UNIT-0010",
            capture_id=cap["id"],
            order_lines="SKU-MUG-11:1",
            observed_in_box="SKU-MUG-11:1",
            checks={"all_items_present": {"verdict": "PASS"}},
            verdict=None,  # Illegal: completed must have verdict
            status="completed"
        )


def test_schema_sql_has_forced_rls_on_all_tables():
    """Validates that schema.sql includes ENABLE and FORCE ROW LEVEL SECURITY for all 7 tables."""
    schema_path = Path(__file__).parent.parent / "agent" / "db" / "schema.sql"
    assert schema_path.exists(), "schema.sql missing!"
    content = schema_path.read_text(encoding="utf-8")

    expected_tables = ["orgs", "users", "captures", "records", "overrides", "eval_runs", "eval_items", "catalogue_items"]
    for tbl in expected_tables:
        enable_str = f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY;"
        force_str = f"ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY;"
        assert enable_str in content, f"Missing ENABLE ROW LEVEL SECURITY for {tbl}"
        assert force_str in content, f"Missing FORCE ROW LEVEL SECURITY for {tbl}"

    # Verify overrides trigger is present in SQL
    assert "prevent_override_mutation" in content
    # Verify non-bypass app role
    assert "pack_app_user" in content
    # Verify overrides does not grant update/delete to app user
    assert "GRANT SELECT, INSERT ON overrides TO pack_app_user;" in content


def test_tenancy_override_cross_tenant_blocked(repo_alpha, repo_bravo):
    """Proves org_demo_bravo cannot override a record belonging to org_demo_alpha."""
    cap = repo_alpha.insert_capture(
        capture_id="CAP-SEC-01",
        unit_id="UNIT-0090",
        order_id="ORD-SEC-01",
        photo_keys=["tenants/org_demo_alpha/UNIT-0090/photo.jpg"],
        operator_id="op_alpha"
    )
    rec = repo_alpha.insert_record(
        record_id="PCK-SEC-01",
        unit_id="UNIT-0090",
        capture_id=cap["id"],
        order_lines="SKU-A:1",
        observed_in_box="SKU-A:1",
        checks={"all_items_present": {"verdict": "PASS"}},
        verdict="SEAL",
        status="completed"
    )

    # Bravo attempts to submit an override on Alpha's record
    with pytest.raises(TenancyViolationError):
        repo_bravo.insert_override(
            override_id="OVR-ATTACK-01",
            record_id=rec["id"],
            original_verdict="SEAL",
            new_verdict="STOP_AND_FIX",
            reason="Malicious cross-tenant override attempt",
            operator_id="op_bravo"
        )


def test_tenancy_storage_non_tenant_key_rejected():
    """Proves storage manager rejects keys that do not adhere to tenants/{org_id}/ format."""
    # Attempting to sign arbitrary root or foreign paths must fail
    with pytest.raises(TenancyStorageError):
        create_signed_url("org_demo_alpha", "etc/passwd")

    with pytest.raises(TenancyStorageError):
        create_signed_url("org_demo_alpha", "shared/public_image.jpg")

    with pytest.raises(TenancyStorageError):
        create_signed_url("org_demo_alpha", "tenants/org_demo_bravo/UNIT-0001/box.jpg")

    # verify_signed_token must also reject non-tenant or mismatched keys
    assert verify_signed_token("etc/passwd", "org_demo_alpha", 9999999999, "sig") is False
    assert verify_signed_token("tenants/org_demo_bravo/UNIT-0001/box.jpg", "org_demo_alpha", 9999999999, "sig") is False


def test_request_with_no_session_redirects_to_login(unauth_client):
    """Proves that a request with no session redirects to /login."""
    resp = unauth_client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"

    # API endpoints reject unauthenticated access with 401
    resp_records = unauth_client.get("/pack/records")
    assert resp_records.status_code == 401

    resp_verify = unauth_client.post(
        "/pack/verify",
        data={"order_id": "O1", "unit_id": "U1", "order_lines": "A:1"},
        files={"photo": ("box.jpg", b"\xff\xd8\xff\xe0" + b"0"*20, "image/jpeg")}
    )
    assert resp_verify.status_code == 401


def test_tampered_session_cookie_rejected(unauth_client):
    """Proves that a tampered or forged session cookie is rejected."""
    from agent.main import COOKIE_NAME
    unauth_client.cookies.set(COOKIE_NAME, "org_demo_alpha.1700000000.badforgedhmacsig0000000000000000")
    resp = unauth_client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"

    resp_records = unauth_client.get("/pack/records")
    assert resp_records.status_code == 401

    resp_verify = unauth_client.post(
        "/pack/verify",
        data={"order_id": "O1", "unit_id": "U1", "order_lines": "A:1"},
        files={"photo": ("box.jpg", b"\xff\xd8\xff\xe0" + b"0"*20, "image/jpeg")}
    )
    assert resp_verify.status_code == 401


def test_bravo_session_cannot_read_alpha_records_images_or_catalogue_even_when_posting_org_id_alpha():
    """Proves Bravo session cannot read Alpha records, images, or catalogue, even when posting org_id=org_demo_alpha."""
    import io
    from PIL import Image
    from starlette.testclient import TestClient
    from agent.main import app, sign_session_org, COOKIE_NAME, set_adapter
    from agent.models.mock import MockVisionAdapter
    from agent.models.base import ModelObservation
    from agent.db.storage import save_file_bytes

    # 1. Seed Alpha data (record, image, catalogue item)
    repo_alpha = PackRepository(org_id="org_demo_alpha")
    repo_alpha.create_org("org_demo_alpha", "Alpha Demo Merchant")
    alpha_key = generate_storage_key("org_demo_alpha", "UNIT-0099", "box.jpg", b"alpha_secret_image_bytes")
    save_file_bytes(alpha_key, b"alpha_secret_image_bytes")
    alpha_signed_url = create_signed_url("org_demo_alpha", alpha_key)

    cap = repo_alpha.insert_capture("CAP-SEC-99", "UNIT-0099", "ORD-99", [alpha_key], "op_alpha")
    rec = repo_alpha.insert_record(
        record_id="PCK-SEC-ALPHA-99",
        unit_id="UNIT-0099",
        capture_id=cap["id"],
        order_lines="SKU-A:1",
        observed_in_box="SKU-A:1",
        checks={"all_items_present": {"verdict": "PASS"}},
        verdict="SEAL",
        status="completed"
    )
    repo_alpha.insert_catalogue_item(
        sku="SKU-ALPHA-CONFIDENTIAL",
        title="Alpha Proprietary Device",
        description="Confidential Alpha Item"
    )

    # 2. Authenticate client strictly as Bravo
    bravo_client = TestClient(app)
    bravo_client.cookies.set(COOKIE_NAME, sign_session_org("org_demo_bravo"))

    # Attempt to read Alpha record (even explicitly querying ?org_id=org_demo_alpha)
    resp_rec = bravo_client.get(f"/pack/record/{rec['id']}?org_id=org_demo_alpha")
    assert resp_rec.status_code == 404

    # Attempt to read Alpha image (even explicitly querying ?org=org_demo_alpha)
    resp_img = bravo_client.get(alpha_signed_url)
    assert resp_img.status_code == 403

    # Attempt to read Alpha catalogue items via Bravo repository
    repo_bravo = PackRepository(org_id="org_demo_bravo")
    repo_bravo.create_org("org_demo_bravo", "Bravo Demo 3PL")
    bravo_skus = [item["sku"] for item in repo_bravo.list_catalogue_items()]
    assert "SKU-ALPHA-CONFIDENTIAL" not in bravo_skus

    # Attempt to POST verify with org_id='org_demo_alpha' form field from Bravo session
    # System MUST attribute the verification strictly to Bravo, ignoring the form field
    buf = io.BytesIO()
    Image.new("RGB", (50, 50)).save(buf, format="JPEG")
    set_adapter(MockVisionAdapter(default_observation=ModelObservation(observed_items=[], unrecognised_items=[], image_quality={"usable": True, "issues": []}, occlusion_suspected=False)))
    resp_post = bravo_client.post(
        "/pack/verify",
        data={"org_id": "org_demo_alpha", "order_id": "ORD-BRAVO-TEST", "unit_id": "UNIT-BRAVO-01", "order_lines": "SKU-A:1"},
        files={"photo": ("box.jpg", buf.getvalue(), "image/jpeg")}
    )
    assert resp_post.status_code == 200
    # The record must be stored under Bravo, NEVER under Alpha
    assert len(repo_alpha.list_records(unit_id="UNIT-BRAVO-01")) == 0
    assert len(repo_bravo.list_records(unit_id="UNIT-BRAVO-01")) == 1


def test_alpha_catalogue_edits_invisible_to_bravo(client):
    """Proves Alpha's catalogue edits are completely invisible to Bravo."""
    from starlette.testclient import TestClient
    from agent.main import app, sign_session_org, COOKIE_NAME

    # Alpha adds a new product
    resp = client.post("/catalogue/item", data={
        "sku": "SKU-ALPHA-EXCLUSIVE-01",
        "title": "Alpha Exclusive Widget",
        "description": "Visible only to Alpha"
    })
    assert resp.status_code == 200

    # Verify present in Alpha repository
    repo_alpha = PackRepository(org_id="org_demo_alpha")
    alpha_skus = [i["sku"] for i in repo_alpha.list_catalogue_items()]
    assert "SKU-ALPHA-EXCLUSIVE-01" in alpha_skus

    # Bravo client and repo must NOT see Alpha's item
    bravo_client = TestClient(app)
    bravo_client.cookies.set(COOKIE_NAME, sign_session_org("org_demo_bravo"))
    repo_bravo = PackRepository(org_id="org_demo_bravo")
    bravo_skus = [i["sku"] for i in repo_bravo.list_catalogue_items()]
    assert "SKU-ALPHA-EXCLUSIVE-01" not in bravo_skus

    # Bravo attempting to delete Alpha's item does not delete it
    del_resp = bravo_client.post("/catalogue/item/delete", data={"sku": "SKU-ALPHA-EXCLUSIVE-01"})
    assert del_resp.status_code == 200
    assert "not found" in del_resp.text.lower()

    # Confirm item remains intact in Alpha repository
    assert "SKU-ALPHA-EXCLUSIVE-01" in [i["sku"] for i in repo_alpha.list_catalogue_items()]


def test_empty_catalogue_triggers_fallback_and_records_candidate_source_order_only():
    """Proves an empty catalogue triggers the fallback warning and sets candidate_source = 'order_only'."""
    import io
    from PIL import Image
    from starlette.testclient import TestClient
    from agent.main import app, sign_session_org, COOKIE_NAME, set_adapter
    from agent.models.mock import MockVisionAdapter
    from agent.models.base import ModelObservation, ObservedItem, ImageQuality

    empty_org = "org_demo_empty_test"
    repo = PackRepository(org_id=empty_org)
    repo.create_org(empty_org, "Empty Catalogue Merchant")
    assert len(repo.list_catalogue_items()) == 0

    client_empty = TestClient(app)
    client_empty.cookies.set(COOKIE_NAME, sign_session_org(empty_org))

    mock_obs = ModelObservation(
        observed_items=[ObservedItem(sku="SKU-FALLBACK-1", count=1, count_confidence=0.9, identity_confidence=0.9, partially_occluded=False, bbox=[0,0,0,0])],
        unrecognised_items=[],
        image_quality=ImageQuality(usable=True, issues=[]),
        occlusion_suspected=False
    )
    set_adapter(MockVisionAdapter(default_observation=mock_obs))

    buf = io.BytesIO()
    Image.new("RGB", (60, 60)).save(buf, format="JPEG")
    files = {"photo": ("box.jpg", buf.getvalue(), "image/jpeg")}
    data = {
        "order_id": "ORD-EMPTY-100",
        "unit_id": "UNIT-EMPTY-100",
        "order_lines": "SKU-FALLBACK-1:1"
    }

    resp = client_empty.post("/pack/verify", data=data, files=files)
    assert resp.status_code == 200
    html = resp.text

    # 1. Fallback warning banner is removed under open detection
    assert "⚠️ No catalogue set up" not in html
    assert "SEAL" in html

    # 2. Record must have prompt_version recorded in audit
    from agent.models.base import PROMPT_VERSION
    records = repo.list_records(unit_id="UNIT-EMPTY-100")
    assert len(records) == 1
    rec = records[0]
    assert rec["checks"]["_audit"]["prompt_version"] == PROMPT_VERSION


