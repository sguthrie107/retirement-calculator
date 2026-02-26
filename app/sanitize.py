"""Input sanitization utilities.

All user-supplied free-text strings pass through these helpers before
being stored.  SQLAlchemy already uses parameterized queries (no raw SQL),
so the focus here is preventing XSS payloads from being persisted and
clamping string lengths to sane limits.
"""
import re
import html

# Length caps for free-text fields
MAX_NOTES_LENGTH = 500
MAX_NAME_LENGTH = 50

# Pattern that allows only alphanumeric, spaces, hyphens, apostrophes
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9 '\-]+$")


def sanitize_notes(text: str | None, max_length: int = MAX_NOTES_LENGTH) -> str | None:
    """Escape HTML entities and truncate notes to a safe length."""
    if text is None:
        return None
    cleaned = html.escape(text.strip(), quote=True)
    return cleaned[:max_length] if cleaned else None


def sanitize_name(text: str, max_length: int = MAX_NAME_LENGTH) -> str:
    """Validate and clean a name (username, child name, etc).

    Raises ValueError if the name contains disallowed characters.
    """
    stripped = text.strip()
    if not stripped:
        raise ValueError("Name must not be empty")
    if len(stripped) > max_length:
        raise ValueError(f"Name must be {max_length} characters or fewer")
    if not _SAFE_NAME_RE.match(stripped):
        raise ValueError("Name contains invalid characters")
    return stripped
