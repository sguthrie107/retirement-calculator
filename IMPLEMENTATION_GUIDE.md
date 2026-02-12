# Retirement Calculator - Phase 1 Implementation Guide

## Overview
This document explains the comprehensive implementation of `retirement_401k_age_based_plan_phase_1()` and the supporting architecture for the retirement planning system.

## Architecture

### Data Structure: `users.json`
Location: `data/users.json`

Contains beneficiary-specific 401k configuration:
- **Basic Info**: Name, current age, current 401k balance
- **Contribution Details**: 
  - Annual salary
  - Employee contribution percentage
  - Company match percentage
  - Contribution frequency
  - Vesting percentage
- **Portfolio Allocation**:
  - 70% US Total Market Index (VTSAX)
  - 30% International Total Market Index (VTIAX)
- **Return Assumption**: 9% annual projected return

**Supported Beneficiaries**: Steven and Alyssa

### Core Function: `retirement_401k_age_based_plan_phase_1()`

**Purpose**: Calculate year-by-year 401k projections from current age through age 50.

**Signature**:
```python
def retirement_401k_age_based_plan_phase_1(
    beneficiary: str,
    age: int,
    current_year: int = None,
    portfolio: DataFrame = None
) -> DataFrame
```

**Parameters**:
- `beneficiary`: Name of beneficiary ('Steven' or 'Alyssa')
- `age`: Current age (must be < 50)
- `current_year`: Starting year for projections (defaults to current year)
- `portfolio`: Existing portfolio DataFrame to append to (for chaining multiple beneficiaries)

**Returns**: 
DataFrame with columns:
- `beneficiary`: Name of person
- `age_at_year_end`: Age at end of projection year
- `phase`: Phase name ("Phase 1")
- `year`: Calendar year
- `annual_contribution`: Total annual contribution (employee + employer match)
- `balance_end_of_year`: Projected 401k balance at year end

### Helper Functions

#### `_load_user_data(beneficiary: str)`
Loads beneficiary-specific configuration from `users.json`. Raises ValueError if user not found.

#### `_validate_phase_1_inputs(beneficiary: str, age: int)`
Validates that:
- Beneficiary name is a non-empty string
- Age is a positive integer less than 50

#### `_calculate_annual_contribution(salary, contribution_pct, company_match_pct)`
Calculates total annual contribution:
```
Total = (Salary × Employee%) + (Salary × Company Match%)
```

#### `_project_404k_balance(start_balance, years_list, salary, contribution_pct, match_pct, return_pct)`
Year-by-year projection logic:
1. Add annual contribution to current balance
2. Apply compound annual return
3. Repeat for each year

## Usage Examples

### Single Beneficiary
```python
from lib.plan_by_age import retirement_401k_age_based_plan_phase_1

# Get Steven's Phase 1 plan
steven_plan = retirement_401k_age_based_plan_phase_1("Steven", 35)
print(steven_plan)
```

### Multiple Beneficiaries
```python
import pandas as pd
from lib.plan_by_age import retirement_401k_age_based_plan_phase_1

steven_plan = retirement_401k_age_based_plan_phase_1("Steven", 35)
alyssa_plan = retirement_401k_age_based_plan_phase_1("Alyssa", 32)

combined = pd.concat([steven_plan, alyssa_plan], ignore_index=True)
print(combined)
```

### Specified Year
```python
# Project starting from 2025 instead of current year
plan = retirement_401k_age_based_plan_phase_1("Steven", 35, current_year=2025)
```

## Portfolio Design

### Phase 1 (Current Age - 50)
**Asset Allocation**: 100% Stocks
- 70% US Total Market Index (VTSAX)
- 30% International Total Market Index (VTIAX)
- Expected annual return: 9%
- Risk level: AGGRESSIVE (suitable for long-term growth)

This aggressive allocation is appropriate because:
- Long time horizon (15+ years until age 50)
- Dollar-cost averaging through regular contributions
- Historical equity returns support 9% assumption
- Volatility is manageable over 15+ year periods

## Key Design Decisions

1. **Immutable User Data**: User configuration is loaded from `users.json`, not hardcoded
2. **Compound Returns**: Uses end-of-year balance application for returns
3. **Year-by-Year Granularity**: Each row represents one calendar year
4. **DataFrame Chaining**: `portfolio` parameter allows combining multiple beneficiaries
5. **Type Safety**: Uses type hints throughout for clarity and IDE support
6. **Validation**: Comprehensive input validation with clear error messages
7. **Helper Functions**: Private helper functions (prefixed with `_`) keep implementation clean

## Future Enhancements

1. **Phase 2 Implementation** (Age 50-65): 70% stocks / 30% bonds
2. **Phase 3 Implementation** (Age 65+): 40% stocks / 60% bonds
3. **Inflation Adjustment**: Model salary increases and inflation
4. **Tax Calculations**: Account for tax-deferred growth and distributions
5. **Scenario Analysis**: Monte Carlo simulations with variable returns
6. **Education Planning**: Similar framework for 529 plans and education savings
7. **IRA Calculations**: Separate functions for Traditional and Roth IRAs

## Files Modified

1. `data/users.json` - Created with beneficiary configuration
2. `lib/constants.py` - Added USERS_FILE constant
3. `lib/plan_by_age.py` - Complete implementation of Phase 1
4. `demo_phase_1.py` - Example usage script

## Running the Demo

```bash
python demo_phase_1.py
```

This will show projections for both Steven and Alyssa through age 50.
