"""Pytest configuration and shared fixtures for Pack Manager."""

import sys
from pathlib import Path
import pytest

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
