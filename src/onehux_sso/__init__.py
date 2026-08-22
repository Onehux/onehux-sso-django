# onehux_sso/__init__.py
"""Django SDK for OneHux Accounts SSO — Authorization Code + PKCE against a real,
general hosted login page. Formalizes what dashboard/docs/integrate/backend/django's own
guide otherwise only shows as copy-paste example code."""

from .client import OneHuxClient
from .decorators import OneHuxLoginRequiredMixin, onehux_login_required
from .exceptions import (
    InvalidStateError,
    OneHuxSSOError,
    TokenExchangeError,
    TokenExpiredError,
)

__version__ = "0.1.3"

__all__ = [
    "OneHuxClient",
    "OneHuxSSOError",
    "InvalidStateError",
    "TokenExchangeError",
    "TokenExpiredError",
    "onehux_login_required",
    "OneHuxLoginRequiredMixin",
]
