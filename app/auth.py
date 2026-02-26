"""HTTP Basic Auth middleware for the Retirement Calculator Dashboard."""
import base64
import os
import secrets
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_USERS: dict[str, str] = {
    "steven": os.getenv("AUTH_STEVEN_PASSWORD", ""),
    "alyssa": os.getenv("AUTH_ALYSSA_PASSWORD", ""),
    "guest":  os.getenv("AUTH_GUEST_PASSWORD", ""),
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
        normalized = username.lower()
        expected = _USERS.get(normalized)
        if not expected:
            return None
        if secrets.compare_digest(password, expected):
            return normalized
        return None
    except Exception:
        return None


def get_authenticated_user(authorization: str | None) -> str | None:
    """Public accessor for route-level auth checks."""
    return _get_authenticated_user(authorization)


def is_editor(user: str | None) -> bool:
    """Only Steven and Alyssa (or local dev) may write data."""
    return user is not None and user.lower() in {"steven", "alyssa", "local_dev"}


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Enforce HTTP Basic Auth; attach identity to request.state."""

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path == "/health":
            return await call_next(request)

        host = request.url.hostname or ""
        is_local = host in _LOCAL_HOSTS

        authorization = request.headers.get("Authorization")
        user = _get_authenticated_user(authorization)
        request.state.authenticated_user = user
        request.state.is_local = is_local

        # Local dev bypass
        if is_local:
            request.state.authenticated_user = "local_dev"
            return await call_next(request)

        if user is None:
            return Response(
                content="Unauthorized - please log in.",
                status_code=401,
                headers={"WWW-Authenticate": f'Basic realm="{_REALM}"'},
            )

        # Guest is read-only
        if user == "guest" and request.method.upper() in _WRITE_METHODS:
            return Response(
                content="Forbidden - guest access is read-only.",
                status_code=403,
            )

        return await call_next(request)
