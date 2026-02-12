"""Getter functions for bond data."""

from typing import Any, Dict, List

from .data_loader import get_all_funds, get_fund_by_ticker, get_metadata
from .constants import DATA_FILES


def get_all_bonds() -> List[Dict[str, Any]]:
    """
    Get all bonds and bond funds.
    
    Returns:
        List of all bonds/funds from bonds.json
    """
    return get_all_funds(DATA_FILES["BONDS"])


def get_bond(ticker: str) -> Dict[str, Any]:
    """
    Get a specific bond fund by ticker.
    
    Args:
        ticker: Ticker symbol (e.g., 'BND', 'FXNAX')
        
    Returns:
        Bond fund data dictionary
        
    Raises:
        ValueError: If ticker not found
    """
    return get_fund_by_ticker(DATA_FILES["BONDS"], ticker)


def get_bonds_by_category(category: str) -> List[Dict[str, Any]]:
    """
    Get all bonds in a specific category.
    
    Args:
        category: Category name (e.g., 'Total Bond Market', 'Corporate Bonds')
        
    Returns:
        List of bonds in the specified category
    """
    bonds = get_all_bonds()
    return [b for b in bonds if b.get("category", "") == category]


def get_bonds_by_credit_quality(quality: str) -> List[Dict[str, Any]]:
    """
    Get all bonds with a specific credit quality rating.
    
    Args:
        quality: Credit quality (e.g., 'Investment Grade', 'High Yield')
        
    Returns:
        List of bonds with the specified credit quality
    """
    bonds = get_all_bonds()
    return [b for b in bonds if b.get("credit_quality", "") == quality]


def get_bonds_by_duration(min_duration: float = None, max_duration: float = None) -> List[Dict[str, Any]]:
    """
    Get bonds filtered by duration range.
    
    Args:
        min_duration: Minimum duration in years (optional)
        max_duration: Maximum duration in years (optional)
        
    Returns:
        List of bonds within the duration range
    """
    bonds = get_all_bonds()
    filtered = bonds
    
    if min_duration is not None:
        filtered = [b for b in filtered if b.get("duration_years", 0) >= min_duration]
    
    if max_duration is not None:
        filtered = [b for b in filtered if b.get("duration_years", 0) <= max_duration]
    
    return filtered


def get_short_term_bonds() -> List[Dict[str, Any]]:
    """Get bonds with short duration (< 3 years)."""
    return get_bonds_by_duration(max_duration=3.0)


def get_intermediate_bonds() -> List[Dict[str, Any]]:
    """Get bonds with intermediate duration (3-10 years)."""
    return get_bonds_by_duration(min_duration=3.0, max_duration=10.0)


def get_long_term_bonds() -> List[Dict[str, Any]]:
    """Get bonds with long duration (> 10 years)."""
    return get_bonds_by_duration(min_duration=10.0)


def get_bonds_metadata() -> Dict[str, Any]:
    """Get metadata about the bonds data file."""
    return get_metadata(DATA_FILES["BONDS"])


def get_bond_tickers() -> List[str]:
    """Get a list of all available bond tickers."""
    bonds = get_all_bonds()
    return [b.get("ticker") for b in bonds if b.get("ticker")]


def filter_high_yield_bonds(min_yield: float) -> List[Dict[str, Any]]:
    """
    Get bonds with yield above a threshold.
    
    Args:
        min_yield: Minimum yield percentage
        
    Returns:
        List of bonds meeting the criteria
    """
    bonds = get_all_bonds()
    return [
        b for b in bonds
        if b.get("current_yield_pct") is not None and b.get("current_yield_pct") >= min_yield
    ]


def filter_by_expense_ratio(max_expense_ratio: float) -> List[Dict[str, Any]]:
    """
    Get bond funds with expense ratio below a threshold.
    
    Args:
        max_expense_ratio: Maximum expense ratio (e.g., 0.5 for 0.5%)
        
    Returns:
        List of funds meeting the criteria
    """
    bonds = get_all_bonds()
    return [
        b for b in bonds
        if b.get("expense_ratio") is not None and b.get("expense_ratio") <= max_expense_ratio
    ]
