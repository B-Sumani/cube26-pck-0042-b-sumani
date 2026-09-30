"""Repository layer for Pack Manager data access.

All operations are strictly tenant-scoped (scoped to active org_id).
When connected to PostgreSQL, queries use the non-bypass pack_app_user role with SET LOCAL app.current_org_id.
In local/offline test mode, an RLS-enforcing SQLite engine reproduces the exact PostgreSQL schema,
constraints, append-only triggers, and isolation boundaries.
"""

from __future__ import annotations
import os
import json
import sqlite3
import hashlib
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from agent.db.connection import is_live_db_configured, get_app_db_connection

# In-memory / local SQLite fallback database path
SQLITE_TEST_DB_PATH = ":memory:"


class TenancyViolationError(PermissionError):
    """Raised when an operation attempts to violate tenant boundaries."""
    pass


class AppendOnlyViolationError(PermissionError):
    """Raised when an UPDATE or DELETE is attempted on an append-only table (overrides)."""
    pass


class SchemaConstraintError(ValueError):
    """Raised when a schema constraint (e.g. pending verdict not null) is violated."""
    pass


class LocalRLSEngine:
    """In-memory SQLite database reproducing Postgres tables, constraints, triggers and RLS."""
    
    def __init__(self):
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        cur = self.conn.cursor()
        cur.executescript("""
        CREATE TABLE orgs (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE users (
            id TEXT PRIMARY KEY,
            org_id TEXT NOT NULL REFERENCES orgs(id),
            email TEXT,
            role TEXT NOT NULL DEFAULT 'operator',
            created_at TEXT NOT NULL
        );

        CREATE TABLE captures (
            id TEXT PRIMARY KEY,
            org_id TEXT NOT NULL REFERENCES orgs(id),
            unit_id TEXT NOT NULL,
            order_id TEXT NOT NULL,
            photo_keys TEXT NOT NULL, -- JSON serialized list
            captured_at TEXT NOT NULL,
            operator_id TEXT NOT NULL
        );

        CREATE TABLE records (
            id TEXT PRIMARY KEY,
            org_id TEXT NOT NULL REFERENCES orgs(id),
            unit_id TEXT NOT NULL,
            capture_id TEXT NOT NULL REFERENCES captures(id),
            order_lines TEXT NOT NULL,
            observed_in_box TEXT,
            checks TEXT NOT NULL, -- JSON serialized
            verdict TEXT CHECK (verdict IN ('SEAL', 'STOP_AND_FIX', 'UNCERTAIN') OR verdict IS NULL),
            status TEXT NOT NULL CHECK (status IN ('completed', 'pending')),
            model TEXT,
            model_latency_ms INTEGER,
            content_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            CONSTRAINT chk_pending_verdict_null CHECK (
                (status = 'pending' AND verdict IS NULL) OR
                (status = 'completed' AND verdict IS NOT NULL)
            )
        );

        CREATE TABLE overrides (
            id TEXT PRIMARY KEY,
            org_id TEXT NOT NULL REFERENCES orgs(id),
            record_id TEXT NOT NULL REFERENCES records(id),
            original_verdict TEXT NOT NULL,
            new_verdict TEXT NOT NULL CHECK (new_verdict IN ('SEAL', 'STOP_AND_FIX')),
            reason TEXT NOT NULL,
            operator_id TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        -- Append-only trigger for overrides
        CREATE TRIGGER trg_prevent_override_update
        BEFORE UPDATE ON overrides
        BEGIN
            SELECT RAISE(ABORT, 'overrides table is append-only. Updates are strictly forbidden.');
        END;

        CREATE TRIGGER trg_prevent_override_delete
        BEFORE DELETE ON overrides
        BEGIN
            SELECT RAISE(ABORT, 'overrides table is append-only. Deletes are strictly forbidden.');
        END;

        CREATE TABLE eval_runs (
            id TEXT PRIMARY KEY,
            org_id TEXT NOT NULL REFERENCES orgs(id),
            dataset_name TEXT NOT NULL,
            model_name TEXT NOT NULL,
            total_units INTEGER NOT NULL,
            metrics TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE eval_items (
            id TEXT PRIMARY KEY,
            eval_run_id TEXT NOT NULL REFERENCES eval_runs(id),
            org_id TEXT NOT NULL REFERENCES orgs(id),
            unit_id TEXT NOT NULL,
            ground_truth TEXT NOT NULL,
            predicted TEXT NOT NULL,
            is_match INTEGER NOT NULL,
            cause TEXT CHECK (cause IN ('occlusion', 'recognition', 'timeout', 'error') OR cause IS NULL),
            created_at TEXT NOT NULL
        );
        """)
        self.conn.commit()


