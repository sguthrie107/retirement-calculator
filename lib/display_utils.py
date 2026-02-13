"""
Display utilities for retirement calculator.

Handles data preparation, merging, and summary calculations for display purposes.
The actual rendering (tabulate, print) remains in calculate.py.
"""

from typing import Dict, List, Tuple, Any
import pandas as pd
from pandas import DataFrame

from .plan_by_age import calculate_annualized_return
from .ira import calculate_ira_annualized_return


def merge_projections(df_401k: DataFrame, df_ira: DataFrame) -> DataFrame:
    """
    Merge 401k and IRA projections into a unified DataFrame by year and age.
    
    Args:
        df_401k: 401k projection DataFrame
        df_ira: IRA projection DataFrame
        
    Returns:
        Merged DataFrame with columns for both account types and totals
    """
    if df_401k.empty and df_ira.empty:
        return DataFrame()
    
    # Merge on year and age
    merged = pd.merge(
        df_401k[["year", "age", "phase", "balance", "total_contribution"]],
        df_ira[["year", "age", "phase", "ira_balance", "ira_contribution"]],
        on=["year", "age"],
        how="outer",
        suffixes=("_401k", "_ira")
    ).fillna(0)
    
    # Sort by year
    merged = merged.sort_values("year").reset_index(drop=True)
    
    # Calculate combined totals
    merged["total_balance"] = merged["balance"] + merged["ira_balance"]
    merged["total_contributions"] = merged["total_contribution"] + merged["ira_contribution"]
    
    # Resolve phase (prefer 401k phase if both exist)
    merged["phase_display"] = merged.apply(
        lambda row: row.get("phase_401k", row.get("phase_ira", "N/A"))
        if row.get("phase_401k", 0) not in [0, ""]
        else row.get("phase_ira", "N/A"),
        axis=1
    )
    
    return merged


def prepare_unified_display_data(merged: DataFrame) -> List[Dict[str, Any]]:
    """
    Convert merged projection DataFrame into display-ready format.
    
    Args:
        merged: Output from merge_projections()
        
    Returns:
        List of dictionaries ready for tabulate display
    """
    if merged.empty:
        return []
    
    display_data = []
    for _, row in merged.iterrows():
        display_data.append({
            "Age": int(row["age"]),
            "Year": int(row["year"]),
            "Phase": row["phase_display"],
            "Total Balance": row["total_balance"],
            "401k Balance": row["balance"],
            "IRA Balance": row["ira_balance"],
            "Contributions": row["total_contributions"],
        })
    
    return display_data


def calculate_summary_statistics(
    df_401k: DataFrame,
    df_ira: DataFrame,
) -> Dict[str, Any]:
    """
    Calculate all summary statistics for combined retirement projection.
    
    Args:
        df_401k: 401k projection DataFrame
        df_ira: IRA projection DataFrame
        
    Returns:
        Dictionary containing all summary statistics
    """
    # Extract final values
    final_401k = df_401k["balance"].iloc[-1] if not df_401k.empty else 0
    final_ira = df_ira["ira_balance"].iloc[-1] if not df_ira.empty else 0
    combined_balance = final_401k + final_ira
    
    # Calculate totals
    total_401k_contribs = df_401k["total_contribution"].sum() if not df_401k.empty else 0
    total_ira_contribs = df_ira["ira_contribution"].sum() if not df_ira.empty else 0
    total_401k_growth = df_401k["growth"].sum() if not df_401k.empty else 0
    total_ira_growth = df_ira["growth"].sum() if not df_ira.empty else 0
    
    # Calculate returns
    annualized_401k = calculate_annualized_return(df_401k) if not df_401k.empty else 0
    annualized_ira = calculate_ira_annualized_return(df_ira) if not df_ira.empty else 0
    
    # Get metadata
    beneficiary = (
        df_401k["beneficiary"].iloc[0]
        if not df_401k.empty
        else df_ira["beneficiary"].iloc[0]
        if not df_ira.empty
        else "Unknown"
    )
    
    start_age = (
        int(df_401k["age"].iloc[0])
        if not df_401k.empty
        else int(df_ira["age"].iloc[0])
        if not df_ira.empty
        else 0
    )
    
    end_age = (
        int(df_401k["age"].iloc[-1])
        if not df_401k.empty
        else int(df_ira["age"].iloc[-1])
        if not df_ira.empty
        else 0
    )
    
    return {
        # Balances
        "final_401k": final_401k,
        "final_ira": final_ira,
        "combined_balance": combined_balance,
        
        # Contributions
        "total_401k_contributions": total_401k_contribs,
        "total_ira_contributions": total_ira_contribs,
        "total_contributions": total_401k_contribs + total_ira_contribs,
        
        # Growth
        "total_401k_growth": total_401k_growth,
        "total_ira_growth": total_ira_growth,
        "total_growth": total_401k_growth + total_ira_growth,
        
        # Returns
        "annualized_401k": annualized_401k,
        "annualized_ira": annualized_ira,
        
        # Metadata
        "beneficiary": beneficiary,
        "start_age": start_age,
        "end_age": end_age,
    }


def prepare_401k_display_data(df: DataFrame) -> List[Dict[str, Any]]:
    """
    Convert 401k projection DataFrame into display-ready format.
    
    Args:
        df: 401k projection DataFrame
        
    Returns:
        List of dictionaries ready for tabulate display
    """
    if df.empty:
        return []
    
    display_data = []
    for _, row in df.iterrows():
        display_data.append({
            "Age": int(row['age']),
            "Year": int(row['year']),
            "Phase": row.get('phase', 'N/A'),
            "Salary": row['salary'],
            "Employee Contrib": row['employee_contribution'],
            "Employer Match": row['employer_match'],
            "Dividend Income": row.get('dividend_income', 0),
            "Price Appreciation": row.get('price_appreciation', 0),
            "Balance": row['balance'],
        })
    
    return display_data


def calculate_401k_summary(df: DataFrame) -> Dict[str, Any]:
    """
    Calculate summary statistics for 401k projection.
    
    Args:
        df: 401k projection DataFrame
        
    Returns:
        Dictionary containing summary statistics
    """
    if df.empty:
        return {}
    
    return {
        "beneficiary": df['beneficiary'].iloc[0],
        "start_age": int(df['age'].iloc[0]),
        "end_age": int(df['age'].iloc[-1]),
        "final_balance": df["balance"].iloc[-1],
        "total_contributions": df["total_contribution"].sum(),
        "total_growth": df["growth"].sum(),
        "total_employee": df["employee_contribution"].sum(),
        "total_employer": df["employer_match"].sum(),
        "annualized_return": calculate_annualized_return(df),
    }
