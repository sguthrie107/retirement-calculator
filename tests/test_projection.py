"""Unit tests for projection and Monte Carlo calculation logic.

These tests cover pure calculation functions that don't require a running
database or network access.
"""
import math
import random
import pytest
import pandas as pd

from app.services import projection as projection_service
from app.services.monte_carlo import (
    _allocation_moments,
    _annual_contribution,
    _annual_hsa_contribution,
    _annual_ira_contribution,
    _draw_annual_return,
    _eligible_hsa_withdrawal,
    _is_bond_like_ticker,
    _normalize_allocation_weights,
    _retirement_spending_for_year,
    _rating_for_probability,
    _estimate_social_security_annual_benefit,
    _route_withdrawal,
    _student_t,
    _load_guardrail_config,
    _load_household_guardrail_config,
    _guardrail_adjusted_rate,
    _apply_guardrail_to_withdrawal,
    AssetMoments,
    RATING_BANDS,
    BOND_LIKE_TICKERS,
    WITHDRAWAL_STRATEGY_PROPORTIONAL,
    WITHDRAWAL_STRATEGY_401K_FIRST,
    DEFAULT_GUARDRAIL_BASELINE_PCT,
    DEFAULT_GUARDRAIL_MIN_PCT,
    DEFAULT_GUARDRAIL_MAX_PCT,
    WITHDRAWAL_MODE_FIXED,
    WITHDRAWAL_MODE_DYNAMIC,
)
from app.services.comparison import (
    _allocation_sequence_risk_returns,
    _sequence_risk_returns_for_projected_portfolio,
    _estimated_annual_contribution,
    compute_deltas,
)
from lib.calculator_utils import compute_contribution_pct_for_year, project_root, load_user_profile
from lib.display_utils import merge_projections


# ---------------------------------------------------------------------------
# _draw_annual_return
# ---------------------------------------------------------------------------

class TestDrawAnnualReturn:
    def test_zero_shock_approximates_geometric_median(self):
        """With shock=0 the return should be close to the lognormal geometric median."""
        mu, sigma = 0.07, 0.12
        r = _draw_annual_return(mu, sigma, 0.0)
        expected_geo_median = math.exp(math.log1p(mu) - 0.5 * sigma ** 2) - 1
        assert abs(r - expected_geo_median) < 1e-10

    def test_positive_shock_raises_return(self):
        r_flat = _draw_annual_return(0.07, 0.12, 0.0)
        r_up = _draw_annual_return(0.07, 0.12, 2.0)
        assert r_up > r_flat

    def test_negative_shock_lowers_return(self):
        r_flat = _draw_annual_return(0.07, 0.12, 0.0)
        r_down = _draw_annual_return(0.07, 0.12, -2.0)
        assert r_down < r_flat

    def test_catastrophic_draw_floored_at_negative_95_pct(self):
        """Return can never be worse than -95%."""
        r = _draw_annual_return(0.07, 0.12, -100.0)
        assert r >= -0.95

    def test_tiny_sigma_is_safe(self):
        """Sigma close to zero should not cause divide-by-zero errors."""
        r = _draw_annual_return(0.07, 1e-10, 0.0)
        assert math.isfinite(r)


# ---------------------------------------------------------------------------
# _rating_for_probability
# ---------------------------------------------------------------------------

class TestRatingForProbability:
    @pytest.mark.parametrize("prob,expected_grade", [
        (95.0, "A"),
        (92.0, "A"),
        (88.0, "B"),
        (85.0, "B"),
        (77.0, "C"),
        (75.0, "C"),
        (62.0, "D"),
        (60.0, "D"),
        (50.0, "F"),
        (0.0,  "F"),
    ])
    def test_grade_boundaries(self, prob, expected_grade):
        rating = _rating_for_probability(prob)
        assert rating["grade"] == expected_grade

    def test_returns_all_required_keys(self):
        rating = _rating_for_probability(90.0)
        assert {"tier", "grade", "label", "min_probability", "description"} == set(rating.keys())

    def test_rating_bands_are_exhaustive(self):
        """Every probability in [0, 100] should map to a band."""
        for p in range(0, 101):
            rating = _rating_for_probability(float(p))
            assert rating["grade"] in {"A", "B", "C", "D", "F"}

    def test_tier_ordering(self):
        """Higher probability → higher tier."""
        tier_high = _rating_for_probability(95.0)["tier"]
        tier_low = _rating_for_probability(30.0)["tier"]
        assert tier_high > tier_low


# ---------------------------------------------------------------------------
# _annual_contribution
# ---------------------------------------------------------------------------