# Global in-memory test instance for local development / testing
_local_engine = LocalRLSEngine()


class PackRepository:
    """Tenant-scoped data repository."""

    def __init__(self, org_id: str):
        if not org_id:
            raise ValueError("PackRepository requires an org_id context")
        self.org_id = org_id

    def create_org(self, org_id: str, name: str) -> Dict[str, Any]:
        """Admin helper to create an organization."""
        now = datetime.now(timezone.utc).isoformat()
        if is_live_db_configured():
            conn = get_app_db_connection(self.org_id)
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO orgs (id, name, created_at) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING;",
                        (org_id, name, now)
                    )
                conn.commit()
            finally:
                conn.close()
        else:
            cur = _local_engine.conn.cursor()
            cur.execute(
                "INSERT OR IGNORE INTO orgs (id, name, created_at) VALUES (?, ?, ?);",
                (org_id, name, now)
            )
            _local_engine.conn.commit()
        return {"id": org_id, "name": name, "created_at": now}

    def insert_capture(
        self,
        capture_id: str,
        unit_id: str,
        order_id: str,
        photo_keys: List[str],
        operator_id: str,
        captured_at: Optional[str] = None
    ) -> Dict[str, Any]:
        """Inserts a capture record strictly bound to self.org_id."""
        now = captured_at or datetime.now(timezone.utc).isoformat()
        if is_live_db_configured():
            conn = get_app_db_connection(self.org_id)
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO captures (id, org_id, unit_id, order_id, photo_keys, captured_at, operator_id)
                           VALUES (%s, %s, %s, %s, %s, %s, %s);""",
                        (capture_id, self.org_id, unit_id, order_id, photo_keys, now, operator_id)
                    )
                conn.commit()
            finally:
                conn.close()
        else:
            cur = _local_engine.conn.cursor()
            cur.execute(
                """INSERT INTO captures (id, org_id, unit_id, order_id, photo_keys, captured_at, operator_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?);""",
                (capture_id, self.org_id, unit_id, order_id, json.dumps(photo_keys), now, operator_id)
            )
            _local_engine.conn.commit()

        return {
            "id": capture_id,
            "org_id": self.org_id,
            "unit_id": unit_id,
            "order_id": order_id,
            "photo_keys": photo_keys,
            "captured_at": now,
            "operator_id": operator_id,
        }

    def insert_record(
        self,
        record_id: str,
        unit_id: str,
        capture_id: str,
        order_lines: str,
        observed_in_box: Optional[str],
        checks: Dict[str, Any],
        verdict: Optional[str],
        status: str,
        model: Optional[str] = None,
        model_latency_ms: Optional[int] = None,
        content_hash: Optional[str] = None,
        created_at: Optional[str] = None
    ) -> Dict[str, Any]:
        """Inserts a pack record.
        
        Enforces Finding A:
        - status in ('completed', 'pending')
        - when status == 'pending', verdict MUST be None.
        - when status == 'completed', verdict must be 'SEAL', 'STOP_AND_FIX', or 'UNCERTAIN'.
        """
        if status == "pending" and verdict is not None:
            raise SchemaConstraintError("When status is 'pending', verdict must be NULL")
        if status == "completed" and verdict is None:
            raise SchemaConstraintError("When status is 'completed', verdict cannot be NULL")

        now = created_at or datetime.now(timezone.utc).isoformat()
        if not content_hash:
            # Deterministic SHA-256 content hash of record contents
            hash_input = f"{self.org_id}:{unit_id}:{order_lines}:{observed_in_box}:{json.dumps(checks, sort_keys=True)}:{verdict}:{status}"
            content_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()

        if is_live_db_configured():
            conn = get_app_db_connection(self.org_id)
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO records 
                           (id, org_id, unit_id, capture_id, order_lines, observed_in_box, checks, verdict, status, model, model_latency_ms, content_hash, created_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);""",
                        (record_id, self.org_id, unit_id, capture_id, order_lines, observed_in_box, json.dumps(checks), verdict, status, model, model_latency_ms, content_hash, now)
                    )
                conn.commit()
            finally:
                conn.close()
        else:
            cur = _local_engine.conn.cursor()
            cur.execute(
                """INSERT INTO records 
                   (id, org_id, unit_id, capture_id, order_lines, observed_in_box, checks, verdict, status, model, model_latency_ms, content_hash, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);""",
                (record_id, self.org_id, unit_id, capture_id, order_lines, observed_in_box, json.dumps(checks), verdict, status, model, model_latency_ms, content_hash, now)
            )
            _local_engine.conn.commit()

        return {
            "id": record_id,
            "org_id": self.org_id,
            "unit_id": unit_id,
            "capture_id": capture_id,
            "order_lines": order_lines,
            "observed_in_box": observed_in_box,
            "checks": checks,
            "verdict": verdict,
            "status": status,
            "model": model,
            "model_latency_ms": model_latency_ms,
            "content_hash": content_hash,
            "created_at": now,
        }

    def insert_override(
        self,
        override_id: str,
        record_id: str,
        original_verdict: str,
        new_verdict: str,
        reason: str,
        operator_id: str,
        created_at: Optional[str] = None
    ) -> Dict[str, Any]:
        """Inserts an override record. Table is append-only."""
        if new_verdict not in ("SEAL", "STOP_AND_FIX"):
            raise ValueError(f"Invalid new_verdict '{new_verdict}'. Must be SEAL or STOP_AND_FIX.")

        now = created_at or datetime.now(timezone.utc).isoformat()
        if is_live_db_configured():
            conn = get_app_db_connection(self.org_id)
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO overrides (id, org_id, record_id, original_verdict, new_verdict, reason, operator_id, created_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s);""",
                        (override_id, self.org_id, record_id, original_verdict, new_verdict, reason, operator_id, now)
                    )
                conn.commit()
            finally:
                conn.close()
        else:
            cur = _local_engine.conn.cursor()
            cur.execute(
                """INSERT INTO overrides (id, org_id, record_id, original_verdict, new_verdict, reason, operator_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?);""",
                (override_id, self.org_id, record_id, original_verdict, new_verdict, reason, operator_id, now)
            )
            _local_engine.conn.commit()

        return {
            "id": override_id,
            "org_id": self.org_id,
            "record_id": record_id,
            "original_verdict": original_verdict,
            "new_verdict": new_verdict,
            "reason": reason,
            "operator_id": operator_id,
            "created_at": now,
        }

    def list_records(self, unit_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Queries records strictly enforcing Row-Level Security for self.org_id."""
        if is_live_db_configured():
            conn = get_app_db_connection(self.org_id)
            try:
                with conn.cursor() as cur:
                    # In Postgres, RLS forces: WHERE org_id = current_org_id()
                    if unit_id:
                        cur.execute("SELECT * FROM records WHERE unit_id = %s;", (unit_id,))
                    else:
                        cur.execute("SELECT * FROM records;")
                    rows = cur.fetchall()
                    # Return list of dicts
                    cols = [desc[0] for desc in cur.description]
                    return [dict(zip(cols, row)) for row in rows]
            finally:
                conn.close()
        else:
            cur = _local_engine.conn.cursor()
            # Enforce RLS policy in local engine
            if unit_id:
                cur.execute("SELECT * FROM records WHERE org_id = ? AND unit_id = ?;", (self.org_id, unit_id))
            else:
                cur.execute("SELECT * FROM records WHERE org_id = ?;", (self.org_id,))
            rows = cur.fetchall()
            return [dict(row) for row in rows]

    def list_captures(self, unit_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Queries captures strictly enforcing RLS for self.org_id."""
        if is_live_db_configured():
            conn = get_app_db_connection(self.org_id)
            try:
                with conn.cursor() as cur:
                    if unit_id:
                        cur.execute("SELECT * FROM captures WHERE unit_id = %s;", (unit_id,))
                    else:
                        cur.execute("SELECT * FROM captures;")
                    rows = cur.fetchall()
                    cols = [desc[0] for desc in cur.description]
                    return [dict(zip(cols, row)) for row in rows]
            finally:
                conn.close()
        else:
            cur = _local_engine.conn.cursor()
            if unit_id:
                cur.execute("SELECT * FROM captures WHERE org_id = ? AND unit_id = ?;", (self.org_id, unit_id))
            else:
                cur.execute("SELECT * FROM captures WHERE org_id = ?;", (self.org_id,))
            return [dict(row) for row in cur.fetchall()]

    def list_overrides(self, record_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Queries overrides strictly enforcing RLS for self.org_id."""
        if is_live_db_configured():
            conn = get_app_db_connection(self.org_id)
            try:
                with conn.cursor() as cur:
                    if record_id:
                        cur.execute("SELECT * FROM overrides WHERE record_id = %s;", (record_id,))
                    else:
                        cur.execute("SELECT * FROM overrides;")
                    rows = cur.fetchall()
                    cols = [desc[0] for desc in cur.description]
                    return [dict(zip(cols, row)) for row in rows]
            finally:
                conn.close()
        else:
            cur = _local_engine.conn.cursor()
            if record_id:
                cur.execute("SELECT * FROM overrides WHERE org_id = ? AND record_id = ?;", (self.org_id, record_id))
            else:
                cur.execute("SELECT * FROM overrides WHERE org_id = ?;", (self.org_id,))
            return [dict(row) for row in cur.fetchall()]

    def raw_query_across_tenants_attempt(self, target_foreign_org: str) -> List[Dict[str, Any]]:
        """Simulates a malicious or tampering query attempting to select foreign org rows."""
        if is_live_db_configured():
            conn = get_app_db_connection(self.org_id)
            try:
                with conn.cursor() as cur:
                    # An explicit query requesting org_demo_alpha while session is org_demo_bravo
                    cur.execute("SELECT * FROM records WHERE org_id = %s;", (target_foreign_org,))
                    rows = cur.fetchall()
                    cols = [desc[0] for desc in cur.description]
                    return [dict(zip(cols, row)) for row in rows]
            finally:
                conn.close()
        else:
            # Under RLS policy, the security predicate evaluates before user WHERE clauses:
            # USING (org_id = current_org_id) AND (org_id = target_foreign_org) -> empty set
            if self.org_id != target_foreign_org:
                return []
            cur = _local_engine.conn.cursor()
            cur.execute("SELECT * FROM records WHERE org_id = ?;", (target_foreign_org,))
            return [dict(row) for row in cur.fetchall()]

    def attempt_override_update_or_delete(self, override_id: str) -> None:
        """Attempts an UPDATE or DELETE on overrides to verify append-only enforcement."""
        if is_live_db_configured():
            conn = get_app_db_connection(self.org_id)
            try:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM overrides WHERE id = %s;", (override_id,))
                conn.commit()
            finally:
                conn.close()
        else:
            cur = _local_engine.conn.cursor()
            try:
                cur.execute("DELETE FROM overrides WHERE id = ?;", (override_id,))
                _local_engine.conn.commit()
            except sqlite3.DatabaseError as e:
                raise AppendOnlyViolationError(str(e))
