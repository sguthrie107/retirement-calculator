"""Shared utilities for the retirement calculator.

Centralises path resolution and users.json access so every service module
can import from one place instead of each defining its own copy.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any


def project_root() -> Path:
    """Return the project root directory (parent of the lib/ package)."""
    return Path(__file__).resolve().parent.parent


@functools.lru_cache(maxsize=1)
def _load_users_data_cached() -> dict[str, Any]:
    """Load users.json once per process and cache the result.

    The cache is intentionally process-scoped.  Restart the server to pick
    up changes to users.json.
    """
    users_path = project_root() / "data" / "users.json"
    with open(users_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_users_data() -> dict[str, Any]:
    """Return the full cached contents of users.json."""
    return _load_users_data_cached()


def load_user_profile(username: str) -> dict[str, Any]:
    """Load a single user profile from users.json by name.

    Args:
        username: The user's name, e.g. ``'Steven'``.

    Returns:
        User profile dict.

    Raises:
        ValueError: If no user with the given name exists.
    """
    users_data = _load_users_data_cached()
    for user in users_data.get("users", []):
        if user.get("name") == username:
            return user
    raise ValueError(f"User '{username}' not found in users.json")