class TestAnnualContribution:
    def _make_profile(self, employee_pct, match_pct, vested_pct=1.0):
        return {
            "contribution_details": {
                "annual_salary": 100_000,
                "annual_contribution_pct": employee_pct,
                "company_match_pct": match_pct,
                "company_match_vested_pct": vested_pct,
            }
        }

    def test_employee_only(self):
        profile = self._make_profile(0.06, 0.0)
        assert _annual_contribution(profile, 100_000) == pytest.approx(6_000)

    def test_with_fully_vested_match(self):
        profile = self._make_profile(0.06, 0.03, 1.0)
        assert _annual_contribution(profile, 100_000) == pytest.approx(9_000)

    def test_with_partial_vesting(self):
        profile = self._make_profile(0.06, 0.03, 0.5)
        # 6% employee + 3% * 50% = 7.5%
        assert _annual_contribution(profile, 100_000) == pytest.approx(7_500)

    def test_salary_scales_linearly(self):
        profile = self._make_profile(0.10, 0.0)
        assert _annual_contribution(profile, 200_000) == pytest.approx(20_000)

    def test_override_contribution_pct(self):
        profile = self._make_profile(0.06, 0.0)
        # Override to 10%
        assert _annual_contribution(profile, 100_000, employee_pct_override=0.10) == pytest.approx(10_000)

    def test_401k_employee_contribution_respects_catch_up_limit_at_age_50(self):
        profile = self._make_profile(0.50, 0.0)
        # 2026 defaults: 23,500 + 7,500 catch-up = 31,000 employee cap
        result = _annual_contribution(
            profile,
            200_000,
            age=50,
            years_since_start=0,
            inflation=0.0,
        )
        assert result == pytest.approx(31_000)

    def test_401k_employee_contribution_respects_enhanced_catch_up_ages_60_to_63(self):
        profile = self._make_profile(0.50, 0.0)
        # 2026 defaults: 23,500 + 11,250 enhanced catch-up = 34,750 employee cap
        result = _annual_contribution(
            profile,
            300_000,
            age=60,
            years_since_start=0,
            inflation=0.0,
        )
        assert result == pytest.approx(34_750)

    def test_maximize_mode_hits_401k_limit_even_with_low_pct(self):
        profile = self._make_profile(0.01, 0.0)
        profile["contribution_details"]["maximize_retirement_contributions"] = True
        result = _annual_contribution(
            profile,
            120_000,
            age=40,
            years_since_start=0,
            inflation=0.0,
        )
        assert result == pytest.approx(23_500)

    def test_calendar_year_step_up_schedule_applies(self):
        profile = self._make_profile(0.05, 0.0)
        profile["contribution_details"].update({
            "annual_contribution_pct_step_start_year": 2031,
            "annual_contribution_pct_step_pct": 0.01,
            "annual_contribution_pct_step_cap_pct": 0.15,
        })
        result = _annual_contribution(
            profile,
            100_000,
            age=40,
            calendar_year=2033,
            years_since_start=0,
            inflation=0.0,
        )
        assert result == pytest.approx(8_000)

    def test_company_match_starts_at_configured_year(self):
        profile = self._make_profile(0.05, 1.0)
        profile["contribution_details"].update({
            "company_match_start_year": 2028,
            "company_match_employee_cap_pct": 0.06,
        })

        before_start = _annual_contribution(
            profile,
            100_000,
            calendar_year=2027,
        )
        at_start = _annual_contribution(
            profile,
            100_000,
            calendar_year=2028,
        )

        assert before_start == pytest.approx(5_000)
        assert at_start == pytest.approx(10_000)

    def test_company_match_up_to_employee_cap_pct(self):
        profile = self._make_profile(0.10, 1.0)
        profile["contribution_details"].update({
            "company_match_start_year": 2028,
            "company_match_employee_cap_pct": 0.06,
        })

        result = _annual_contribution(
            profile,
            100_000,
            calendar_year=2028,
        )
        # Employee contributes 10,000; company matches only first 6% (6,000).
        assert result == pytest.approx(16_000)


class TestContributionPctSchedule:
    def test_compute_contribution_pct_for_year_caps_at_limit(self):
        contribution_details = {
            "annual_contribution_pct": 0.05,
            "annual_contribution_pct_step_start_year": 2031,
            "annual_contribution_pct_step_pct": 0.01,
            "annual_contribution_pct_step_cap_pct": 0.15,
        }

        assert compute_contribution_pct_for_year(contribution_details, 2030) == pytest.approx(0.05)
        assert compute_contribution_pct_for_year(contribution_details, 2031) == pytest.approx(0.06)
        assert compute_contribution_pct_for_year(contribution_details, 2045) == pytest.approx(0.15)


class TestEstimatedAnnualContribution:
    def _profile(self):
        return {
            "contribution_details": {
                "annual_salary": 100_000,
                "salary_increase_pct": 0.0,
                "annual_contribution_pct": 0.05,
                "company_match_pct": 1.0,
                "company_match_vested_pct": 1.0,
                "annual_ira_contribution": 7_000,
                "company_match_start_year": 2028,
                "company_match_employee_cap_pct": 0.06,
            }
        }

    def test_match_not_applied_before_start_year(self):
        total = _estimated_annual_contribution(self._profile(), years_since_base=1)  # year 2027
        assert total == pytest.approx(12_000)  # 5k employee + 0 match + 7k IRA

    def test_match_applied_at_start_year_with_cap(self):
        total = _estimated_annual_contribution(self._profile(), years_since_base=2)  # year 2028
        assert total == pytest.approx(17_000)  # 5k employee + 5k match + 7k IRA

    def test_compute_contribution_pct_for_year_boosts_base_and_cap(self):
        contribution_details = {
            "annual_contribution_pct": 0.05,
            "annual_contribution_pct_step_start_year": 2031,
            "annual_contribution_pct_step_pct": 0.01,
            "annual_contribution_pct_step_cap_pct": 0.15,
        }

        assert compute_contribution_pct_for_year(contribution_details, 2031, pct_boost=0.03) == pytest.approx(0.09)
        assert compute_contribution_pct_for_year(contribution_details, 2045, pct_boost=0.03) == pytest.approx(0.18)


