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
from lib import ui


def _display_projection(df: pd.DataFrame) -> None:
    """Pretty-print the projection DataFrame as an Excel-like table."""
    if df.empty:
        ui.print_error("No projection data — check age and retirement age inputs.")
        return

    # Get display data and summary from library
    display_data = prepare_401k_display_data(df)
    summary = calculate_401k_summary(df)
    
    beneficiary = summary["beneficiary"]
    start_age = summary["start_age"]
    end_age = summary["end_age"]

    # Format currency values for display
    for row in display_data:
        row["Salary"] = ui.format_currency(row["Salary"])
        row["Employee Contrib"] = ui.format_currency(row["Employee Contrib"])
        row["Employer Match"] = ui.format_currency(row["Employer Match"])
        row["Dividend Income"] = ui.format_currency(row["Dividend Income"])
        row["Price Appreciation"] = ui.format_currency(row["Price Appreciation"])
        row["Balance"] = ui.format_currency(row["Balance"])

    ui.print_data_panel(
        f"401K PROJECTION: {beneficiary} (Ages {start_age} to {end_age})",
        tabulate(
            display_data,
            headers="keys",
            tablefmt="grid",
            floatfmt=".2f",
        )
    )

    # Summary statistics
    summary_data = [
        ["Final Balance at Age " + str(end_age), ui.format_currency(summary["final_balance"])],
        ["Total Employee Contributions", ui.format_currency(summary["total_employee"])],
        ["Total Employer Match", ui.format_currency(summary["total_employer"])],
        ["Total Contributions", ui.format_currency(summary["total_contributions"])],
        ["Total Investment Growth", ui.format_currency(summary["total_growth"])],
        ["Average Annualized Return", f"{summary['annualized_return'] * 100:.2f}%"],
    ]

    ui.print_data_panel(
        "401K SUMMARY STATISTICS",
        tabulate(
            summary_data,
            tablefmt="plain",
            floatfmt=".2f",
        )
    )
    ui.print_divider()


def _display_unified_projection(
    df_401k: pd.DataFrame,
    df_ira: pd.DataFrame,
) -> None:
    """Display a unified table with both 401k and IRA data merged by year."""
    if df_401k.empty and df_ira.empty:
        ui.print_error("No projection data available.")
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
        row["Total Balance"] = ui.format_currency(row["Total Balance"])
        row["401k Balance"] = ui.format_currency(row["401k Balance"])
        row["IRA Balance"] = ui.format_currency(row["IRA Balance"])
        row["Contributions"] = ui.format_currency(row["Contributions"])
    
    ui.print_data_panel(
        f"RETIREMENT PROJECTION: {beneficiary} (Ages {start_age} to {end_age})",
        tabulate(
            display_data,
            headers="keys",
            tablefmt="grid",
            floatfmt=".2f",
        )
    )
    
    # Summary statistics
    summary_data = [
        ["Final 401k Balance", ui.format_currency(summary["final_401k"])],
        ["Final IRA Balance", ui.format_currency(summary["final_ira"])],
        ["Combined Balance at Age " + str(end_age), ui.format_currency(summary["combined_balance"])],
        ["", ""],
        ["Total 401k Contributions", ui.format_currency(summary["total_401k_contributions"])],
        ["Total IRA Contributions", ui.format_currency(summary["total_ira_contributions"])],
        ["Total Contributions (All)", ui.format_currency(summary["total_contributions"])],
        ["", ""],
        ["Total 401k Growth", ui.format_currency(summary["total_401k_growth"])],
        ["Total IRA Growth", ui.format_currency(summary["total_ira_growth"])],
        ["Total Growth (All)", ui.format_currency(summary["total_growth"])],
        ["", ""],
        ["401k Annualized Return", f"{summary['annualized_401k'] * 100:.2f}%"],
        ["IRA Annualized Return", f"{summary['annualized_ira'] * 100:.2f}%"],
    ]
    
    ui.print_data_panel(
        "SUMMARY STATISTICS",
        tabulate(
            summary_data,
            tablefmt="plain",
            floatfmt=".2f",
        )
    )
    ui.print_divider()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # Display the control panel header
    ui.print_header()
    
    # Main menu
    ui.print_section("SYSTEM SELECTION")
    mode = ui.input_choice(
        "Select operational mode",
        {"1": "Load Stored Profile", "2": "Enter Custom Parameters"}
    )
    
    # Optional post-retirement calculation
    post_ret_years = 0
    calc_post_ret = ui.input_string("Calculate post-retirement growth? (y/n)", default="n").lower()
    if calc_post_ret.startswith("y"):
        post_ret_years = ui.input_int("Years to project after retirement", default=15)

    if mode == "Load Stored Profile":
        ui.print_section("PROFILE SELECTION")
        name = ui.input_choice(
            "Select a profile",
            {"1": "Steven", "2": "Alyssa"}
        )
        
        ui.print_status(f"Initializing projection for {name}...", "info")
        ui.print_divider()
        
        df_401k = retirement_401k_full_plan(
            name, 
            post_retirement_years=post_ret_years
        )
        df_ira = retirement_ira_full_plan(
            name,
            post_retirement_years=post_ret_years
        )

        _display_unified_projection(df_401k, df_ira)
    else:
        ui.print_input_panel("PERSONAL & FINANCIAL DATA")
        
        name = ui.input_string("Enter your name", default="User")
        age = ui.input_int("Current age")
        salary = ui.input_float("Annual salary ($)")
        contrib = ui.input_float("Your contribution (%)", default=15)
        match = ui.input_float("Employer match (%)", default=5)
        raise_pct = ui.input_float("Expected annual salary increase (%)", default=3)
        ret_age = ui.input_int("Retirement age", default=65)
        balance = ui.input_float("Current 401k balance ($)", default=0)

        ui.print_section("FUND PROVIDER SELECTION")
        provider = ui.input_choice(
            "Select fund provider",
            {"1": "Vanguard", "2": "Fidelity"}
        )

        ui.print_divider()
        ui.print_status(f"Calculating projection for {name}...", "info")
        ui.print_divider()
        
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
            post_retirement_years=post_ret_years,
        )
        _display_projection(df)


if __name__ == "__main__":
    main()
