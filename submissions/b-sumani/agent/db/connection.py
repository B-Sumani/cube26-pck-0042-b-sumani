"""Database connection manager for Pack Manager.

Supports:
1. Direct PostgreSQL connection via psycopg (admin role for migrations, pack_app_user for app queries).
2. Supabase client via supabase-py (anon key for app queries with RLS, service role for migrations/admin).
3. In-memory RLS-enforcing test engine for offline verification when external DB is unconfigured.
"""

from __future__ import annotations
import os
import contextlib
from typing import Optional, Dict, Any, Generator
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
DATABASE_APP_URL = os.getenv("DATABASE_APP_URL")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")


def is_live_db_configured() -> bool:
    """Check if a live PostgreSQL or Supabase database is configured."""
    return bool(DATABASE_URL or (SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY))


def get_admin_db_connection():
    """Returns a direct psycopg connection with admin / DDL privileges.
    
    Used strictly for schema migrations, table creation, and setting up RLS policies.
    NEVER use this connection for tenant-scoped application queries.
    """
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL is not set. Configure it in .env to connect to Postgres.")
    import psycopg
    conn = psycopg.connect(DATABASE_URL, autocommit=True)
    return conn


def get_app_db_connection(org_id: Optional[str] = None):
    """Returns a direct psycopg connection for tenant-scoped application queries.
    
    Uses DATABASE_APP_URL (non-bypass role pack_app_user).
    Row-Level Security is strictly enforced because pack_app_user:
    1. Is NOT a superuser (rolsuper = false)
    2. Does NOT have BYPASSRLS (rolbypassrls = false)
    3. Is NOT the owner of the tables
    """
    url = DATABASE_APP_URL or DATABASE_URL
    if not url:
        raise ValueError("Neither DATABASE_APP_URL nor DATABASE_URL is set in .env.")
    import psycopg
    conn = psycopg.connect(url)
    
    # If connecting using the primary URL, switch to the unprivileged pack_app_user role
    if not DATABASE_APP_URL and DATABASE_URL:
        with conn.cursor() as cur:
            cur.execute("SET ROLE pack_app_user;")
    return conn


@contextlib.contextmanager
def tenant_db_session(org_id: str) -> Generator[Any, None, None]:
    """Context manager executing database queries strictly scoped to org_id under RLS.
    
    IMPORTANT POOLING HYGIENE:
    Uses `SET LOCAL app.current_org_id = %s` inside an explicit transaction block (`with conn.transaction()`).
    In PostgreSQL, `SET LOCAL` only lasts for the duration of the current transaction block.
    Upon COMMIT or ROLLBACK, the setting is discarded by the server, preventing any cross-tenant
    parameter leakage when using connection poolers (PgBouncer, Supabase Pooler, etc.).
    """
    conn = get_app_db_connection(org_id)
    try:
        with conn.transaction():
            with conn.cursor() as cur:
                # Scoped to this transaction only
                cur.execute("SET LOCAL app.current_org_id = %s;", (org_id,))
                yield cur
    finally:
        conn.close()


def get_supabase_admin_client():
    """Returns Supabase client with service_role key.
    
    ADMIN ONLY: Used for schema setups, bucket creation.
    Never used for tenant-scoped data queries!
    """
    if not (SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY):
        raise ValueError("SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not configured in .env.")
    from supabase import create_client, Client
    client: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    return client


def get_supabase_app_client(org_id: str):
    """Returns Supabase client with non-bypass anon key and org_id context.
    
    RLS is enforced by PostgREST. The service key is NOT used here.
    """
    if not (SUPABASE_URL and SUPABASE_ANON_KEY):
        raise ValueError("SUPABASE_URL or SUPABASE_ANON_KEY not configured in .env.")
    from supabase import create_client, Client
    from supabase.lib.client_options import ClientOptions
    
    options = ClientOptions(
        headers={
            "X-Org-Id": org_id,
            "apikey": SUPABASE_ANON_KEY
        }
    )
    client: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY, options=options)
    return client