# ---------------------------------------------------------------------------
# _annual_ira_contribution
# ---------------------------------------------------------------------------

class TestAnnualIraContribution:
    def _profile(self, base_ira):
        return {"contribution_details": {"annual_ira_contribution": base_ira}}

    def test_zero_base_returns_zero(self):
        assert _annual_ira_contribution(self._profile(0), 5, 0.03) == 0.0

    def test_year_zero_equals_base(self):
        assert _annual_ira_contribution(self._profile(7_000), 0, 0.03) == pytest.approx(7_000)

    def test_inflation_compounds(self):
        base = 7_000
        r = _annual_ira_contribution(self._profile(base), 10, 0.03)
        expected = base * (1.03 ** 10)
        assert r == pytest.approx(expected)

    def test_ira_is_capped_to_limit_when_age_provided(self):
        r = _annual_ira_contribution(self._profile(10_000), 0, 0.03, age=40)
        assert r == pytest.approx(7_000)

    def test_ira_catch_up_limit_applies_at_age_50(self):
        r = _annual_ira_contribution(self._profile(10_000), 0, 0.03, age=50)
        assert r == pytest.approx(8_000)

    def test_ira_maximize_mode_uses_age_based_limit(self):
        profile = {
            "contribution_details": {
                "annual_ira_contribution": 0,
                "maximize_retirement_contributions": True,
            }
        }
        r = _annual_ira_contribution(profile, 0, 0.03, age=50)
        assert r == pytest.approx(8_000)


class TestAnnualHsaContribution:
    def _profile(self, monthly=200, start_year=2028, growth_pct=0.0):
        return {
            "contribution_details": {
                "hsa_monthly_contribution": monthly,
                "hsa_contribution_start_year": start_year,
                "hsa_contribution_growth_pct": growth_pct,
            }
        }

    def test_zero_until_start_year(self):
        assert _annual_hsa_contribution(self._profile(), 2027, inflation=0.03) == pytest.approx(0.0)

    def test_monthly_contribution_becomes_annual_amount(self):
        assert _annual_hsa_contribution(self._profile(), 2028, inflation=0.03) == pytest.approx(2_400.0)

    def test_growth_pct_applies_from_hsa_start_year(self):
        result = _annual_hsa_contribution(self._profile(growth_pct=0.02), 2030, inflation=0.03)
        assert result == pytest.approx(2_400.0 * (1.02 ** 2))


class TestEligibleHsaWithdrawal:
    def test_capped_by_medical_spending(self):
        assert _eligible_hsa_withdrawal(10_000, 3_000, 50_000) == pytest.approx(3_000)

    def test_capped_by_available_balance(self):
        assert _eligible_hsa_withdrawal(10_000, 8_000, 1_500) == pytest.approx(1_500)

    def test_zero_when_no_medical_need(self):
        assert _eligible_hsa_withdrawal(10_000, 0, 5_000) == pytest.approx(0.0)


class TestRetirementSpendingForYear:
    def test_applies_expense_adjustment_once_effective_year_is_reached(self):
        spending_config = {
            "base_year": 2026,
            "annual_general_living_expenses": 115_000,
            "annual_medical_quality_of_life_expenses": 30_000,
            "expense_adjustments": [
                {
                    "effective_year": 2052,
                    "annual_general_living_expenses_delta": -24_000,
                }
            ],
        }

        _, _, before_payoff = _retirement_spending_for_year(spending_config, 2051, 0.0)
        _, _, after_payoff = _retirement_spending_for_year(spending_config, 2052, 0.0)

        assert before_payoff == pytest.approx(145_000)
        assert after_payoff == pytest.approx(121_000)


class TestMergeProjections:
    def test_does_not_apply_phase_3_withdrawals_by_default(self):
        df_401k = pd.DataFrame([
            {"year": 2026, "age": 65, "phase": "Phase 3", "balance": 100_000.0, "total_contribution": 10_000.0},
        ])
        df_ira = pd.DataFrame([
            {"year": 2026, "age": 65, "phase": "Phase 3", "ira_balance": 50_000.0, "ira_contribution": 7_000.0},
        ])

        merged = merge_projections(df_401k, df_ira)

        assert float(merged.loc[0, "total_balance"]) == pytest.approx(150_000.0)
        assert float(merged.loc[0, "withdrawal"]) == pytest.approx(0.0)

    def test_can_apply_phase_3_withdrawals_when_requested(self):
        df_401k = pd.DataFrame([
            {"year": 2026, "age": 65, "phase": "Phase 3", "balance": 100_000.0, "total_contribution": 10_000.0},
        ])
        df_ira = pd.DataFrame([
            {"year": 2026, "age": 65, "phase": "Phase 3", "ira_balance": 50_000.0, "ira_contribution": 7_000.0},
        ])

        merged = merge_projections(df_401k, df_ira, withdrawal_pct=0.06, apply_withdrawals=True)

        assert float(merged.loc[0, "withdrawal"]) == pytest.approx(9_000.0)
        assert float(merged.loc[0, "balance"]) == pytest.approx(91_000.0)
        assert float(merged.loc[0, "ira_balance"]) == pytest.approx(50_000.0)


