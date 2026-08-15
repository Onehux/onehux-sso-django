# onehux_sso/conf.py
"""Settings resolution — every value comes from django.conf.settings.ONEHUX_SSO, a plain dict.
No package-level defaults for CLIENT_ID/CLIENT_SECRET/REDIRECT_URI (those are real per-app
secrets, never guessable); LOGIN_BASE_URL/API_BASE_URL/SCOPE default to this platform's own
production hosts and OpenID's standard scope, since those are the same for every integrator."""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

_DEFAULTS = {
    "LOGIN_BASE_URL": "https://accounts.onehux.com",
    "API_BASE_URL": "https://api-accounts.onehux.com",
    "SCOPE": "openid profile email",
    "LOGIN_SUCCESS_REDIRECT": "/",
    "LOGOUT_SUCCESS_REDIRECT": "/",
    "SESSION_ACCESS_TOKEN_KEY": "onehux_access_token",
}

_REQUIRED = ("CLIENT_ID", "CLIENT_SECRET", "REDIRECT_URI", "POST_LOGOUT_REDIRECT_URI")


def get_setting(key: str):
    """Return ONEHUX_SSO[key], falling back to this module's defaults, raising
    ImproperlyConfigured for a required key with no default and nothing set."""
    config = getattr(settings, "ONEHUX_SSO", None)
    if config is None:
        raise ImproperlyConfigured(
            "ONEHUX_SSO settings dict is missing. Add it to your Django settings module — "
            "see onehux_sso's README for the required keys (CLIENT_ID, CLIENT_SECRET, "
            "REDIRECT_URI, POST_LOGOUT_REDIRECT_URI)."
        )
    if key in config:
        return config[key]
    if key in _DEFAULTS:
        return _DEFAULTS[key]
    if key in _REQUIRED:
        raise ImproperlyConfigured(f"ONEHUX_SSO['{key}'] is required and was not set.")
    raise KeyError(key)
