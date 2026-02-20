"""Comparison service - merges actual vs projected data."""
import json
from pathlib import Path

from sqlalchemy.orm import Session
from ..models import User, Account, ActualBalance
from .projection import get_user_projection


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _load_user_profile(username: str) -> dict:
    users_path = _project_root() / "data" / "users.json"
    with open(users_path, "r", encoding="utf-8") as f:
        users_data = json.load(f)

    for user in users_data.get("users", []):
        if user.get("name") == username:
            return user

    raise ValueError(f"User '{username}' not found in users.json")


def get_comparison_data(username: str, db: Session, current_year: int = 2026) -> dict:
    """
    Get actual vs projected comparison data for a user.
    
    Args:
        username: Name of user
        db: Database session
        current_year: Current year for projections
        
    Returns:
        Dict with 'projected', 'actual', and 'deltas' lists
    """
    # Get projected data from calculator engine
    projection_data = get_user_projection(username, current_year)
    projected = projection_data["projected"]
    profile = _load_user_profile(username)
    retirement_age = int(profile.get("retirement_age", 65))
    current_age = int(profile.get("age", 35))
    retirement_year = current_year + max(0, retirement_age - current_age)
    
    # Merge projected account_balances with actual account_balances
    # Create a merged account_balances map for ALL years
    all_account_balances = {}
    
    # First, populate with projected data
    for p in projected:
        year = p["year"]
        all_account_balances[year] = p.get("account_balances", {}).copy()
    
    # Get actual balances from database
    user = db.query(User).filter(User.name == username).first()
    
    actual = []
    balance_id_map = {}  # Maps (year) -> list of balance IDs
    timestamp_map = {}  # Maps (year) -> most recent timestamp
    account_balances_map = {}  # Maps (year) -> {account_type: balance}
    
    if user:
        # Get all actual balances for this user across all accounts
        actuals_401k = (
            db.query(ActualBalance)
            .join(Account)
            .filter(Account.user_id == user.id, Account.account_type == "401k")
            .order_by(ActualBalance.year)
            .all()
        )
        
        actuals_ira = (
            db.query(ActualBalance)
            .join(Account)
            .filter(Account.user_id == user.id, Account.account_type == "roth_ira")
            .order_by(ActualBalance.year)
            .all()
        )
        
        # Combine 401k + IRA by year, tracking separate balances
        actual_by_year = {}
        for ab in actuals_401k + actuals_ira:
            year = ab.year
            actual_by_year[year] = actual_by_year.get(year, 0) + ab.balance
            
            # Track account-specific balance
            if year not in account_balances_map:
                account_balances_map[year] = {}
            account_balances_map[year][ab.account.account_type] = round(ab.balance, 2)
            
            # Track balance IDs for this year
            if year not in balance_id_map:
                balance_id_map[year] = []
            balance_id_map[year].append(ab.id)
            # Track the most recent timestamp for this year
            if year not in timestamp_map or ab.recorded_at > timestamp_map[year]:
                timestamp_map[year] = ab.recorded_at
        
        actual = [
            {
                "year": year, 
                "balance": round(balance, 2), 
                "balance_ids": [int(bid) for bid in balance_id_map.get(year, [])], 
                "timestamp": timestamp_map.get(year),
                "account_balances": account_balances_map.get(year, {})
            }
            for year, balance in sorted(actual_by_year.items())
        ]
        
        # Merge actual account balances into the all_account_balances map
        for year, acct_bal in account_balances_map.items():
            all_account_balances[year] = acct_bal
    
    # Update projected list to use merged account_balances
    for p in projected:
        p["account_balances"] = all_account_balances.get(p["year"], p.get("account_balances", {}))
    
    # Debug logging
    print(f"DEBUG comparison.py: account_balances_map = {account_balances_map}")
    print(f"DEBUG comparison.py: actual data = {actual}")
    
    # Compute deltas where we have both actual and projected
    deltas = compute_deltas(projected, actual)
    
    print(f"DEBUG comparison.py: User {username} - actual data: {actual}")
    print(f"DEBUG comparison.py: Deltas computed: {deltas}")
    
    return {
        "projected": projected,
        "actual": actual,
        "deltas": deltas,
        "retirement_age": retirement_age,
        "retirement_year": retirement_year,
    }


def get_all_users_comparison(db: Session, current_year: int = 2026) -> dict:
    """
    Get projections for all users to compare side-by-side.
    All projections are padded to the same end year for uniform comparison.
    
    Args:
        db: Database session
        current_year: Current year for projections
        
    Returns:
        Dict with 'users' list containing {username, projected} for each user.
        All projections extended to same end year with null values for padding.
    """
    users = db.query(User).all()
    
    users_data = []
    max_year = 0
    
    # First pass: get all projections and find max year
    all_projections = []
    for user in users:
        try:
            projection_data = get_user_projection(user.name, current_year)
            projected = projection_data["projected"]
            all_projections.append({
                "username": user.name,
                "projected": projected
            })
            # Track the maximum year across all users
            if projected:
                max_year = max(max_year, max(p["year"] for p in projected))
        except Exception:
            # Skip users that can't be projected
            continue
    
    # Second pass: pad all projections to max_year
    for user_proj in all_projections:
        projected = user_proj["projected"]
        
        if projected and max_year > 0:
            # Create a set of years that already have data
            existing_years = {p["year"] for p in projected}
            
            # Add null entries for missing years from max year of this user to max_year
            last_year = max(p["year"] for p in projected)
            for year in range(last_year + 1, max_year + 1):
                projected.append({"year": year, "balance": None})
            
            # Sort by year
            projected.sort(key=lambda x: x["year"])
        
        users_data.append(user_proj)
    
    return {"users": users_data}


def compute_deltas(projected: list[dict], actual: list[dict]) -> list[dict]:
    """
    Compute dollar and percentage deltas between actual and projected.
    
    Args:
        projected: List of {year, balance} dicts
        actual: List of {year, balance, balance_ids, timestamp, account_balances} dicts
        
    Returns:
        List of delta dicts with year, projected, actual, delta, delta_pct, balance_ids, timestamp, account_balances
    """
    proj_by_year = {p["year"]: p["balance"] for p in projected}
    deltas = []
    
    for a in actual:
        year = a["year"]
        if year in proj_by_year:
            proj_bal = proj_by_year[year]
            actual_bal = a["balance"]
            diff = actual_bal - proj_bal
            pct = (diff / proj_bal * 100) if proj_bal else 0
            
            deltas.append({
                "year": year,
                "projected": round(proj_bal, 2),
                "actual": round(actual_bal, 2),
                "delta": round(diff, 2),
                "delta_pct": round(pct, 2),
                "balance_ids": a.get("balance_ids", []),
                "timestamp": a.get("timestamp"),
                "account_balances": a.get("account_balances", {}),
            })
    
    return deltas
