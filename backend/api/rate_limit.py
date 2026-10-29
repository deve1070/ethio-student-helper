"""Shared slowapi rate limiter, keyed by client IP. One instance for the whole app (main.py registers
it on app.state and adds its middleware/exception handler); a route opts into a tighter limit than the
default with `@limiter.limit("N/period")` - the decorated route function needs a `request: Request`
parameter, which is how slowapi reads the client IP."""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])
