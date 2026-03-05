import sys; sys.path.insert(0, '.')
from app.services.comparison import get_comparison_data
from app.database import SessionLocal

s = SessionLocal()
comp = get_comparison_data('Steven', s)
s.close()

key_years = {2026, 2030, 2035, 2040, 2045, 2050, 2055, 2060, 2061, 2062}

print("=== Updated chart projection (with rental income) ===")
for p in comp['projected']:
    if p['year'] in key_years:
        print(f"  {p['year']}: {p['balance']:>14,.0f}")

print()
print("MC P50 at retirement (age 65 start): 8,280,853")
print("Old chart at 2062:                   4,949,666")
