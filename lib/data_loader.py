"""Core data loading utilities for retirement calculator."""

import functools
import json
from typing import Any, Dict, List

from .constants import DATA_DIR, DATA_FILES


@functools.lru_cache(maxsize=16)
def load_json_file(filename: str) -> Dict[str, Any]:
    """
    Load and parse a JSON file from the data directory.

    Results are cached for the lifetime of the process; restart the server
    to reload changed data files.

    Args:
        filename: Name of the JSON file (e.g., 'stocks.json')
        
    Returns:
        Parsed JSON data as a dictionary
        
    Raises:
        FileNotFoundError: If the file doesn't exist
        json.JSONDecodeError: If the file is not valid JSON
    """
    filepath = DATA_DIR / filename
    
    if not filepath.exists():
        raise FileNotFoundError(f"Data file not found: {filepath}")
    
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_all_funds(filename: str) -> List[Dict[str, Any]]:
    """
    Get all funds from a data file.
    
    Args:
        filename: Name of the JSON file (e.g., 'stocks.json')
        
    Returns:
        List of fund dictionaries
    """
    data = load_json_file(filename)
    return data.get("funds", [])


def get_fund_by_ticker(filename: str, ticker: str) -> Dict[str, Any]:
    """
    Get a specific fund by ticker symbol.
    
    Args:
        filename: Name of the JSON file
        ticker: Ticker symbol to search for
        
    Returns:
        Fund dictionary if found
        
    Raises:
        ValueError: If ticker not found
    """
    funds = get_all_funds(filename)
    
    for fund in funds:
        if fund.get("ticker", "").upper() == ticker.upper():
            return fund
    
    raise ValueError(f"Ticker '{ticker}' not found in {filename}")


def get_metadata(filename: str) -> Dict[str, Any]:
    """Get metadata from a data file."""
    data = load_json_file(filename)
    return data.get("metadata", {})
