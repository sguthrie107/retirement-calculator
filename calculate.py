"""
Interactive 401k Retirement Projection Calculator

Prompts the user for basic financial inputs (similar to Bankrate, NerdWallet,
etc.) and displays a year-by-year projection showing how their 401k balance
grows through three investment phases:

  Phase 1 (up to 50):  70% US Stock / 30% Foreign Stock
  Phase 2 (50 to 65):  60% US Stock / 20% Foreign Stock / 20% Bonds
  Phase 3 (65+):       40% US Stock / 20% Foreign Stock / 40% Bonds

Usage:
    python calculate.py
"""

import sys
import pandas as pd
from tabulate import tabulate

from lib.plan_by_age import (
    retirement_401k_full_plan,
    retirement_401k_custom_plan,
    calculate_annualized_return,
)


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------

def _input_float(prompt: str, default: float = None) -> float:
    """Prompt for a float value with optional default."""
    suffix = f" [{default}]" if default is not None else ""
    while True:
        raw = input(f"  {prompt}{suffix}: ").strip()
        if not raw and default is not None:
            return default
        try:
            return float(raw)
        except ValueError:
            print("    → Please enter a valid number.")


def _input_int(prompt: str, default: int = None) -> int:
    """Prompt for an integer value with optional default."""
    suffix = f" [{default}]" if default is not None else ""
    while True:
        raw = input(f"  {prompt}{suffix}: ").strip()
        if not raw and default is not None:
            return default
        try:
            return int(raw)
        except ValueError:
            print("    → Please enter a valid whole number.")


def _input_choice(prompt: str, options: dict) -> str:
    """Prompt user to pick from numbered options. Returns the value."""
    for key, label in options.items():
        print(f"    {key}. {label}")
    while True:
        raw = input(f"  {prompt}: ").strip()
        if raw in options:
            return options[raw]
        print(f"    → Please enter one of: {', '.join(options.keys())}")


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _format_currency(value: float) -> str:
    """Format a numeric value as $1,234.56 string."""
    return f"${value:,.2f}"


def _display_projection(df: pd.DataFrame) -> None:
    """Pretty-print the projection DataFrame as an Excel-like table."""
    if df.empty:
        print("\n  No projection data — check age and retirement age inputs.\n")
        return

    beneficiary = df['beneficiary'].iloc[0]
    start_age = int(df['age'].iloc[0])
    end_age = int(df['age'].iloc[-1])

    # Prepare data for display
    display_data = []
    for idx, row in df.iterrows():
        display_data.append({
            "Age": int(row['age']),
            "Year": int(row['year']),
            "Phase": row.get('phase', 'N/A'),
            "Salary": _format_currency(row['salary']),
            "Employee Contrib": _format_currency(row['employee_contribution']),
            "Employer Match": _format_currency(row['employer_match']),
            "Dividend Income": _format_currency(row.get('dividend_income', 0)),
            "Price Appreciation": _format_currency(row.get('price_appreciation', 0)),
            "Balance": _format_currency(row['balance']),
        })

    print()
    print("=" * 160)
    print(f"  401K PROJECTION: {beneficiary} (Ages {start_age} to {end_age})")
    print("=" * 160)
    
    # Use tabulate to create an Excel-like table
    table_output = tabulate(
        display_data,
        headers="keys",
        tablefmt="grid",
        floatfmt=".2f",
    )
    print(table_output)
    print("=" * 160)

    # Summary statistics
    final_balance = df["balance"].iloc[-1]
    total_contributions = df["total_contribution"].sum()
    total_growth = df["growth"].sum()
    total_employee = df["employee_contribution"].sum()
    total_employer = df["employer_match"].sum()
    annualized_return = calculate_annualized_return(df)

    summary_data = [
        ["Final Balance at Age " + str(end_age), _format_currency(final_balance)],
        ["Total Employee Contributions", _format_currency(total_employee)],
        ["Total Employer Match", _format_currency(total_employer)],
        ["Total Contributions", _format_currency(total_contributions)],
        ["Total Investment Growth", _format_currency(total_growth)],
        ["Average Annualized Return", f"{annualized_return * 100:.2f}%"],
    ]

    print()
    print("  SUMMARY STATISTICS")
    print("  " + "=" * 70)
    summary_output = tabulate(
        summary_data,
        tablefmt="plain",
        floatfmt=".2f",
    )
    for line in summary_output.split('\n'):
        print("  " + line)
    print("  " + "=" * 70)
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print()
    print("=" * 60)
    print("       401K RETIREMENT PROJECTION CALCULATOR")
    print("=" * 60)
    print()
    print("  Choose an option:")
    print("    1. Use a stored profile (Steven or Alyssa)")
    print("    2. Enter your own values")
    print()

    mode = _input_choice("Select", {"1": "stored", "2": "custom"})

    if mode == "stored":
        print()
        name = _input_choice(
            "Select profile",
            {"1": "Steven", "2": "Alyssa"},
        )
        print(f"\n  Loading profile for {name}...")
        df = retirement_401k_full_plan(name)
    else:
        print()
        print("  Enter your information below.")
        print("  " + "-" * 40)
        name = input("  Your name: ").strip() or "User"
        age = _input_int("Current age")
        salary = _input_float("Annual salary ($)")
        contrib = _input_float("Your contribution (%)", default=15)
        match = _input_float("Employer match (%)", default=5)
        raise_pct = _input_float("Expected annual salary increase (%)", default=3)
        ret_age = _input_int("Retirement age", default=65)
        balance = _input_float("Current 401k balance ($)", default=0)

        print()
        print("  Fund provider (determines which mutual funds to use):")
        provider = _input_choice(
            "Select provider",
            {"1": "Vanguard", "2": "Fidelity"},
        )

        print(f"\n  Calculating projection for {name}...")
        df = retirement_401k_custom_plan(
            name=name,
            age=age,
            salary=salary,
            contribution_pct=contrib / 100.0,
            match_pct=match / 100.0,
            salary_increase_pct=raise_pct / 100.0,
            retirement_age=ret_age,
            starting_balance=balance,
            fund_provider=provider,
        )

    _display_projection(df)


if __name__ == "__main__":
    main()
