-- Schema for Pack Manager (Round 2 Cube Buildathon)
-- Enforces tenancy isolation, row-level security (RLS) on every table,
-- and append-only overrides.

-- 1. Organizations
CREATE TABLE IF NOT EXISTS orgs (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. Users
CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(64) PRIMARY KEY,
    org_id VARCHAR(64) NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    email VARCHAR(255),
    role VARCHAR(50) NOT NULL DEFAULT 'operator',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3. Captures (Open-box photograph captures before sealing)
CREATE TABLE IF NOT EXISTS captures (
    id VARCHAR(64) PRIMARY KEY,
    org_id VARCHAR(64) NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    unit_id VARCHAR(32) NOT NULL,
    order_id VARCHAR(64) NOT NULL,
    photo_keys TEXT[] NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    operator_id VARCHAR(64) NOT NULL
);

-- 4. Records (Pack evidence records with checks, verdict, status)
CREATE TABLE IF NOT EXISTS records (
    id VARCHAR(64) PRIMARY KEY,
    org_id VARCHAR(64) NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    unit_id VARCHAR(32) NOT NULL,
    capture_id VARCHAR(64) NOT NULL REFERENCES captures(id) ON DELETE CASCADE,
    order_lines TEXT NOT NULL,
    observed_in_box TEXT,
    checks JSONB NOT NULL DEFAULT '{}'::jsonb,
    verdict VARCHAR(20) CHECK (verdict IN ('SEAL', 'STOP_AND_FIX', 'UNCERTAIN')),
    status VARCHAR(20) NOT NULL CHECK (status IN ('completed', 'pending')),
    model VARCHAR(64),
    model_latency_ms INTEGER,
    content_hash VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_pending_verdict_null CHECK (
        (status = 'pending' AND verdict IS NULL) OR
        (status = 'completed' AND verdict IS NOT NULL)
    )
);

-- Index for unit_id joins across the buildathon pods
CREATE INDEX IF NOT EXISTS idx_records_unit_id ON records(unit_id);
CREATE INDEX IF NOT EXISTS idx_records_org_id ON records(org_id);
CREATE INDEX IF NOT EXISTS idx_captures_unit_id ON captures(unit_id);

-- 5. Overrides (Append-only record of human operator disagreement)
CREATE TABLE IF NOT EXISTS overrides (
    id VARCHAR(64) PRIMARY KEY,
    org_id VARCHAR(64) NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    record_id VARCHAR(64) NOT NULL REFERENCES records(id) ON DELETE CASCADE,
    original_verdict VARCHAR(20) NOT NULL,
    new_verdict VARCHAR(20) NOT NULL CHECK (new_verdict IN ('SEAL', 'STOP_AND_FIX')),
    reason TEXT NOT NULL,
    operator_id VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Trigger to guarantee append-only integrity for overrides (no UPDATE or DELETE)
CREATE OR REPLACE FUNCTION prevent_override_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'overrides table is append-only. Updates and deletes are strictly forbidden.';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_prevent_override_mutation ON overrides;
CREATE TRIGGER trg_prevent_override_mutation
    BEFORE UPDATE OR DELETE ON overrides
    FOR EACH ROW
    EXECUTE FUNCTION prevent_override_mutation();

-- 6. Eval Runs (Benchmark tracking)
CREATE TABLE IF NOT EXISTS eval_runs (
    id VARCHAR(64) PRIMARY KEY,
    org_id VARCHAR(64) NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    dataset_name VARCHAR(100) NOT NULL,
    model_name VARCHAR(64) NOT NULL,
    total_units INTEGER NOT NULL,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 7. Eval Items (Per-unit benchmark predictions vs ground truth)
CREATE TABLE IF NOT EXISTS eval_items (
    id VARCHAR(64) PRIMARY KEY,
    eval_run_id VARCHAR(64) NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
    org_id VARCHAR(64) NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    unit_id VARCHAR(32) NOT NULL,
    ground_truth JSONB NOT NULL,
    predicted JSONB NOT NULL,
    is_match BOOLEAN NOT NULL,
    cause VARCHAR(32) CHECK (cause IN ('occlusion', 'recognition', 'timeout', 'error')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- ROW LEVEL SECURITY (RLS) - FORCED ON EVERY TABLE
-- ============================================================================

ALTER TABLE orgs ENABLE ROW LEVEL SECURITY;
ALTER TABLE orgs FORCE ROW LEVEL SECURITY;

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;

ALTER TABLE captures ENABLE ROW LEVEL SECURITY;
ALTER TABLE captures FORCE ROW LEVEL SECURITY;

ALTER TABLE records ENABLE ROW LEVEL SECURITY;
ALTER TABLE records FORCE ROW LEVEL SECURITY;

ALTER TABLE overrides ENABLE ROW LEVEL SECURITY;
ALTER TABLE overrides FORCE ROW LEVEL SECURITY;

ALTER TABLE eval_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE eval_runs FORCE ROW LEVEL SECURITY;

ALTER TABLE eval_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE eval_items FORCE ROW LEVEL SECURITY;

-- Helper function to retrieve the active tenant org_id from the session setting
-- or from the Supabase JWT auth claim if present
CREATE OR REPLACE FUNCTION current_org_id()
RETURNS VARCHAR AS $$
BEGIN
    RETURN COALESCE(
        NULLIF(current_setting('app.current_org_id', true), ''),
        NULLIF(current_setting('request.jwt.claim.org_id', true), '')
    );
END;
$$ LANGUAGE plpgsql STABLE;

-- Application Role Setup (Non-Superuser, Non-BypassRLS role)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pack_app_user') THEN
        CREATE ROLE pack_app_user WITH LOGIN PASSWORD 'pack_app_secret_pass';
    END IF;
END $$;

GRANT USAGE ON SCHEMA public TO pack_app_user;
GRANT SELECT, INSERT, UPDATE ON orgs, users, captures, records, eval_runs, eval_items TO pack_app_user;
-- Note: Overrides table only gets SELECT and INSERT. Never UPDATE or DELETE.
GRANT SELECT, INSERT ON overrides TO pack_app_user;

-- Drop existing policies if any
DROP POLICY IF EXISTS orgs_isolation ON orgs;
DROP POLICY IF EXISTS users_isolation ON users;
DROP POLICY IF EXISTS captures_isolation ON captures;
DROP POLICY IF EXISTS records_isolation ON records;
DROP POLICY IF EXISTS overrides_isolation ON overrides;
DROP POLICY IF EXISTS eval_runs_isolation ON eval_runs;
DROP POLICY IF EXISTS eval_items_isolation ON eval_items;

-- Tenant Isolation Policies
CREATE POLICY orgs_isolation ON orgs
    FOR ALL
    TO PUBLIC
    USING (id = current_org_id())
    WITH CHECK (id = current_org_id());

CREATE POLICY users_isolation ON users
    FOR ALL
    TO PUBLIC
    USING (org_id = current_org_id())
    WITH CHECK (org_id = current_org_id());

CREATE POLICY captures_isolation ON captures
    FOR ALL
    TO PUBLIC
    USING (org_id = current_org_id())
    WITH CHECK (org_id = current_org_id());

CREATE POLICY records_isolation ON records
    FOR ALL
    TO PUBLIC
    USING (org_id = current_org_id())
    WITH CHECK (org_id = current_org_id());

CREATE POLICY overrides_isolation ON overrides
    FOR ALL
    TO PUBLIC
    USING (org_id = current_org_id())
    WITH CHECK (org_id = current_org_id());

CREATE POLICY eval_runs_isolation ON eval_runs
    FOR ALL
    TO PUBLIC
    USING (org_id = current_org_id())
    WITH CHECK (org_id = current_org_id());

CREATE POLICY eval_items_isolation ON eval_items
    FOR ALL
    TO PUBLIC
    USING (org_id = current_org_id())
    WITH CHECK (org_id = current_org_id());