class TestProjectionServiceCaching:
    def test_build_projected_series_reuses_cached_scenarios(self, monkeypatch):
        projection_service._build_projected_series_cached.cache_clear()
        call_counts = {"401k": 0, "ira": 0, "overlay": 0}

        def fake_401k(*_args, **_kwargs):
            call_counts["401k"] += 1
            return pd.DataFrame({"year": [2026], "balance": [1_000.0]})

        def fake_ira(*_args, **_kwargs):
            call_counts["ira"] += 1
            return pd.DataFrame({"year": [2026], "ira_balance": [500.0]})

        def fake_overlay(*_args, **_kwargs):
            call_counts["overlay"] += 1
            return {}

        monkeypatch.setattr(projection_service, "_load_user_profile", lambda _username: {})
        monkeypatch.setattr(projection_service, "retirement_401k_full_plan", fake_401k)
        monkeypatch.setattr(projection_service, "retirement_ira_full_plan", fake_ira)
        monkeypatch.setattr(
            projection_service,
            "merge_projections",
            lambda *_args, **_kwargs: pd.DataFrame({"year": [2026], "total_balance": [1_500.0]}),
        )
        monkeypatch.setattr(projection_service, "_compute_rental_income_overlay", fake_overlay)

        baseline_first = projection_service._build_projected_series("Steven")
        baseline_second = projection_service._build_projected_series("Steven")
        boosted_first = projection_service._build_projected_series("Steven", contribution_pct_boost=0.03)
        boosted_second = projection_service._build_projected_series("Steven", contribution_pct_boost=0.03)

        assert baseline_first == baseline_second
        assert boosted_first == boosted_second
        assert baseline_first is not baseline_second
        assert boosted_first is not boosted_second

        baseline_first[0]["balance"] = 999.0
        fresh_baseline = projection_service._build_projected_series("Steven")

        assert fresh_baseline[0]["balance"] == pytest.approx(1_500.0)
        assert call_counts == {"401k": 2, "ira": 2, "overlay": 2}

        projection_service._build_projected_series_cached.cache_clear()


# ---------------------------------------------------------------------------
# _is_bond_like_ticker
# ---------------------------------------------------------------------------

class TestIsBondLikeTicker:
    @pytest.mark.parametrize("ticker", list(BOND_LIKE_TICKERS))
    def test_bond_tickers_recognized(self, ticker):
        assert _is_bond_like_ticker(ticker) is True

    @pytest.mark.parametrize("ticker", ["FXAIX", "FZILX", "FSGGX", "VTI"])
    def test_equity_tickers_not_bond(self, ticker):
        assert _is_bond_like_ticker(ticker) is False

    def test_case_insensitive(self):
        ticker = next(iter(BOND_LIKE_TICKERS))
        assert _is_bond_like_ticker(ticker.lower()) is True


# ---------------------------------------------------------------------------
# _normalize_allocation_weights
# ---------------------------------------------------------------------------

class TestNormalizeAllocationWeights:
    def test_already_normalized_unchanged(self):
        alloc = {
            "a": {"pct": 0.6, "ticker": "FXAIX"},
            "b": {"pct": 0.4, "ticker": "FXNAX"},
        }
        result = _normalize_allocation_weights(alloc)
        assert result["a"]["pct"] == pytest.approx(0.6)
        assert result["b"]["pct"] == pytest.approx(0.4)

    def test_unnormalized_weights_sum_to_one(self):
        alloc = {
            "a": {"pct": 3.0, "ticker": "FXAIX"},
            "b": {"pct": 1.0, "ticker": "FXNAX"},
            "c": {"pct": 1.0, "ticker": "FZILX"},
        }
        result = _normalize_allocation_weights(alloc)
        total = sum(v["pct"] for v in result.values())
        assert total == pytest.approx(1.0)

    def test_empty_allocation_returns_empty(self):
        assert _normalize_allocation_weights({}) == {}

    def test_zero_weight_allocation_returns_empty(self):
        alloc = {"a": {"pct": 0.0, "ticker": "X"}}
        assert _normalize_allocation_weights(alloc) == {}


# ---------------------------------------------------------------------------
# Monte Carlo allocation sensitivity
# ---------------------------------------------------------------------------

