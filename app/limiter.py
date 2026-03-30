"""Shared rate-limiter instance for the Retirement Calculator Dashboard.

Import ``limiter`` in ``main.py`` to attach it to the app, and in any
router module where you want to apply ``@limiter.limit(...)`` decorators.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

# Key requests by client IP address.
limiter = Limiter(key_func=get_remote_address)
