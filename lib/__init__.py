"""
Retirement Calculator Library - Data getters and utilities.

This module provides a clean functional API for accessing investment and asset data
from the data/ directory. Each module (stocks, bonds, assets) contains specialized
getter functions for its data type.

Example usage:

    from lib.stocks import get_stock, get_index_funds
    from lib.bonds import get_all_bonds
    
    # Get a specific stock
    amazon = get_stock('AMZN')
    
    # Get all index funds
    index_funds = get_index_funds()
    
    # Get all bonds
    all_bonds = get_all_bonds()
"""

from .plan_by_age import (
    retirement_401k_age_based_plan_phase_1,
    retirement_401k_age_based_plan_phase_2,
    retirement_401k_age_based_plan_phase_3,
    retirement_401k_full_plan,
    retirement_401k_custom_plan,
)
from .stocks import (
    get_all_stocks,
    get_stock,
    get_stocks_by_category,
    get_stocks_by_type,
    get_index_funds,
    get_etfs,
    get_individual_stocks,
    get_stocks_metadata,
    get_tickers,
    filter_by_expense_ratio,
    filter_by_volatility,
)
from .bonds import (
    get_all_bonds,
    get_bond,
    get_bonds_by_category,
    get_bonds_by_credit_quality,
    get_bonds_by_duration,
    get_short_term_bonds,
    get_intermediate_bonds,
    get_long_term_bonds,
    get_bonds_metadata,
    get_bond_tickers,
    filter_high_yield_bonds,
)
from .assets import (
    get_all_assets,
    get_asset,
    get_assets_by_type,
    get_asset_value_total,
    get_assets_metadata,
)

__all__ = [
    # Plan by age
    "retirement_401k_age_based_plan_phase_1",
    "retirement_401k_age_based_plan_phase_2",
    "retirement_401k_age_based_plan_phase_3",
    "retirement_401k_full_plan",
    "retirement_401k_custom_plan",
    # Stocks
    "get_all_stocks",
    "get_stock",
    "get_stocks_by_category",
    "get_stocks_by_type",
    "get_index_funds",
    "get_etfs",
    "get_individual_stocks",
    "get_stocks_metadata",
    "get_tickers",
    "filter_by_expense_ratio",
    "filter_by_volatility",
    # Bonds
    "get_all_bonds",
    "get_bond",
    "get_bonds_by_category",
    "get_bonds_by_credit_quality",
    "get_bonds_by_duration",
    "get_short_term_bonds",
    "get_intermediate_bonds",
    "get_long_term_bonds",
    "get_bonds_metadata",
    "get_bond_tickers",
    "filter_high_yield_bonds",
    # Assets
    "get_all_assets",
    "get_asset",
    "get_assets_by_type",
    "get_asset_value_total",
    "get_assets_metadata",
]