class TestAllocationMoments:
    def test_bonds_reduce_portfolio_volatility(self):
        fund_moments = {
            "FXAIX": AssetMoments(mean_return=0.10, volatility=0.20),
            "FXNAX": AssetMoments(mean_return=0.04, volatility=0.05),
        }
        all_stock = {"us_stock": {"pct": 1.0, "ticker": "FXAIX"}}
        balanced = {
            "us_stock": {"pct": 0.6, "ticker": "FXAIX"},
            "bonds": {"pct": 0.4, "ticker": "FXNAX"},
        }

        mu_stock, sigma_stock = _allocation_moments(all_stock, fund_moments)
        mu_balanced, sigma_balanced = _allocation_moments(balanced, fund_moments)

        assert sigma_balanced < sigma_stock
        assert mu_balanced < mu_stock


# ---------------------------------------------------------------------------
# Chart sequence-risk sensitivity
# ---------------------------------------------------------------------------

class TestSequenceRiskReturns:
    def test_bond_allocation_softens_first_year_crash(self):
        fund_moments = {
            "FXAIX": AssetMoments(mean_return=0.10, volatility=0.20),
            "FXNAX": AssetMoments(mean_return=0.04, volatility=0.05),
        }
        all_stock = {"us_stock": {"pct": 1.0, "ticker": "FXAIX"}}
        balanced = {
            "us_stock": {"pct": 0.6, "ticker": "FXAIX"},
            "bonds": {"pct": 0.4, "ticker": "FXNAX"},
        }

        all_stock_path = _allocation_sequence_risk_returns(all_stock, fund_moments)
        balanced_path = _allocation_sequence_risk_returns(balanced, fund_moments)

        assert balanced_path[0] > all_stock_path[0]
        assert max(balanced_path) < 0.10

    def test_projected_portfolio_uses_account_structure_at_retirement(self):
        profile = {
            "age": 60,
            "retirement_age": 65,
            "401k_phases": {
                "phase_3": {
                    "end_age": None,
                    "allocation": {
                        "us_stock": {"pct": 1.0, "ticker": "FXAIX"},
                    },
                }
            },
            "ira_phases": {
                "phase_3": {
                    "end_age": None,
                    "allocation": {
                        "bonds": {"pct": 1.0, "ticker": "FXNAX"},
                    },
                }
            },
        }
        projected = [
            {
                "year": 2031,
                "balance": 100_000.0,
                "account_balances": {"401k": 60_000.0, "roth_ira": 40_000.0},
            }
        ]
        fund_moments = {
            "FXAIX": AssetMoments(mean_return=0.10, volatility=0.20),
            "FXNAX": AssetMoments(mean_return=0.04, volatility=0.05),
        }

        path = _sequence_risk_returns_for_projected_portfolio(
            profile,
            projected,
            current_year=2026,
            fund_moments=fund_moments,
        )

        stock_only = _allocation_sequence_risk_returns(
            {"us_stock": {"pct": 1.0, "ticker": "FXAIX"}},
            fund_moments,
        )
        bond_only = _allocation_sequence_risk_returns(
            {"bonds": {"pct": 1.0, "ticker": "FXNAX"}},
            fund_moments,
        )

        expected_first_year = round((0.6 * stock_only[0]) + (0.4 * bond_only[0]), 4)
        assert path[0] == pytest.approx(expected_first_year)


# ---------------------------------------------------------------------------
# _estimate_social_security_annual_benefit
# ---------------------------------------------------------------------------

class TestSocialSecurity:
    def _profile(self, salary=100_000, growth=0.03):
        return {
            "contribution_details": {
                "annual_salary": salary,
                "salary_increase_pct": growth,
            }
        }

    def test_benefit_is_positive(self):
        benefit = _estimate_social_security_annual_benefit(
            self._profile(), current_age=30, retirement_age=65, claim_age=67
        )
        assert benefit > 0

    def test_delayed_claim_increases_benefit(self):
        b_fra = _estimate_social_security_annual_benefit(
            self._profile(), current_age=30, retirement_age=65, claim_age=67
        )
        b_delayed = _estimate_social_security_annual_benefit(
            self._profile(), current_age=30, retirement_age=65, claim_age=70
        )
        assert b_delayed > b_fra

    def test_early_claim_reduces_benefit(self):
        b_fra = _estimate_social_security_annual_benefit(
            self._profile(), current_age=30, retirement_age=65, claim_age=67
        )
        b_early = _estimate_social_security_annual_benefit(
            self._profile(), current_age=30, retirement_age=65, claim_age=62
        )
        assert b_early < b_fra

    def test_higher_salary_gives_higher_benefit(self):
        b_low = _estimate_social_security_annual_benefit(
            self._profile(salary=50_000), current_age=30, retirement_age=65, claim_age=67
        )
        b_high = _estimate_social_security_annual_benefit(
            self._profile(salary=200_000), current_age=30, retirement_age=65, claim_age=67
        )
        assert b_high > b_low

    def test_zero_salary_gives_near_zero_benefit(self):
        benefit = _estimate_social_security_annual_benefit(
            self._profile(salary=0), current_age=30, retirement_age=65, claim_age=67
        )
        assert benefit == pytest.approx(0.0)

    def test_already_retired_returns_zero(self):
        """current_age >= retirement_age → no working years → no earnings history."""
        benefit = _estimate_social_security_annual_benefit(
            self._profile(), current_age=65, retirement_age=65, claim_age=67
        )
        assert benefit == 0.0


