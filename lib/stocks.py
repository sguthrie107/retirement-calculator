"""Getter functions for stock data."""

from typing import Any, Dict, List

from .data_loader import get_all_funds, get_fund_by_ticker, get_metadata
from .constants import DATA_FILES


def get_all_stocks() -> List[Dict[str, Any]]:
    """
    Get all stocks and stock funds.
    
    Returns:
        List of all stocks/funds from stocks.json
    """
    return get_all_funds(DATA_FILES["STOCKS"])


def get_stock(ticker: str) -> Dict[str, Any]:
    """
    Get a specific stock by ticker.
    
    Args:
        ticker: Ticker symbol (e.g., 'AMZN', 'VOO')
        
    Returns:
        Stock/fund data dictionary
        
    Raises:
        ValueError: If ticker not found
    """
    return get_fund_by_ticker(DATA_FILES["STOCKS"], ticker)


def get_stocks_by_category(category: str) -> List[Dict[str, Any]]:
    """
    Get all stocks in a specific category.
    
    Args:
        category: Category name (e.g., 'US Large Cap', 'Technology / E-Commerce Growth')
        
    Returns:
        List of stocks in the specified category
    """
    stocks = get_all_stocks()
    return [s for s in stocks if s.get("category", "") == category]


def get_stocks_by_type(fund_type: str) -> List[Dict[str, Any]]:
    """
    Get all stocks of a specific type.
    
    Args:
        fund_type: Fund type (e.g., 'Index Fund', 'Individual Stock', 'ETF')
        
    Returns:
        List of stocks with the specified fund type
    """
    stocks = get_all_stocks()
    return [s for s in stocks if s.get("fund_type", "") == fund_type]


def get_index_funds() -> List[Dict[str, Any]]:
    """Get all index funds."""
    return get_stocks_by_type("Index Fund")


def get_etfs() -> List[Dict[str, Any]]:
    """Get all ETFs."""
    return get_stocks_by_type("ETF")


def get_individual_stocks() -> List[Dict[str, Any]]:
    """Get all individual stocks."""
    return get_stocks_by_type("Individual Stock")


def get_stocks_metadata() -> Dict[str, Any]:
    """Get metadata about the stocks data file."""
    return get_metadata(DATA_FILES["STOCKS"])


def get_tickers() -> List[str]:
    """Get a list of all available stock tickers."""
    stocks = get_all_stocks()
    return [s.get("ticker") for s in stocks if s.get("ticker")]


def filter_by_expense_ratio(max_expense_ratio: float) -> List[Dict[str, Any]]:
    """
    Get funds with expense ratio below a threshold.
    
    Args:
        max_expense_ratio: Maximum expense ratio (e.g., 0.1 for 0.1%)
        
    Returns:
        List of funds meeting the criteria
    """
    stocks = get_all_stocks()
    return [
        s for s in stocks
        if s.get("expense_ratio") is not None and s.get("expense_ratio") <= max_expense_ratio
    ]


def filter_by_volatility(max_volatility: float) -> List[Dict[str, Any]]:
    """
    Get funds with volatility below a threshold.
    
    Args:
        max_volatility: Maximum volatility percentage
        
    Returns:
        List of funds meeting the criteria
    """
    stocks = get_all_stocks()
    return [
        s for s in stocks
        if s.get("volatility_pct") is not None and s.get("volatility_pct") <= max_volatility
    ]
