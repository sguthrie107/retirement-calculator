"""HTTP Basic Auth middleware for the Retirement Calculator Dashboard."""
import base64
import os
import secrets
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# ---------------------------------------------------------------------------
# User credentials — loaded from environment variables.
# Set these in Railway's environment variable panel (or in a local .env file).
# ---------------------------------------------------------------------------
_USERS: dict[str, str] = {
    "steven": os.getenv("AUTH_STEVEN_PASSWORD", ""),
    "alyssa": os.getenv("AUTH_ALYSSA_PASSWORD", ""),
    "guest":  os.getenv("AUTH_GUEST_PASSWORD",  ""),
}

_REALM = "Guthrie Finance — Retirement"


def _check_credentials(authorization: str | None) -> bool:
    """Return True if the Authorization header contains valid Basic credentials."""
    if not authorization or not authorization.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(authorization[6:]).decode("utf-8")
        username, _, password = decoded.partition(":")
        expected = _USERS.get(username.lower(), None)
        # expected being empty-string means the env var wasn't set — deny access
        if not expected:
            return False
        return secrets.compare_digest(password, expected)
    except Exception:
        return False


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that enforces HTTP Basic Auth on every request."""

    async def dispatch(self, request: Request, call_next) -> Response:
        # Allow health-check pings through without auth (useful for Railway)
        if request.url.path == "/health":
            return await call_next(request)

        if not _check_credentials(request.headers.get("authorization")):
            return Response(
                content="Unauthorized — please log in.",
                status_code=401,
                headers={"WWW-Authenticate": f'Basic realm="{_REALM}"'},
            )
        return await call_next(request)