# ---------------------------------------------------------------------------
# compute_deltas
# ---------------------------------------------------------------------------

class TestComputeDeltas:
    def test_includes_historical_inflation_for_actual_year(self):
        projected = [{"year": 2024, "balance": 100_000.0}]
        actual = [{
            "year": 2024,
            "balance": 105_000.0,
            "balance_ids": [1],
            "timestamp": "2026-05-14T12:00:00",
            "account_balances": {"401k": 80_000.0, "roth_ira": 25_000.0},
        }]

        deltas = compute_deltas(projected, actual)

        assert deltas[0]["actual_inflation_pct"] == pytest.approx(2.9)

    def test_uses_none_when_no_historical_inflation_is_available(self):
        projected = [{"year": 2030, "balance": 100_000.0}]
        actual = [{
            "year": 2030,
            "balance": 95_000.0,
            "balance_ids": [1],
            "timestamp": "2026-05-14T12:00:00",
            "account_balances": {"401k": 70_000.0, "roth_ira": 25_000.0},
        }]

        deltas = compute_deltas(projected, actual)

        assert deltas[0]["actual_inflation_pct"] is None


# ---------------------------------------------------------------------------
# _student_t
# ---------------------------------------------------------------------------

class TestStudentT:
    def test_produces_float(self):
        rng = random.Random(42)
        val = _student_t(rng)
        assert isinstance(val, float)
        assert math.isfinite(val)

    def test_reproducible_with_seed(self):
        r1 = random.Random(1)
        r2 = random.Random(1)
        assert _student_t(r1) == _student_t(r2)

    def test_distribution_is_centred(self):
        """Over many draws the mean should be close to zero."""
        rng = random.Random(0)
        draws = [_student_t(rng) for _ in range(10_000)]
        mean = sum(draws) / len(draws)
        assert abs(mean) < 0.1


# ---------------------------------------------------------------------------
# lib/calculator_utils
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# _route_withdrawal
# ---------------------------------------------------------------------------

class TestRouteWithdrawal:
    def test_proportional_splits_by_balance(self):
        w_401k, w_ira, w_income = _route_withdrawal(10_000, 60_000, 40_000, 0, WITHDRAWAL_STRATEGY_PROPORTIONAL)
        assert w_401k == pytest.approx(6_000)
        assert w_ira == pytest.approx(4_000)
        assert w_income == pytest.approx(0)

    def test_proportional_with_income_bucket(self):
        # 50k 401k, 30k IRA, 20k income = 100k total; 10k withdrawal
        w_401k, w_ira, w_income = _route_withdrawal(10_000, 50_000, 30_000, 20_000, WITHDRAWAL_STRATEGY_PROPORTIONAL)
        assert w_401k == pytest.approx(5_000)
        assert w_ira == pytest.approx(3_000)
        assert w_income == pytest.approx(2_000)

    def test_401k_first_drains_401k_before_ira(self):
        """When 401k can't cover the full withdrawal, the remainder spills into IRA."""
        w_401k, w_ira, w_income = _route_withdrawal(5_000, 3_000, 100_000, 0, WITHDRAWAL_STRATEGY_401K_FIRST)
        assert w_401k == pytest.approx(3_000)
        assert w_ira == pytest.approx(2_000)
        assert w_income == pytest.approx(0)

    def test_401k_first_ira_untouched_when_401k_covers_all(self):
        """IRA receives zero withdrawal when 401k balance is sufficient."""
        w_401k, w_ira, w_income = _route_withdrawal(5_000, 100_000, 100_000, 0, WITHDRAWAL_STRATEGY_401K_FIRST)
        assert w_401k == pytest.approx(5_000)
        assert w_ira == pytest.approx(0)
        assert w_income == pytest.approx(0)

    def test_401k_first_income_bucket_before_ira(self):
        """After 401k is exhausted, income bucket is drawn before IRA."""
        w_401k, w_ira, w_income = _route_withdrawal(15_000, 10_000, 100_000, 8_000, WITHDRAWAL_STRATEGY_401K_FIRST)
        assert w_401k == pytest.approx(10_000)
        assert w_income == pytest.approx(5_000)
        assert w_ira == pytest.approx(0)

    def test_zero_withdrawal_returns_all_zeros_proportional(self):
        assert _route_withdrawal(0, 50_000, 50_000, 10_000, WITHDRAWAL_STRATEGY_PROPORTIONAL) == (0.0, 0.0, 0.0)

    def test_zero_withdrawal_returns_all_zeros_401k_first(self):
        assert _route_withdrawal(0, 50_000, 50_000, 10_000, WITHDRAWAL_STRATEGY_401K_FIRST) == (0.0, 0.0, 0.0)

    def test_zero_total_balance_returns_zeros_proportional(self):
        assert _route_withdrawal(1_000, 0, 0, 0, WITHDRAWAL_STRATEGY_PROPORTIONAL) == (0.0, 0.0, 0.0)

    def test_unknown_strategy_falls_back_to_proportional(self):
        """Unrecognised strategy string uses proportional behaviour."""
        w_401k, w_ira, w_income = _route_withdrawal(10_000, 60_000, 40_000, 0, "unknown_strategy")
        assert w_401k == pytest.approx(6_000)
        assert w_ira == pytest.approx(4_000)


