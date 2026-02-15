"""Comparison service - merges actual vs projected data."""
from sqlalchemy.orm import Session
from ..models import User, Account, ActualBalance
from .projection import get_user_projection


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
    
    # Get actual balances from database
    user = db.query(User).filter(User.name == username).first()
    
    actual = []
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
        
        # Combine 401k + IRA by year
        actual_by_year = {}
        for ab in actuals_401k + actuals_ira:
            actual_by_year[ab.year] = actual_by_year.get(ab.year, 0) + ab.balance
        
        actual = [
            {"year": year, "balance": round(balance, 2)}
            for year, balance in sorted(actual_by_year.items())
        ]
    
    # Compute deltas where we have both actual and projected
    deltas = compute_deltas(projected, actual)
    
    return {
        "projected": projected,
        "actual": actual,
        "deltas": deltas,
    }


def get_all_users_comparison(db: Session, current_year: int = 2026) -> dict:
    """
    Get projections for all users to compare side-by-side.
    
    Args:
        db: Database session
        current_year: Current year for projections
        
    Returns:
        Dict with 'users' list containing {username, projected} for each user
    """
    users = db.query(User).all()
    
    users_data = []
    for user in users:
        try:
            projection_data = get_user_projection(user.name, current_year)
            users_data.append({
                "username": user.name,
                "projected": projection_data["projected"]
            })
        except Exception:
            # Skip users that can't be projected
            continue
    
    return {"users": users_data}


def compute_deltas(projected: list[dict], actual: list[dict]) -> list[dict]:
    """
    Compute dollar and percentage deltas between actual and projected.
    
    Args:
        projected: List of {year, balance} dicts
        actual: List of {year, balance} dicts
        
    Returns:
        List of delta dicts with year, projected, actual, delta, delta_pct
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
            })
    
    return deltas
