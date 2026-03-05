import sys; sys.path.insert(0, '.')
from app.services.projection import get_user_projection
from app.services.comparison import get_comparison_data
from app.database import SessionLocal

proj = get_user_projection('Steven', current_year=2026)
key_years = {2026,2030,2035,2040,2045,2050,2055,2060,2061,2062}
print("=== New raw projection (with rental) ===")
for p in proj['projected']:
    if p['year'] in key_years:
        rental = p['account_balances'].get('rental', 0)
        print(f"  {p['year']}: total={p['balance']:>14,.0f}  (401k={p['account_balances'].get('401k',0):>12,.0f}  ira={p['account_balances'].get('roth_ira',0):>12,.0f}  rental={rental:>12,.0f})")

print()
print("=== Comparison chart projection (with chart_seed scaling) ===")
s = SessionLocal()
comp = get_comparison_data('Steven', s)
s.close()
for p in comp['projected']:
    if p['year'] in key_years:
        print(f"  {p['year']}: {p['balance']:>14,.0f}")

print()
print("MC P50 at retirement: 8,280,853")