class TestCalculatorUtils:
    def test_project_root_exists(self):
        root = project_root()
        assert root.exists()
        assert (root / "data").is_dir()
        assert (root / "lib").is_dir()

    def test_project_root_contains_users_json(self):
        assert (project_root() / "data" / "users.json").exists()


class TestLoadGuardrailConfig:
    def _cfg(self, profile):
        return _load_guardrail_config(profile)

    def test_returns_fixed_mode_when_not_configured(self):
        cfg = self._cfg({})
        assert cfg["enabled"] is False
        assert cfg["mode"] == WITHDRAWAL_MODE_FIXED

    def test_returns_fixed_mode_when_disabled_explicitly(self):
        cfg = self._cfg({"withdrawal_guardrails": {"enabled": False}})
        assert cfg["enabled"] is False
        assert cfg["mode"] == WITHDRAWAL_MODE_FIXED

    def test_returns_dynamic_mode_when_enabled(self):
        cfg = self._cfg({"withdrawal_guardrails": {"enabled": True}})
        assert cfg["enabled"] is True
        assert cfg["mode"] == WITHDRAWAL_MODE_DYNAMIC

    def test_uses_custom_bounds_when_provided(self):
        cfg = self._cfg({"withdrawal_guardrails": {
            "enabled": True,
            "baseline_pct": 0.042,
            "min_pct": 0.035,
            "max_pct": 0.050,
        }})
        assert cfg["baseline_pct"] == pytest.approx(0.042)
        assert cfg["min_pct"] == pytest.approx(0.035)
        assert cfg["max_pct"] == pytest.approx(0.050)

    def test_falls_back_to_defaults_when_bounds_absent(self):
        cfg = self._cfg({"withdrawal_guardrails": {"enabled": True}})
        assert cfg["baseline_pct"] == pytest.approx(DEFAULT_GUARDRAIL_BASELINE_PCT)
        assert cfg["min_pct"] == pytest.approx(DEFAULT_GUARDRAIL_MIN_PCT)
        assert cfg["max_pct"] == pytest.approx(DEFAULT_GUARDRAIL_MAX_PCT)


class TestLoadHouseholdGuardrailConfig:
    def test_returns_fixed_when_none_enabled(self):
        cfg = _load_household_guardrail_config([
            {"name": "A", "withdrawal_pct": 0.05},
            {"name": "B", "withdrawal_pct": 0.045},
        ])
        assert cfg["enabled"] is False
        assert cfg["mode"] == WITHDRAWAL_MODE_FIXED

    def test_returns_enabled_config_even_when_not_first(self):
        cfg = _load_household_guardrail_config([
            {"name": "A", "withdrawal_pct": 0.05},
            {
                "name": "B",
                "withdrawal_guardrails": {
                    "enabled": True,
                    "baseline_pct": 0.04,
                    "min_pct": 0.036,
                    "max_pct": 0.044,
                },
            },
        ])
        assert cfg["enabled"] is True
        assert cfg["mode"] == WITHDRAWAL_MODE_DYNAMIC
        assert cfg["baseline_pct"] == pytest.approx(0.04)


