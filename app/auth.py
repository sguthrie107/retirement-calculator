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

_REALM = "Guthrie Finance - Retirement"
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _get_authenticated_user(authorization: str | None) -> str | None:
    """Return normalized username when Basic credentials are valid, else None."""
    if not authorization or not authorization.startswith("Basic "):
        return None
    try:
        decoded = base64.b64decode(authorization[6:]).decode("utf-8")
        username, _, password = decoded.partition(":")
        normalized_username = username.lower()
        expected = _USERS.get(normalized_username, None)
        # expected being empty-string means the env var wasn't set — deny access
        if not expected:
            return None
        if secrets.compare_digest(password, expected):
            return normalized_username
        return None
    except Exception:
        return None


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that enforces HTTP Basic Auth on every request."""

    async def dispatch(self, request: Request, call_next) -> Response:
        # Allow health-check pings through without auth (useful for Railway)
        if request.url.path == "/health":
            return await call_next(request)

        # Local development convenience: skip auth for localhost access.
        if request.url.hostname in _LOCAL_HOSTS:
            return await call_next(request)

        authenticated_user = _get_authenticated_user(request.headers.get("authorization"))
        if not authenticated_user:
            return Response(
                content="Unauthorized - please log in.",
                status_code=401,
                headers={"WWW-Authenticate": f'Basic realm="{_REALM}"'},
            )

        if authenticated_user == "guest" and request.method.upper() in _WRITE_METHODS:
            return Response(
                content="Forbidden - guest access is read-only.",
                status_code=403,
            )
        return await call_next(request)
