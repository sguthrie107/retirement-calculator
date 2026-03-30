"""
Debug script: Simulate the MC P50 trajectory (using geometric median returns)
and compare with actual stored MC P50 and deterministic projection.
"""
import sys, math
sys.path.insert(0, ".")
import json

with open("data/users.json") as f:
    users = json.load(f)
user = [u for u in users["users"] if u["name"] == "Steven"][0]

from app.services.monte_carlo import (
    _account_phase_moments,
    _build_fund_moments,
    _annual_contribution,
    _annual_ira_contribution,
)
from app.services.projection import get_user_projection
from app.database import SessionLocal

fund_moments = _build_fund_moments()

# MC parameters (match run_stress_test)
current_age    = 29
retirement_age = 65
life_expectancy = 88
withdrawal_pct  = 0.05
base_salary     = float(user["contribution_details"]["annual_salary"])
salary_growth   = float(user["contribution_details"]["salary_increase_pct"])
inflation       = 0.028

# Starting balances (actual DB, what MC uses)
start_401k = 55527.74
start_ira  = 32684.14
total      = start_401k + start_ira
w_401k     = start_401k / total
w_ira      = start_ira  / total

# Compute volatility uplift (exactly as MC does)
(mu_401k_0, sig_401k_0), (mu_ira_0, sig_ira_0) = _account_phase_moments(
    user, current_age, fund_moments, retirement_age
)
blended_vol    = math.sqrt((w_401k * sig_401k_0) ** 2 + (w_ira * sig_ira_0) ** 2)
target_vol     = 0.135
volatility_uplift = max(1.0, target_vol / max(blended_vol, 1e-8))
print(f"blended_vol (no uplift): {blended_vol * 100:.3f}%  uplift_factor: {volatility_uplift:.4f}")
print()

# Simulate with geometric median each year (shock = 0 ⇒ P50 trajectory)
bal_401k          = start_401k
bal_ira           = start_ira
salary            = base_salary
annual_withdrawal = 0.0
retirement_balance = None

PRINT_YEARS = {2026, 2030, 2035, 2040, 2045, 2050, 2055, 2060, 2062, 2070, 2080, 2085}

years_to_sim = life_expectancy - current_age

print(f"{'Year':>6} {'Age':>4} {'401k':>12} {'IRA':>12} {'Total':>14}  (MC geo-median trajectory)")
for year_idx in range(years_to_sim):
    age      = current_age + year_idx
    year_cal = 2026 + year_idx

    (mu_401k, sig_401k), (mu_ira, sig_ira) = _account_phase_moments(
        user, age, fund_moments, retirement_age
    )
    sig_401k *= volatility_uplift
    sig_ira  *= volatility_uplift

    # Geometric median return (lognormal median = exp(log_mean) - 1)
    r_401k = math.exp(math.log1p(mu_401k) - 0.5 * sig_401k ** 2) - 1
    r_ira  = math.exp(math.log1p(mu_ira)  - 0.5 * sig_ira  ** 2) - 1

    if age < retirement_age:
        contr_401k = _annual_contribution(user, salary)
        contr_ira  = _annual_ira_contribution(user, year_idx, inflation)
        # Mid-period convention (matches MC code)
        bal_401k = max((bal_401k + 0.5 * contr_401k) * (1 + r_401k) + 0.5 * contr_401k, 0)
        bal_ira  = max((bal_ira  + 0.5 * contr_ira ) * (1 + r_ira ) + 0.5 * contr_ira,  0)
        salary  *= (1 + salary_growth)
    else:
        if retirement_balance is None:
            retirement_balance = bal_401k + bal_ira
            annual_withdrawal  = retirement_balance * withdrawal_pct
            print(f"  => RETIREMENT age {age}: balance={retirement_balance:,.0f}  annual_withdrawal={annual_withdrawal:,.0f}")
        else:
            annual_withdrawal *= (1 + inflation)
        total_b   = max(bal_401k + bal_ira, 0.0)
        share_401k = bal_401k / total_b if total_b > 0 else 0.5
        share_ira  = 1.0 - share_401k
        w401 = annual_withdrawal * share_401k
        wira = annual_withdrawal * share_ira
        bal_401k = max((bal_401k - 0.5 * w401) * (1 + r_401k) - 0.5 * w401, 0)
        bal_ira  = max((bal_ira  - 0.5 * wira ) * (1 + r_ira ) - 0.5 * wira,  0)

    if year_cal in PRINT_YEARS:
        print(f"{year_cal:>6} {age:>4} {bal_401k:>12,.0f} {bal_ira:>12,.0f} {(bal_401k + bal_ira):>14,.0f}")

print()
# Compare with the deterministic projection (uses users.json starting balances)
print("=== Deterministic projection (raw, from users.json $100k start) ===")
s = SessionLocal()
proj = get_user_projection("Steven", s)
s.close()
by_year = {row["year"]: row["total_balance"] for row in proj["projection"]}
for yr in sorted(PRINT_YEARS):
    if yr in by_year:
        print(f"  {yr}: {by_year[yr]:>14,.0f}")

print()
print("=== Stored MC outcome percentiles ===")
import json as _json
from app.database import SessionLocal as SL
from app.models import StressTestResult, User as UserModel
s2 = SL()
u_db = s2.query(UserModel).filter(UserModel.name == "Steven").first()
latest = s2.query(StressTestResult).filter(StressTestResult.user_id == u_db.id).order_by(StressTestResult.created_at.desc()).first()
if latest:
    ass = latest.assumptions_json
    pc  = ass.get("outcome_percentiles", {})
    print(f"  Retirement P10={pc['retirement']['p10']:>14,.0f}  P50={pc['retirement']['p50']:>14,.0f}  P90={pc['retirement']['p90']:>14,.0f}")
    print(f"  Life       P10={pc['life']['p10']:>14,.0f}  P50={pc['life']['p50']:>14,.0f}  P90={pc['life']['p90']:>14,.0f}")
s2.close()
