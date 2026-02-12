"""
Demo script showing the full 3-phase 401k projection for stored users.
"""

from lib.plan_by_age import (
    retirement_401k_age_based_plan_phase_1,
    retirement_401k_full_plan,
)
import pandas as pd

pd.set_option("display.max_rows", None)
pd.set_option("display.max_columns", None)
pd.set_option("display.width", 200)

# ── Phase 1 only (original demo) ──────────────────────────────────────────
print("=" * 70)
print("PHASE 1 - 401K RETIREMENT PLAN FOR STEVEN (Age 35 → 50)")
print("=" * 70)
steven_phase_1 = retirement_401k_age_based_plan_phase_1("Steven", 35)
print(steven_phase_1.to_string(index=False))
print()

print("=" * 70)
print("PHASE 1 - 401K RETIREMENT PLAN FOR ALYSSA (Age 32 → 50)")
print("=" * 70)
alyssa_phase_1 = retirement_401k_age_based_plan_phase_1("Alyssa", 32)
print(alyssa_phase_1.to_string(index=False))
print()

# ── Full plan (all 3 phases) ──────────────────────────────────────────────
print("=" * 100)
print("FULL 3-PHASE 401K PLAN FOR STEVEN (Age 35 → 65)")
print("=" * 100)
steven_full = retirement_401k_full_plan("Steven")
print(steven_full.to_string(index=False))
print()

print("=" * 100)
print("FULL 3-PHASE 401K PLAN FOR ALYSSA (Age 32 → 65)")
print("=" * 100)
alyssa_full = retirement_401k_full_plan("Alyssa")
print(alyssa_full.to_string(index=False))
print()

# ── Summary ───────────────────────────────────────────────────────────────
print("=" * 70)
print("SUMMARY AT RETIREMENT (Age 65)")
print("=" * 70)
for name, df in [("Steven", steven_full), ("Alyssa", alyssa_full)]:
    final = df.iloc[-1]
    total_contrib = df["total_contribution"].sum()
    total_growth = df["growth"].sum()
    print(f"\n  {name}:")
    print(f"    Final Balance:        ${final['balance']:>15,.2f}")
    print(f"    Total Contributions:  ${total_contrib:>15,.2f}")
    print(f"    Total Growth:         ${total_growth:>15,.2f}")
print()
