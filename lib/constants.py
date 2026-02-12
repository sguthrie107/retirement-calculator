"""Constants and configuration for retirement calculator."""

from pathlib import Path

# Data directory paths
DATA_DIR = Path(__file__).parent.parent / "data"

# Data file names
STOCKS_FILE = "stocks.json"
BONDS_FILE = "bonds.json"
ASSETS_FILE = "assets.json"
USERS_FILE = "users.json"

# Full file paths
STOCKS_PATH = DATA_DIR / STOCKS_FILE
BONDS_PATH = DATA_DIR / BONDS_FILE
ASSETS_PATH = DATA_DIR / ASSETS_FILE
USERS_PATH = DATA_DIR / USERS_FILE

# For easier reference in functions
DATA_FILES = {
    "STOCKS": STOCKS_FILE,
    "BONDS": BONDS_FILE,
    "ASSETS": ASSETS_FILE,
    "USERS": USERS_FILE,
}

# Alternative dict for full paths
DATA_PATHS = {
    "STOCKS": STOCKS_PATH,
    "BONDS": BONDS_PATH,
    "ASSETS": ASSETS_PATH,
}