class TestGuardrailAdjustedRate:
    ACTIVE = {
        "enabled": True,
        "mode": WITHDRAWAL_MODE_DYNAMIC,
        "baseline_pct": 0.04,
        "min_pct": 0.036,
        "max_pct": 0.044,
    }
    INACTIVE = {
        "enabled": False,
        "mode": WITHDRAWAL_MODE_FIXED,
        "baseline_pct": 0.04,
        "min_pct": 0.036,
        "max_pct": 0.044,
    }

    def test_passthrough_when_disabled(self):
        rate = _guardrail_adjusted_rate(0.045, -0.15, self.INACTIVE)
        assert rate == pytest.approx(0.045)

    def test_returns_baseline_when_no_prior_return(self):
        rate = _guardrail_adjusted_rate(0.04, None, self.ACTIVE)
        assert rate == pytest.approx(0.04)

    def test_floor_on_severe_loss_year(self):
        # Return <= -10% → floor
        rate_exact = _guardrail_adjusted_rate(0.04, -0.10, self.ACTIVE)
        rate_worse = _guardrail_adjusted_rate(0.04, -0.30, self.ACTIVE)
        assert rate_exact == pytest.approx(self.ACTIVE["min_pct"])
        assert rate_worse == pytest.approx(self.ACTIVE["min_pct"])

    def test_partial_reduction_on_mild_negative_year(self):
        # Return of -5% → midpoint between baseline and floor
        rate = _guardrail_adjusted_rate(0.04, -0.05, self.ACTIVE)
        expected = 0.04 - 0.5 * (0.04 - 0.036)  # t=0.5 → 3.8%
        assert rate == pytest.approx(expected, rel=1e-6)

    def test_ceiling_on_strong_gain_year(self):
        # Return >= +20% → ceiling
        rate_exact = _guardrail_adjusted_rate(0.04, 0.20, self.ACTIVE)
        rate_better = _guardrail_adjusted_rate(0.04, 0.35, self.ACTIVE)
        assert rate_exact == pytest.approx(self.ACTIVE["max_pct"])
        assert rate_better == pytest.approx(self.ACTIVE["max_pct"])

    def test_partial_increase_on_moderate_gain_year(self):
        # Return of +10% → midpoint between baseline and ceiling
        rate = _guardrail_adjusted_rate(0.04, 0.10, self.ACTIVE)
        expected = 0.04 + 0.5 * (0.044 - 0.04)  # t=0.5 → 4.2%
        assert rate == pytest.approx(expected, rel=1e-6)

    def test_baseline_at_zero_return(self):
        rate = _guardrail_adjusted_rate(0.04, 0.0, self.ACTIVE)
        assert rate == pytest.approx(0.04)

    def test_deterministic_for_same_inputs(self):
        r1 = _guardrail_adjusted_rate(0.04, -0.07, self.ACTIVE)
        r2 = _guardrail_adjusted_rate(0.04, -0.07, self.ACTIVE)
        assert r1 == r2

    def test_rate_always_within_guardrail_bounds(self):
        for prior_return in [-0.50, -0.15, -0.10, -0.05, 0.0, 0.05, 0.10, 0.20, 0.40]:
            rate = _guardrail_adjusted_rate(0.04, prior_return, self.ACTIVE)
            assert self.ACTIVE["min_pct"] <= rate <= self.ACTIVE["max_pct"], (
                f"rate={rate:.4f} out of bounds for prior_return={prior_return}"
            )

    def test_project_root_contains_users_json(self):
        assert (project_root() / "data" / "users.json").exists()


class TestApplyGuardrailToWithdrawal:
    """Tests for _apply_guardrail_to_withdrawal (Guyton-Klinger clamp logic)."""

    DISABLED = {
        "enabled": False,
        "baseline_pct": 0.04,
        "min_pct": 0.036,
        "max_pct": 0.044,
    }
    ACTIVE = {
        "enabled": True,
        "baseline_pct": 0.04,
        "min_pct": 0.036,
        "max_pct": 0.044,
    }

    def test_passthrough_when_disabled(self):
        """Disabled guardrails return the inflation-grown amount unchanged."""
        amount = 42_000.0
        result, _ = _apply_guardrail_to_withdrawal(amount, 1_000_000.0, self.DISABLED, None)
        assert result == amount

    def test_within_band_unchanged(self):
        """Withdrawal already within band is returned as-is."""
        # 4.0% of 1_000_000 = 40_000 — within [3.6%, 4.4%]
        amount = 40_000.0
        result, rate = _apply_guardrail_to_withdrawal(amount, 1_000_000.0, self.ACTIVE, 0.05)
        assert result == amount
        assert abs(rate - 0.04) < 1e-9

    def test_withdrawal_clamped_to_ceiling(self):
        """When implied rate > max_pct, withdrawal is cut to ceiling."""
        # 50_000 on 1_000_000 = 5% implied rate — above 4.4% ceiling
        amount = 50_000.0
        result, rate = _apply_guardrail_to_withdrawal(amount, 1_000_000.0, self.ACTIVE, 0.05)
        assert abs(result - 44_000.0) < 1.0  # max_pct × balance
        assert abs(rate - 0.044) < 1e-6

    def test_withdrawal_raised_to_floor_after_strong_gain(self):
        """When implied rate < min_pct (portfolio grew a lot), withdrawal is raised to target floor."""
        # 30_000 on 1_000_000 = 3.0% — below 3.6% floor; prior year strong gain so target = baseline 4.0%
        amount = 30_000.0
        result, rate = _apply_guardrail_to_withdrawal(amount, 1_000_000.0, self.ACTIVE, 0.25)
        assert result > amount  # must be raised
        assert rate >= self.ACTIVE["min_pct"]

    def test_floor_applied_on_severe_loss(self):
        """After a severe loss year (-15%), floor is the guardrail min, not baseline."""
        # 30_000 on 1_000_000 → 3% implied, below floor; prior year -15% so adjusted rate = min_pct
        amount = 30_000.0
        result, rate = _apply_guardrail_to_withdrawal(amount, 1_000_000.0, self.ACTIVE, -0.15)
        assert abs(rate - 0.036) < 1e-6
        assert abs(result - 36_000.0) < 1.0

    def test_zero_balance_safe(self):
        """Zero spendable balance does not raise ZeroDivisionError."""
        result, rate = _apply_guardrail_to_withdrawal(40_000.0, 0.0, self.ACTIVE, 0.05)
        assert result == 40_000.0  # passthrough when balance is zero
