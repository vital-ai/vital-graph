"""
Request context for audit logging.

Uses contextvars to capture IP and user-agent from the incoming request
so audit events can include client information without threading Request
objects through the entire call stack.
"""

from contextvars import ContextVar
from typing import Optional

_request_ip: ContextVar[Optional[str]] = ContextVar("request_ip", default=None)
_request_ua: ContextVar[Optional[str]] = ContextVar("request_ua", default=None)


def set_request_context(ip: Optional[str], user_agent: Optional[str]) -> None:
    _request_ip.set(ip)
    _request_ua.set(user_agent)


def get_request_ip() -> Optional[str]:
    return _request_ip.get()


def get_request_ua() -> Optional[str]:
    return _request_ua.get()
