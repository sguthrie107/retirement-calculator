"""Tests for the retirement-calculator web application.

Covers:
  - Input sanitization helpers
  - Balance CRUD routes (create, read, update, delete + XSS escaping)
  - Auth enforcement (editor vs non-editor via is_editor)
  - Pydantic schema validation (negative balance, invalid account type)
  - Security headers on every response
  - Health check
"""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import create_app
from app.database import get_db
from app.models import Base, User
from app.sanitize import sanitize_name, sanitize_notes


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def _db_session_factory():
    """In-memory SQLite engine + session factory shared for the module.

    Uses StaticPool so every session shares the same underlying connection,
    keeping tables alive across separate ``get_db`` calls.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Seed one user so balance routes have someone to work with
    db = factory()
    db.add(User(name="Steven"))
    db.commit()
    db.close()

    return factory


@pytest.fixture(scope="module")
def client(_db_session_factory):
    """TestClient wired to the in-memory DB.

    Because TestClient connects via localhost the auth middleware sets the
    user to ``local_dev`` which is an editor — write routes work without
    needing explicit auth headers.
    """
    application = create_app()

    def _override():
        db = _db_session_factory()
        try:
            yield db
        finally:
            db.close()

    application.dependency_overrides[get_db] = _override

    with TestClient(application, base_url="http://localhost") as c:
        yield c


@pytest.fixture(scope="module")
def readonly_client(_db_session_factory):
    """TestClient that simulates a non-editor (guest) user.

    Patches ``is_editor`` to always return False so write routes get 403.
    Uses localhost so the middleware doesn't block with 401 first.
    """
    application = create_app()

    def _override():
        db = _db_session_factory()
        try:
            yield db
        finally:
            db.close()

    application.dependency_overrides[get_db] = _override

    with TestClient(application, base_url="http://localhost") as c:
        yield c


# ── Sanitize unit tests ────────────────────────────────────────────────────

class TestSanitizeName:
    def test_valid_name(self):
        assert sanitize_name("Steven") == "Steven"

    def test_allows_hyphen_and_apostrophe(self):
        assert sanitize_name("O'Brien") == "O'Brien"
        assert sanitize_name("Mary-Jane") == "Mary-Jane"

    def test_strips_whitespace(self):
        assert sanitize_name("  Alyssa  ") == "Alyssa"

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="empty"):
            sanitize_name("")

    def test_rejects_whitespace_only(self):
        with pytest.raises(ValueError, match="empty"):
            sanitize_name("   ")

    def test_rejects_script_tag(self):
        with pytest.raises(ValueError, match="invalid characters"):
            sanitize_name("<script>alert(1)</script>")

    def test_rejects_sql_injection(self):
        with pytest.raises(ValueError, match="invalid characters"):
            sanitize_name("'; DROP TABLE users; --")

    def test_length_cap(self):
        with pytest.raises(ValueError, match="characters or fewer"):
            sanitize_name("A" * 51)


class TestSanitizeNotes:
    def test_none_passthrough(self):
        assert sanitize_notes(None) is None

    def test_strips_and_escapes(self):
        result = sanitize_notes('  <script>alert("xss")</script>  ')
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_ampersand_escaped(self):
        assert "&amp;" in sanitize_notes("A & B")

    def test_truncates(self):
        long_text = "x" * 600
        result = sanitize_notes(long_text, max_length=500)
        assert len(result) == 500

    def test_empty_returns_none(self):
        assert sanitize_notes("   ") is None


# ── Balance CRUD (local_dev = editor) ───────────────────────────────────────

class TestBalanceRoutes:
    def test_create_balance(self, client):
        resp = client.post(
            "/api/balances/Steven",
            json={"account_type": "401k", "year": 2026, "balance": 50000.0, "notes": "initial"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["year"] == 2026
        assert data["balance"] == 50000.0
        assert data["notes"] == "initial"

    def test_get_balances(self, client):
        resp = client.get("/api/balances/Steven")
        assert resp.status_code == 200
        items = resp.json()
        assert isinstance(items, list)
        assert len(items) >= 1

    def test_get_balances_unknown_user_returns_empty(self, client):
        resp = client.get("/api/balances/NobodyHere")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_update_balance(self, client):
        balances = client.get("/api/balances/Steven").json()
        bid = balances[0]["id"]
        resp = client.put(f"/api/balances/{bid}", json={"balance": 55000.0})
        assert resp.status_code == 200
        assert resp.json()["balance"] == 55000.0

    def test_delete_balance(self, client):
        create_resp = client.post(
            "/api/balances/Steven",
            json={"account_type": "roth_ira", "year": 2025, "balance": 1000.0},
        )
        bid = create_resp.json()["id"]
        resp = client.delete(f"/api/balances/{bid}")
        assert resp.status_code == 204

    def test_duplicate_year_account_returns_409(self, client):
        resp = client.post(
            "/api/balances/Steven",
            json={"account_type": "401k", "year": 2026, "balance": 60000.0},
        )
        assert resp.status_code == 409

    def test_xss_in_notes_is_escaped(self, client):
        resp = client.post(
            "/api/balances/Steven",
            json={
                "account_type": "roth_ira",
                "year": 2026,
                "balance": 2000.0,
                "notes": '<img src=x onerror=alert(1)>',
            },
        )
        assert resp.status_code == 201
        notes = resp.json()["notes"]
        assert "<img" not in notes
        assert "&lt;img" in notes

    def test_update_nonexistent_returns_404(self, client):
        resp = client.put("/api/balances/999999", json={"balance": 1.0})
        assert resp.status_code == 404

    def test_delete_nonexistent_returns_404(self, client):
        resp = client.delete("/api/balances/999999")
        assert resp.status_code == 404


# ── Schema validation (Pydantic rejects before route logic) ────────────────

class TestSchemaValidation:
    def test_negative_balance_rejected(self, client):
        resp = client.post(
            "/api/balances/Steven",
            json={"account_type": "401k", "year": 2080, "balance": -100.0},
        )
        assert resp.status_code == 422

    def test_invalid_account_type_rejected(self, client):
        resp = client.post(
            "/api/balances/Steven",
            json={"account_type": "crypto", "year": 2080, "balance": 100.0},
        )
        assert resp.status_code == 422

    def test_year_out_of_range_rejected(self, client):
        resp = client.post(
            "/api/balances/Steven",
            json={"account_type": "401k", "year": 1999, "balance": 100.0},
        )
        assert resp.status_code == 422

    def test_missing_required_fields_rejected(self, client):
        resp = client.post("/api/balances/Steven", json={})
        assert resp.status_code == 422


# ── Auth enforcement ────────────────────────────────────────────────────────

class TestAuthEnforcement:
    """Patches ``is_editor`` to simulate a non-editor hitting write routes."""

    def test_create_blocked_for_non_editor(self, readonly_client):
        with patch("app.routes.balances.is_editor", return_value=False):
            resp = readonly_client.post(
                "/api/balances/Steven",
                json={"account_type": "401k", "year": 2090, "balance": 100.0},
            )
        assert resp.status_code == 403

    def test_update_blocked_for_non_editor(self, readonly_client):
        with patch("app.routes.balances.is_editor", return_value=False):
            resp = readonly_client.put("/api/balances/1", json={"balance": 1.0})
        assert resp.status_code == 403

    def test_delete_blocked_for_non_editor(self, readonly_client):
        with patch("app.routes.balances.is_editor", return_value=False):
            resp = readonly_client.delete("/api/balances/1")
        assert resp.status_code == 403

    def test_read_allowed_for_non_editor(self, readonly_client):
        with patch("app.routes.balances.is_editor", return_value=False):
            resp = readonly_client.get("/api/balances/Steven")
        assert resp.status_code == 200


# ── Security headers ───────────────────────────────────────────────────────

class TestSecurityHeaders:
    def test_csp_present(self, client):
        resp = client.get("/health")
        csp = resp.headers.get("Content-Security-Policy", "")
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp

    def test_x_frame_options(self, client):
        assert client.get("/health").headers.get("X-Frame-Options") == "DENY"

    def test_nosniff(self, client):
        assert client.get("/health").headers.get("X-Content-Type-Options") == "nosniff"

    def test_hsts(self, client):
        hsts = client.get("/health").headers.get("Strict-Transport-Security", "")
        assert "max-age=" in hsts

    def test_referrer_policy(self, client):
        rp = client.get("/health").headers.get("Referrer-Policy", "")
        assert "strict-origin" in rp

    def test_permissions_policy(self, client):
        pp = client.get("/health").headers.get("Permissions-Policy", "")
        assert "camera=()" in pp


# ── Health check ────────────────────────────────────────────────────────────

def test_health_check(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
