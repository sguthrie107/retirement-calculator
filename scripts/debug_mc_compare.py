"""Run actual run_stress_test fresh (same code as stored result) and compare."""
import sys
sys.path.insert(0, ".")
import json
from app.database import SessionLocal
from app.services.monte_carlo import run_stress_test, get_latest_stress_test
from app.models import User

s = SessionLocal()
print("Running fresh run_stress_test('Steven', ...)  10000 sims ...")
result = run_stress_test("Steven", s, simulation_count=10000, random_seed=42)
ass = json.loads(result.assumptions_json)
pc = ass.get("outcome_percentiles", {})
snap = ass.get("portfolio_snapshot", {})
print(f"Starting balances: 401k={snap.get('starting_401k_balance')}  IRA={snap.get('starting_ira_balance')}  total={snap.get('starting_total_balance')}")
print(f"Blended return: {snap.get('blended_expected_return_pct')}%  vol: {snap.get('blended_volatility_pct')}%  uplift: {snap.get('target_volatility_floor_pct')}")
print()
print(f"Retirement P10={pc['retirement']['p10']:,.0f}  P50={pc['retirement']['p50']:,.0f}  P90={pc['retirement']['p90']:,.0f}")
print(f"Life       P10={pc['life']['p10']:,.0f}  P50={pc['life']['p50']:,.0f}  P90={pc['life']['p90']:,.0f}")
print()

stored = get_latest_stress_test("Steven", s)
if stored:
    ass2 = json.loads(stored.assumptions_json)
    pc2 = ass2.get("outcome_percentiles", {})
    print(f"STORED (created {stored.created_at}):")
    print(f"Retirement P10={pc2['retirement']['p10']:,.0f}  P50={pc2['retirement']['p50']:,.0f}  P90={pc2['retirement']['p90']:,.0f}")
    print(f"Life       P10={pc2['life']['p10']:,.0f}  P50={pc2['life']['p50']:,.0f}  P90={pc2['life']['p90']:,.0f}")
s.close()
