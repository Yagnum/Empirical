"""Shared test fixtures.

The app is a flat set of modules at `app/api/`, so tests import them the same
way the app does (`import alpaca`) once that directory is on the path.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import clerk_auth  # noqa: E402
from main import app  # noqa: E402

TEST_USER_ID = "user_test"
TEST_ACCOUNT_ID = "acct-test-0001"


@pytest.fixture
def client():
    """A client whose requests are already "signed in".

    `dependency_overrides` replaces the Clerk dependencies with constants, so
    the tests exercise the *real* routers, validation and serialisation while
    skipping the one part that needs a live third party. Nothing else is
    faked at the framework level.
    """
    app.dependency_overrides[clerk_auth.require_user_id] = lambda: TEST_USER_ID
    app.dependency_overrides[clerk_auth.require_account_id] = lambda: TEST_ACCOUNT_ID
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def anon_client():
    """A client with no auth override, for checking the 401 path."""
    app.dependency_overrides.clear()
    with TestClient(app) as test_client:
        yield test_client
