"""
Interactive Retirement Projection Calculator (401k + IRA)

Prompts the user for basic financial inputs (similar to Bankrate, NerdWallet,
etc.) and displays a year-by-year projection showing how their 401k and IRA
balances grow through three investment phases:

  401k Phases:
    Phase 1 (up to 50):  70% US Stock / 30% Foreign Stock
    Phase 2 (50 to 65):  60% US Stock / 20% Foreign Stock / 20% Bonds
    Phase 3 (65+):       40% US Stock / 20% Foreign Stock / 40% Bonds

  IRA Phases:
    Phase 1 (up to 50):  60% FZROX / 30% FZILX / 10% FSPGX
    Phase 2 (51 to 65):  60% FZROX / 20% FZILX / 20% FUAMX
    Phase 3 (65+):       40% FZROX / 20% FZILX / 15% FUAMX / 15% FNAX / 10% FIPDX

Usage:
    python calculate.py
"""

import sys
import pandas as pd
from tabulate import tabulate

from lib.plan_by_age import (
    retirement_401k_full_plan,
    retirement_401k_custom_plan,
)
from lib.ira import (
    retirement_ira_full_plan,
)
from lib.display_utils import (
    merge_projections,
    prepare_unified_display_data,
    calculate_summary_statistics,
    prepare_401k_display_data,
    calculate_401k_summary,
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

    # Get display data and summary from library
    display_data = prepare_401k_display_data(df)
    summary = calculate_401k_summary(df)
    
    beneficiary = summary["beneficiary"]
    start_age = summary["start_age"]
    end_age = summary["end_age"]

    # Format currency values for display
    for row in display_data:
        row["Salary"] = _format_currency(row["Salary"])
        row["Employee Contrib"] = _format_currency(row["Employee Contrib"])
        row["Employer Match"] = _format_currency(row["Employer Match"])
        row["Dividend Income"] = _format_currency(row["Dividend Income"])
        row["Price Appreciation"] = _format_currency(row["Price Appreciation"])
        row["Balance"] = _format_currency(row["Balance"])

    print()
    print("=" * 160)
    print(f"  401K PROJECTION: {beneficiary} (Ages {start_age} to {end_age})")
    print("=" * 160)
    
    table_output = tabulate(
        display_data,
        headers="keys",
        tablefmt="grid",
        floatfmt=".2f",
    )
    print(table_output)
    print("=" * 160)

    # Summary statistics
    summary_data = [
        ["Final Balance at Age " + str(end_age), _format_currency(summary["final_balance"])],
        ["Total Employee Contributions", _format_currency(summary["total_employee"])],
        ["Total Employer Match", _format_currency(summary["total_employer"])],
        ["Total Contributions", _format_currency(summary["total_contributions"])],
        ["Total Investment Growth", _format_currency(summary["total_growth"])],
        ["Average Annualized Return", f"{summary['annualized_return'] * 100:.2f}%"],
    ]

    print()
    print("  401K SUMMARY STATISTICS")
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


def _display_unified_projection(
    df_401k: pd.DataFrame,
    df_ira: pd.DataFrame,
) -> None:
    """Display a unified table with both 401k and IRA data merged by year."""
    if df_401k.empty and df_ira.empty:
        print("\n  No projection data available.\n")
        return

    # Get merged data and summary from library
    merged = merge_projections(df_401k, df_ira)
    display_data = prepare_unified_display_data(merged)
    summary = calculate_summary_statistics(df_401k, df_ira)
    
    beneficiary = summary["beneficiary"]
    start_age = summary["start_age"]
    end_age = summary["end_age"]
    
    # Format currency values for display
    for row in display_data:
        row["Total Balance"] = _format_currency(row["Total Balance"])
        row["401k Balance"] = _format_currency(row["401k Balance"])
        row["IRA Balance"] = _format_currency(row["IRA Balance"])
        row["Contributions"] = _format_currency(row["Contributions"])
    
    print()
    print("=" * 130)
    print(f"  RETIREMENT PROJECTION: {beneficiary} (Ages {start_age} to {end_age})")
    print("=" * 130)
    
    table_output = tabulate(
        display_data,
        headers="keys",
        tablefmt="grid",
        floatfmt=".2f",
    )
    print(table_output)
    print("=" * 130)
    
    # Summary statistics
    summary_data = [
        ["Final 401k Balance", _format_currency(summary["final_401k"])],
        ["Final IRA Balance", _format_currency(summary["final_ira"])],
        ["Combined Balance at Age " + str(end_age), _format_currency(summary["combined_balance"])],
        ["", ""],
        ["Total 401k Contributions", _format_currency(summary["total_401k_contributions"])],
        ["Total IRA Contributions", _format_currency(summary["total_ira_contributions"])],
        ["Total Contributions (All)", _format_currency(summary["total_contributions"])],
        ["", ""],
        ["Total 401k Growth", _format_currency(summary["total_401k_growth"])],
        ["Total IRA Growth", _format_currency(summary["total_ira_growth"])],
        ["Total Growth (All)", _format_currency(summary["total_growth"])],
        ["", ""],
        ["401k Annualized Return", f"{summary['annualized_401k'] * 100:.2f}%"],
        ["IRA Annualized Return", f"{summary['annualized_ira'] * 100:.2f}%"],
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
    print("       RETIREMENT PROJECTION CALCULATOR")
    print("=" * 60)
    print()
    print("  Choose an option:")
    print("    1. Use a stored profile (Steven or Alyssa)")
    print("    2. Enter your own values (401k only)")
    print()

    mode = _input_choice("Select", {"1": "stored", "2": "custom"})

    if mode == "stored":
        print()
        name = _input_choice(
            "Select profile",
            {"1": "Steven", "2": "Alyssa"},
        )
        print(f"\n  Loading profile for {name}...")

        df_401k = retirement_401k_full_plan(name)
        df_ira = retirement_ira_full_plan(name)

        _display_unified_projection(df_401k, df_ira)
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
