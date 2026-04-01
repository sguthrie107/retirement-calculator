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
    "guest":  os.getenv("AUTH_GUEST_PASSWORD", ""),
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
    """Best-effort client IP extraction, proxy-aware."""
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return (request.client.host if request.client else "unknown").strip() or "unknown"


def _prune_old_failures(ip: str, now: float) -> deque[float]:
    """Drop failed-attempt timestamps outside the configured rolling window."""
    attempts = _FAILED_ATTEMPTS_BY_IP.get(ip)
    if attempts is None:
        attempts = deque()
        _FAILED_ATTEMPTS_BY_IP[ip] = attempts

    cutoff = now - _FAILED_WINDOW_SECONDS
    while attempts and attempts[0] < cutoff:
        attempts.popleft()
    return attempts


def _seconds_until_unlock(ip: str, now: float) -> int | None:
    """Return seconds remaining when IP is locked out, otherwise None."""
    with _AUTH_STATE_LOCK:
        locked_until = _LOCKED_UNTIL_BY_IP.get(ip, 0.0)
        if locked_until > now:
            return max(1, math.ceil(locked_until - now))

        if ip in _LOCKED_UNTIL_BY_IP:
            del _LOCKED_UNTIL_BY_IP[ip]
        return None


def _record_failed_attempt(ip: str, now: float) -> int | None:
    """Record auth failure and start lockout if failure threshold is reached."""
    with _AUTH_STATE_LOCK:
        attempts = _prune_old_failures(ip, now)
        attempts.append(now)

        if len(attempts) >= _MAX_FAILED_ATTEMPTS:
            locked_until = now + _LOCKOUT_SECONDS
            _LOCKED_UNTIL_BY_IP[ip] = locked_until
            attempts.clear()
            return _LOCKOUT_SECONDS
        return None


def _clear_failed_attempts(ip: str) -> None:
    """Reset failure and lockout state after a successful auth attempt."""
    with _AUTH_STATE_LOCK:
        _FAILED_ATTEMPTS_BY_IP.pop(ip, None)
        _LOCKED_UNTIL_BY_IP.pop(ip, None)


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
        request.state.is_local = is_local

        # Local dev bypass
        if is_local:
            request.state.authenticated_user = "local_dev"
            return await call_next(request)

        ip = _client_ip(request)
        now = time.time()
        locked_for = _seconds_until_unlock(ip, now)
        if locked_for is not None:
            return Response(
                content="Too many failed login attempts. Try again later.",
                status_code=429,
                headers={"Retry-After": str(locked_for)},
            )

        authorization = request.headers.get("Authorization")
        user = _get_authenticated_user(authorization)
        request.state.authenticated_user = user

        if user is None:
            lockout_seconds = _record_failed_attempt(ip, now)
            headers = {"WWW-Authenticate": f'Basic realm="{_REALM}"'}
            if lockout_seconds is not None:
                headers["Retry-After"] = str(lockout_seconds)
            return Response(
                content="Unauthorized - please log in.",
                status_code=401,
                headers=headers,
            )

        _clear_failed_attempts(ip)

        # Guest is read-only
        if user == "guest" and request.method.upper() in _WRITE_METHODS:
            return Response(
                content="Forbidden - guest access is read-only.",
                status_code=403,
            )

        return await call_next(request)
