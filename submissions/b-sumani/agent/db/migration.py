"""Schema migration runner for Pack Manager.

Executes schema.sql using admin credentials to create tables, triggers,
and configure forced Row-Level Security.
"""

from __future__ import annotations
import os
import sys
from pathlib import Path
from agent.db.connection import get_admin_db_connection, is_live_db_configured


def run_migration() -> bool:
    """Reads and executes schema.sql using admin connection."""
    schema_path = Path(__file__).parent / "schema.sql"
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found at {schema_path}")
    
    sql = schema_path.read_text(encoding="utf-8")
    
    if not is_live_db_configured():
        print("Note: No live DATABASE_URL or SUPABASE credentials configured in .env.")
        print("Skipping live database migration. Migrations will run when DATABASE_URL is configured.")
        return False

    print("Connecting to database using admin credentials...")
    conn = get_admin_db_connection()
    try:
        with conn.cursor() as cur:
            print("Applying schema.sql...")
            cur.execute(sql)
        print("Migration applied successfully! Tables created and RLS forced.")
        return True
    finally:
        conn.close()


if __name__ == "__main__":
    success = run_migration()
    sys.exit(0 if success else 1)
