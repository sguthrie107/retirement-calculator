"""Projection service - wraps existing retirement calculator engine."""
import pandas as pd
import sys
from pathlib import Path

# Add parent directory to path to import lib modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from lib.plan_by_age import retirement_401k_full_plan
from lib.ira import retirement_ira_full_plan
from lib.display_utils import merge_projections


def get_user_projection(username: str, current_year: int = 2026) -> dict:
    """
    Get projected retirement balances for a user.
    
    Args:
        username: Name of user from users.json
        current_year: Current year for calculations
        
    Returns:
        Dict with 'projected' list of {year, balance, account_balances} dicts
    """
    try:
        # Run existing calculator engine
        df_401k = retirement_401k_full_plan(username, current_year=current_year)
        df_ira = retirement_ira_full_plan(username, current_year=current_year)
        
        # Merge projections
        merged = merge_projections(df_401k, df_ira, current_year=current_year)
        
        if merged.empty:
            return {"projected": []}
        
        # Build 401k and IRA lookup tables from individual projections
        df_401k_lookup = df_401k.set_index('year') if not df_401k.empty else pd.DataFrame()
        df_ira_lookup = df_ira.set_index('year') if not df_ira.empty else pd.DataFrame()
        
        # Convert to list of dicts with account breakdown
        projected = []
        for _, row in merged.iterrows():
            year = int(row["year"])
            total_balance = round(float(row["total_balance"]), 2)
            
            # Get account balances for this year
            account_balances = {}
            if year in df_401k_lookup.index:
                account_balances['401k'] = round(float(df_401k_lookup.loc[year, 'balance']), 2)
            if year in df_ira_lookup.index:
                account_balances['roth_ira'] = round(float(df_ira_lookup.loc[year, 'ira_balance']), 2)
            
            projected.append({
                "year": year,
                "balance": total_balance,
                "account_balances": account_balances
            })
        
        return {"projected": projected}
    except Exception as e:
        raise ValueError(f"Failed to compute projection for {username}: {str(e)}")


def get_401k_projection(username: str, current_year: int = 2026) -> list[dict]:
    """Get 401k-only projection."""
    df = retirement_401k_full_plan(username, current_year=current_year)
    return [
        {"year": int(row["year"]), "balance": round(float(row["balance"]), 2)}
        for _, row in df.iterrows()
    ]


def get_ira_projection(username: str, current_year: int = 2026) -> list[dict]:
    """Get IRA-only projection."""
    df = retirement_ira_full_plan(username, current_year=current_year)
    return [
        {"year": int(row["year"]), "balance": round(float(row["ira_balance"]), 2)}
        for _, row in df.iterrows()
    ]
