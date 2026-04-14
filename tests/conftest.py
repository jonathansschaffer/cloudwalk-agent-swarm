"""
Shared pytest fixtures for the InfinitePay test suite.

Provides:
  - `auth_client`: a TestClient with a valid bearer token for client789
  - `client`: unauthenticated TestClient (for public endpoints like /health)
  - individual fixture variants for each mock user
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app


# ---------------------------------------------------------------------------
# Helper: register + login → JWT token
# ---------------------------------------------------------------------------

def _login(email: str, password: str = "Test123!") -> str:
    """Logs in as a seeded mock user and returns the JWT access token."""
    with TestClient(app) as c:
        resp = c.post("/auth/login", json={"email": email, "password": password})
        assert resp.status_code == 200, (
            f"Login failed for {email}: {resp.status_code} {resp.text}"
        )
        return resp.json()["access_token"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def client():
    """Unauthenticated TestClient — suitable for /health, /auth/*, etc."""
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def token_client789():
    return _login("carlos.andrade@infinitepay.test")


@pytest.fixture(scope="session")
def token_user002():
    return _login("maria.souza@infinitepay.test")


@pytest.fixture(scope="session")
def token_user003():
    return _login("joao.silva@infinitepay.test")


@pytest.fixture(scope="session")
def auth_client(token_client789):
    """Authenticated TestClient pre-configured as client789 (active account)."""
    with TestClient(app) as c:
        c.headers.update({"Authorization": f"Bearer {token_client789}"})
        yield c


@pytest.fixture(scope="session")
def auth_client_002(token_user002):
    """Authenticated TestClient as user_002 (suspended account)."""
    with TestClient(app) as c:
        c.headers.update({"Authorization": f"Bearer {token_user002}"})
        yield c


@pytest.fixture(scope="session")
def auth_client_003(token_user003):
    """Authenticated TestClient as user_003 (pending KYC)."""
    with TestClient(app) as c:
        c.headers.update({"Authorization": f"Bearer {token_user003}"})
        yield c
