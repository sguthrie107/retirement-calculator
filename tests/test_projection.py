"""Unit tests for projection and Monte Carlo calculation logic.

These tests cover pure calculation functions that don't require a running
database or network access.
"""
import math
import random
import pytest
import pandas as pd

from app.services.monte_carlo import (
    _annual_contribution,
    _annual_ira_contribution,
    _draw_annual_return,
    _is_bond_like_ticker,
    _normalize_allocation_weights,
    _retirement_spending_for_year,
    _rating_for_probability,
    _estimate_social_security_annual_benefit,
    _route_withdrawal,
    _student_t,
    AssetMoments,
    RATING_BANDS,
    BOND_LIKE_TICKERS,
    WITHDRAWAL_STRATEGY_PROPORTIONAL,
    WITHDRAWAL_STRATEGY_401K_FIRST,
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
