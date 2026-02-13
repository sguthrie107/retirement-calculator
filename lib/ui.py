"""
Clean, intuitive terminal interface for the Retirement Calculator.
"""

def print_header() -> None:
    """Display the main header."""
    print()
    print("  " + "=" * 56)
    print("  RETIREMENT PROJECTION CALCULATOR")
    print("  " + "=" * 56)
    print()


def print_section(title: str) -> None:
    """Print a section divider."""
    print()
    print(f"  {title}")
    print()


def input_choice(prompt: str, options: dict) -> str:
    """
    Interactive choice prompt.
    
    Args:
        prompt: Display prompt text
        options: Dict of {"key": "label"}
        
    Returns:
        The selected value
    """
    print(f"  {prompt}:")
    print()
    
    for key, label in options.items():
        print(f"    [{key}] {label}")
    
    print()
    
    while True:
        user_input = input("  Choose: ").strip()
        if user_input in options:
            print()
            return options[user_input]
        else:
            print("  Invalid choice. Try again.\n")


def input_float(prompt: str, default: float = None) -> float:
    """Prompt for a float value with optional default."""
    suffix = f" [{default}]" if default is not None else ""
    while True:
        raw = input(f"  {prompt}{suffix}: ").strip()
        if not raw and default is not None:
            return default
        try:
            return float(raw)
        except ValueError:
            print("    Invalid number. Try again.\n")


def input_int(prompt: str, default: int = None) -> int:
    """Prompt for an integer value with optional default."""
    suffix = f" [{default}]" if default is not None else ""
    while True:
        raw = input(f"  {prompt}{suffix}: ").strip()
        if not raw and default is not None:
            return default
        try:
            return int(raw)
        except ValueError:
            print("    Invalid number. Try again.\n")


def input_string(prompt: str, default: str = None) -> str:
    """Prompt for a string value with optional default."""
    suffix = f" [{default}]" if default is not None else ""
    raw = input(f"  {prompt}{suffix}: ").strip()
    if not raw and default is not None:
        return default
    return raw


def print_status(message: str, status: str = "info") -> None:
    """Print a status message."""
    icons = {
        "info": "[*]",
        "success": "[+]",
        "warning": "[!]",
        "error": "[X]"
    }
    icon = icons.get(status, "[*]")
    print(f"  {icon} {message}")


def print_divider() -> None:
    """Print a visual divider."""
    print()


def print_input_panel(title: str) -> None:
    """Print an input panel header."""
    print(f"  {title}")
    print()


def print_data_panel(title: str, content: str) -> None:
    """Print a data display panel."""
    print()
    print(f"  {title}")
    print()
    for line in content.split('\n'):
        if line.strip():
            print(f"  {line}")


def format_currency(value: float) -> str:
    """Format a value as currency."""
    return f"${value:,.2f}"


def print_success(message: str) -> None:
    """Print a success message."""
    print(f"  [+] {message}")


def print_error(message: str) -> None:
    """Print an error message."""
    print(f"  [X] {message}")
