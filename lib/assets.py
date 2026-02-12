"""Getter functions for asset data."""

from typing import Any, Dict, List

from .data_loader import get_metadata, load_json_file
from .constants import DATA_FILES


def get_all_assets() -> List[Dict[str, Any]]:
    """
    Get all assets.
    
    Returns:
        List of all assets from assets.json
    """
    data = load_json_file(DATA_FILES["ASSETS"])
    return data.get("assets", [])


def get_asset(asset_id: str) -> Dict[str, Any]:
    """
    Get a specific asset by ID.
    
    Args:
        asset_id: Asset identifier
        
    Returns:
        Asset data dictionary
        
    Raises:
        ValueError: If asset not found
    """
    assets = get_all_assets()
    
    for asset in assets:
        if asset.get("id", "") == asset_id:
            return asset
    
    raise ValueError(f"Asset '{asset_id}' not found in assets.json")


def get_assets_by_type(asset_type: str) -> List[Dict[str, Any]]:
    """
    Get all assets of a specific type.
    
    Args:
        asset_type: Asset type (e.g., 'cash', 'real_estate', 'retirement_account')
        
    Returns:
        List of assets of the specified type
    """
    assets = get_all_assets()
    return [a for a in assets if a.get("type", "") == asset_type]


def get_asset_value_total() -> float:
    """
    Calculate total value of all assets.
    
    Returns:
        Total asset value
    """
    assets = get_all_assets()
    return sum(a.get("current_value", 0) for a in assets)


def get_assets_metadata() -> Dict[str, Any]:
    """Get metadata about the assets data file."""
    return get_metadata(DATA_FILES["ASSETS"])
