"""Comprehensive comparison: new chart values vs MC P50 at retirement."""
import sys; sys.path.insert(0, '.')
from app.services.comparison import get_comparison_data
from app.services.projection import get_user_projection
from app.database import SessionLocal
import json

s = SessionLocal()

print("=== Raw projection (401k + IRA + rental overlay) ===")
p = get_user_projection('Steven', current_year=2026)
for item in p['projected']:
    if item['year'] in {2026,2030,2035,2040,2045,2050,2055,2060,2061,2062}:
        r = item['account_balances'].get('rental', 0)
        k = item['account_balances'].get('401k', 0)
        i = item['account_balances'].get('roth_ira', 0)
        print(f"  {item['year']}: total={item['balance']:>12,.0f}  (401k={k:>10,.0f}  ira={i:>10,.0f}  rental={r:>10,.0f})")

print()

print("=== Chart projected (seed-scaled 401k+IRA + unscaled rental) ===")
comp = get_comparison_data('Steven', s)
for item in comp['projected']:
    if item['year'] in {2026,2030,2035,2040,2045,2050,2055,2060,2061,2062}:
        ab = item.get('account_balances', {})
        r = ab.get('rental', 0)
        k = ab.get('401k', 0)
        i = ab.get('roth_ira', 0)
        print(f"  {item['year']}: total={item['balance']:>12,.0f}  (401k={k:>10,.0f}  ira={i:>10,.0f}  rental={r:>10,.0f})")

s.close()

print()
print("MC P50 at retirement (age 65): $8,280,853")
print("=> Remaining gap vs chart 2062: $8,280,853 - $6,844,470 = $1,436,383")
print("   This is from chart_seed scaling 401k+IRA down by ~0.72x from 2023 anchor point baseline.")
