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

    expected_tables = ["orgs", "users", "captures", "records", "overrides", "eval_runs", "eval_items"]
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
