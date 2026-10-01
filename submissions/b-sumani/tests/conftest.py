"""Pytest configuration and shared fixtures for Pack Manager."""

import sys
import os
from pathlib import Path
import pytest

os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-offline-suites-99")

# Ensure submissions/b-sumani is in sys.path
BASE_DIR = Path(__file__).parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from agent.db.repo import PackRepository


@pytest.fixture
def repo_alpha():
    """Repository scoped to org_demo_alpha."""
    repo = PackRepository(org_id="org_demo_alpha")
    repo.create_org("org_demo_alpha", "Alpha Demo Merchant")
    return repo


@pytest.fixture
def repo_bravo():
    """Repository scoped to org_demo_bravo."""
    repo = PackRepository(org_id="org_demo_bravo")
    repo.create_org("org_demo_bravo", "Bravo Demo 3PL")
    return repo


@pytest.fixture
def client():
    """Test client for FastAPI app authenticated as org_demo_alpha."""
    from starlette.testclient import TestClient
    from agent.main import app, sign_session_org, COOKIE_NAME
    c = TestClient(app)
    c.cookies.set(COOKIE_NAME, sign_session_org("org_demo_alpha"))
    return c


@pytest.fixture
def unauth_client():
    """Test client for FastAPI app with no session cookie."""
    from starlette.testclient import TestClient
    from agent.main import app
    return TestClient(app)

