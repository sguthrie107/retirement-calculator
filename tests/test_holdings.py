from datetime import date

from fastapi.testclient import TestClient

from app.main import create_app
from app.services import holdings as holdings_service


def test_resolve_current_year_uses_runtime_date():
    assert holdings_service.resolve_current_year(date(2026, 12, 31)) == 2026
    assert holdings_service.resolve_current_year(date(2027, 1, 1)) == 2027


def test_phase_transitions_on_january_first():
    profile = {
        "age": 29,
        "age_reference_year": 2026,
        "401k_phases": {
            "phase_1": {"name": "Phase 1", "end_age": 29, "allocation": {}},
            "phase_2": {"name": "Phase 2", "end_age": None, "allocation": {}},
        },
    }

    age_dec_31 = holdings_service.resolve_current_age(profile, date(2026, 12, 31))
    age_jan_1 = holdings_service.resolve_current_age(profile, date(2027, 1, 1))
    assert age_dec_31 == 29
    assert age_jan_1 == 30

    phase_dec_31, _ = holdings_service.resolve_phase(profile["401k_phases"], age_dec_31)
    phase_jan_1, _ = holdings_service.resolve_phase(profile["401k_phases"], age_jan_1)
    assert phase_dec_31 == "phase_1"
    assert phase_jan_1 == "phase_2"


def test_holdings_endpoint_returns_phase_and_trend(monkeypatch):
    app = create_app()

    profile = {
        "name": "Demo",
        "age": 29,
        "age_reference_year": 2026,
        "current_401k_balance": 60000,
        "current_ira_balance": 40000,
        "401k_phases": {
            "phase_1": {
                "name": "Growth",
                "end_age": 50,
                "allocation": {
                    "us_stock": {"pct": 0.7, "ticker": "FXAIX", "label": "S&P 500"}
                },
            }
        },
        "ira_phases": {
            "phase_1": {
                "name": "Growth",
                "end_age": 50,
                "allocation": {
                    "intl": {"pct": 0.3, "ticker": "FZILX", "label": "Intl Index"}
                },
            }
        },
    }

    def fake_load_user_profile(_username: str):
        return profile

    def fake_get_quote_snapshot(ticker: str, _as_of=None):
        return {
            "ticker": ticker,
            "price": 100.0,
            "previous_close": 98.0,
            "day_change": 2.0,
            "day_change_pct": 2.0408,
            "updated_at": "2027-01-01T00:00:00Z",
            "status": "ok",
            "source": "test",
        }

    monkeypatch.setattr(holdings_service, "_load_user_profile", fake_load_user_profile)
    monkeypatch.setattr(holdings_service, "get_quote_snapshot", fake_get_quote_snapshot)

    with TestClient(app, base_url="http://localhost") as client:
        response = client.get("/api/holdings/Demo?as_of=2027-01-01")

    assert response.status_code == 200
    payload = response.json()
    assert payload["as_of_year"] == 2027
    assert payload["current_age"] == 30
    assert payload["phase"]["401k"]["key"] == "phase_1"
    assert len(payload["holdings"]) == 2
    assert all(row["day_change_pct"] > 0 for row in payload["holdings"])
