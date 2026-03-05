import sys; sys.path.insert(0, '.')
from app.services.projection import get_user_projection
proj = get_user_projection('Steven', current_year=2026)
key_years = {2026,2030,2035,2040,2045,2050,2055,2060,2062}
for p in proj['projected']:
    if p['year'] in key_years:
        rental = p['account_balances'].get('rental', 0)
        print(f"{p['year']}: total={p['balance']:>14,.0f}  rental={rental:>12,.0f}")
