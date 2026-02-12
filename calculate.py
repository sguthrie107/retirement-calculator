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

from lib.plan_by_age import (
    retirement_401k_full_plan,
    retirement_401k_custom_plan,
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

def _format_currency_col(series: pd.Series) -> pd.Series:
    """Format a numeric series as $1,234.56 strings."""
    return series.apply(lambda x: f"${x:>15,.2f}")


def _display_projection(df: pd.DataFrame) -> None:
    """Pretty-print the projection DataFrame and summary statistics."""
    if df.empty:
        print("\n  No projection data — check age and retirement age inputs.\n")
        return

    display = df.copy()
    currency_cols = [
        "salary",
        "employee_contribution",
        "employer_match",
        "total_contribution",
        "growth",
        "balance",
    ]
    for col in currency_cols:
        display[col] = _format_currency_col(display[col])

    # Pandas display settings for full output
    pd.set_option("display.max_rows", None)
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 220)
    pd.set_option("display.colheader_justify", "right")

    header = (
        f"  401K PROJECTION: {df['beneficiary'].iloc[0]}  |  "
        f"Ages {int(df['age'].iloc[0])} → {int(df['age'].iloc[-1])}"
    )

    print()
    print("=" * 180)
    print(header)
    print("=" * 180)
    print(display.to_string(index=False))
    print("=" * 180)

    # Summary
    final_balance = df["balance"].iloc[-1]
    total_contributions = df["total_contribution"].sum()
    total_growth = df["growth"].sum()
    total_employee = df["employee_contribution"].sum()
    total_employer = df["employer_match"].sum()

    print()
    print("  SUMMARY")
    print("  " + "-" * 50)
    print(f"  Final Balance at Age {int(df['age'].iloc[-1]):>3}:  ${final_balance:>15,.2f}")
    print(f"  Total Employee Contributions:   ${total_employee:>15,.2f}")
    print(f"  Total Employer Match:           ${total_employer:>15,.2f}")
    print(f"  Total Contributions:            ${total_contributions:>15,.2f}")
    print(f"  Total Investment Growth:        ${total_growth:>15,.2f}")
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
        print(f"\n  Loading profile for {name} …")
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

        print(f"\n  Calculating projection for {name} …")
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
