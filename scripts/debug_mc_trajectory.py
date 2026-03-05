"""
Run fresh Monte Carlo for Steven and print the yearly P50 balance trajectory.
Also computes per-year P50 manually to diagnose why stored P50 is ~2x expected.
"""
import sys, math, random, statistics
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
    _draw_annual_return,
    _student_t,
)
import numpy as np

fund_moments = _build_fund_moments()

current_age      = 29
retirement_age   = 65
life_expectancy  = 88
withdrawal_pct   = 0.05
base_salary      = float(user["contribution_details"]["annual_salary"])
salary_growth    = float(user["contribution_details"]["salary_increase_pct"])
inflation        = 0.028
target_vol       = 0.135
N_SIMS           = 2000
random_seed      = 42

start_401k = 55527.74
start_ira  = 32684.14
total      = start_401k + start_ira
w_401k     = start_401k / total
w_ira      = start_ira  / total

(mu_401k_0, sig_401k_0), (mu_ira_0, sig_ira_0) = _account_phase_moments(
    user, current_age, fund_moments, retirement_age
)
blended_vol     = math.sqrt((w_401k * sig_401k_0) ** 2 + (w_ira * sig_ira_0) ** 2)
volatility_uplift = max(1.0, target_vol / max(blended_vol, 1e-8))

years_to_sim = life_expectancy - current_age
PRINT_AGES = {35, 40, 45, 50, 55, 60, 65, 70, 80, 88}

# Per-year totals across all sims
per_year_balances = [[] for _ in range(years_to_sim + 1)]
retirement_port_balances = []

for sim in range(N_SIMS):
    rng = random.Random(random_seed + sim)
    age    = current_age
    salary = base_salary
    b401k  = start_401k
    bira   = start_ira
    regime_variance = 1.0
    prev_shock      = 0.0
    annual_withdrawal = 0.0
    ret_start_balance = None
    failed = False

    per_year_balances[0].append(b401k + bira)

    for year_idx in range(years_to_sim):
        age = current_age + year_idx
        if failed:
            per_year_balances[year_idx + 1].append(0.0)
            continue

        total_b = max(b401k + bira, 0.0)

        (mu_401k, sig_401k), (mu_ira, sig_ira) = _account_phase_moments(
            user, age, fund_moments, retirement_age
        )
        sig_401k *= volatility_uplift
        sig_ira  *= volatility_uplift

        shock = _student_t(rng)
        if shock < 0:
            shock *= 1.15
        omega, alpha, beta = 0.08, 0.17, 0.78
        regime_variance = omega + alpha * (prev_shock ** 2) + beta * regime_variance
        regime_scale = max(0.55, min(1.9, math.sqrt(regime_variance)))
        normalized_shock = shock * regime_scale
        prev_shock = normalized_shock

        if age < retirement_age:
            contribution = _annual_contribution(user, salary)
            ira_contrib  = _annual_ira_contribution(user, year_idx, inflation)
            salary      *= (1 + salary_growth)
            w401 = wira = 0
        else:
            if ret_start_balance is None:
                ret_start_balance = total_b
                retirement_port_balances.append(total_b)
                annual_withdrawal  = total_b * withdrawal_pct
            else:
                annual_withdrawal *= (1 + inflation)
            contribution = ira_contrib = 0.0
            share_401k = b401k / total_b if total_b > 0 else 0.5
            share_ira  = 1.0 - share_401k
            w401 = annual_withdrawal * share_401k
            wira = annual_withdrawal * share_ira

        eff_401k = max(b401k + 0.5 * (contribution - w401), 0.0)
        eff_ira  = max(bira  + 0.5 * (ira_contrib  - wira), 0.0)
        r401 = _draw_annual_return(mu_401k, sig_401k, normalized_shock)
        rira = _draw_annual_return(mu_ira,  sig_ira,  normalized_shock)
        b401k = max(eff_401k * (1 + r401) + 0.5 * (contribution - w401), 0.0)
        bira  = max(eff_ira  * (1 + rira ) + 0.5 * (ira_contrib  - wira), 0.0)

        if (b401k + bira) <= 1.0:
            failed = True
            b401k = bira = 0.0

        per_year_balances[year_idx + 1].append(b401k + bira)

print(f"Sims: {N_SIMS}  uplift: {volatility_uplift:.4f}")
print()
print(f"{'Age':>4} {'P10':>14} {'P50':>14} {'P90':>14}  (MC fresh run)")
for year_idx in range(years_to_sim + 1):
    age = current_age + year_idx
    if age in PRINT_AGES:
        vals = sorted(per_year_balances[year_idx])
        n = len(vals)
        p10 = vals[int(n * 0.10)]
        p50 = vals[int(n * 0.50)]
        p90 = vals[int(n * 0.90)]
        print(f"{age:>4} {p10:>14,.0f} {p50:>14,.0f} {p90:>14,.0f}")

print()
retirement_port_balances.sort()
n = len(retirement_port_balances)
print(f"Retirement (at exactly age 65):")
print(f"  P10={retirement_port_balances[int(n*0.10)]:,.0f}  P50={retirement_port_balances[int(n*0.50)]:,.0f}  P90={retirement_port_balances[int(n*0.90)]:,.0f}")
print(f"  (stored in DB: P10=2,496,941  P50=8,251,041  P90=35,894,951)")
