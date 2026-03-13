import sys; sys.path.insert(0, '.')
from app.services.projection import get_user_projection
from app.services.comparison import get_comparison_data
from app.database import SessionLocal

print("=== Raw projection around retirement transition ===")
p = get_user_projection('Steven', current_year=2026)
for item in p['projected']:
    if item['year'] in range(2057, 2070):
        r = item['account_balances'].get('rental', 0)
        k = item['account_balances'].get('401k', 0)
        i = item['account_balances'].get('roth_ira', 0)
        age = 29 + (item['year'] - 2026)
        print(f"  {item['year']} (age {age}): total={item['balance']:>14,.2f}  401k={k:>12,.2f}  ira={i:>12,.2f}  rental={r:>12,.2f}")

print()
print("=== Chart projected (comparison) ===")
s = SessionLocal()
comp = get_comparison_data('Steven', s)
s.close()
for item in comp['projected']:
    if item['year'] in range(2057, 2070):
        ab = item.get('account_balances', {})
        r = ab.get('rental', 0)
        k = ab.get('401k', 0)
        i = ab.get('roth_ira', 0)
        age = 29 + (item['year'] - 2026)
        print(f"  {item['year']} (age {age}): total={item['balance']:>14,.2f}  401k={k:>12,.2f}  ira={i:>12,.2f}  rental={r:>12,.2f}")
