"""HTTP Basic Auth middleware for the Retirement Calculator Dashboard."""
import base64
import math
import os
import secrets
import threading
import time
from collections import deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_USERS: dict[str, str] = {
    "steven": os.getenv("AUTH_STEVEN_PASSWORD", ""),
    "alyssa": os.getenv("AUTH_ALYSSA_PASSWORD", ""),
    "guest": os.getenv("AUTH_GUEST_PASSWORD", ""),
}

_REALM = "Guthrie Finance - Retirement"
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

_MAX_FAILED_ATTEMPTS = max(1, int(os.getenv("AUTH_MAX_FAILED_ATTEMPTS", "8")))
_FAILED_WINDOW_SECONDS = max(5, int(os.getenv("AUTH_FAILED_WINDOW_SECONDS", "300")))
_LOCKOUT_SECONDS = max(5, int(os.getenv("AUTH_LOCKOUT_SECONDS", "900")))

_FAILED_ATTEMPTS_BY_IP: dict[str, deque[float]] = {}
_LOCKED_UNTIL_BY_IP: dict[str, float] = {}
_AUTH_STATE_LOCK = threading.Lock()


def _client_ip(request: Request) -> str:
    """Return the best available client IP address, preferring proxy headers."""
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return (request.client.host if request.client else "unknown").strip() or "unknown"


def _prune_old_failures(ip_address: str, now: float) -> deque[float]:
    """Drop failed-auth timestamps that fall outside the rolling window."""
    attempts = _FAILED_ATTEMPTS_BY_IP.get(ip_address)
    if attempts is None:
        attempts = deque()
        _FAILED_ATTEMPTS_BY_IP[ip_address] = attempts

    cutoff = now - _FAILED_WINDOW_SECONDS
    while attempts and attempts[0] < cutoff:
        attempts.popleft()

    return attempts


def _seconds_until_unlock(ip_address: str, now: float) -> int | None:
    """Return remaining lockout time in seconds, or ``None`` if unlocked."""
    with _AUTH_STATE_LOCK:
        locked_until = _LOCKED_UNTIL_BY_IP.get(ip_address, 0.0)
        if locked_until > now:
            return max(1, math.ceil(locked_until - now))

        _LOCKED_UNTIL_BY_IP.pop(ip_address, None)
        return None


def _record_failed_attempt(ip_address: str, now: float) -> int | None:
    """Track a failed auth attempt and return lockout seconds when threshold is hit."""
    with _AUTH_STATE_LOCK:
        attempts = _prune_old_failures(ip_address, now)
        attempts.append(now)

        if len(attempts) >= _MAX_FAILED_ATTEMPTS:
            _LOCKED_UNTIL_BY_IP[ip_address] = now + _LOCKOUT_SECONDS
            attempts.clear()
            return _LOCKOUT_SECONDS

        return None


def _clear_failed_attempts(ip_address: str) -> None:
    """Clear tracked auth failures after a successful login."""
    with _AUTH_STATE_LOCK:
        _FAILED_ATTEMPTS_BY_IP.pop(ip_address, None)
        _LOCKED_UNTIL_BY_IP.pop(ip_address, None)


def _get_authenticated_user(authorization: str | None) -> str | None:
    """Return normalized username when Basic credentials are valid, else ``None``."""
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
    """Expose the Basic Auth decoder for route-level checks and tests."""
    return _get_authenticated_user(authorization)


def is_editor(user: str | None) -> bool:
    """Return whether the authenticated user may perform write operations."""
    return user is not None and user.lower() in {"steven", "alyssa", "local_dev"}


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Enforce HTTP Basic Auth and attach the authenticated identity to request state."""

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path == "/health":
            return await call_next(request)

        host = request.url.hostname or ""
        is_local = host in _LOCAL_HOSTS
        request.state.is_local = is_local

        if is_local:
            request.state.authenticated_user = "local_dev"
            return await call_next(request)

        ip_address = _client_ip(request)
        now = time.time()
        retry_after = _seconds_until_unlock(ip_address, now)
        if retry_after is not None:
            return Response(
                content="Too many failed login attempts. Try again later.",
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )

        authorization = request.headers.get("Authorization")
        user = _get_authenticated_user(authorization)
        request.state.authenticated_user = user

        if user is None:
            lockout_seconds = _record_failed_attempt(ip_address, now)
            headers = {"WWW-Authenticate": f'Basic realm=\"{_REALM}\"'}
            if lockout_seconds is not None:
                headers["Retry-After"] = str(lockout_seconds)
            return Response(
                content="Unauthorized - please log in.",
                status_code=401,
                headers=headers,
            )

        _clear_failed_attempts(ip_address)

        if user == "guest" and request.method.upper() in _WRITE_METHODS:
            return Response(
                content="Forbidden - guest access is read-only.",
                status_code=403,
            )

        return await call_next(request)
