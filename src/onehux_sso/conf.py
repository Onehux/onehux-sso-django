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
    # OIDC Back-Channel Logout (optional feature — only BackchannelLogoutView uses these).
    # SESSION_SID_KEY: where the OneHux Session id (the JWT `sid` claim) is stashed in this
    # app's own Django session, so a later logout_token POST can be matched back to it.
    "SESSION_SID_KEY": "onehux_sso_sid",
    # How long the sid -> Django session_key index entry is kept in cache. Purely a lookup
    # aid, not the source of truth for session validity — a stale/missing entry just means a
    # logout_token can't be matched to a live local session (already-logged-out is a spec-
    # defined success case, not an error), never a security exposure.
    "BACKCHANNEL_LOGOUT_SID_CACHE_TTL": 60 * 60 * 24 * 7,
}

_REQUIRED = ("CLIENT_ID", "CLIENT_SECRET", "REDIRECT_URI", "POST_LOGOUT_REDIRECT_URI")
# BACKCHANNEL_LOGOUT_SIGNING_SECRET is deliberately NOT in _REQUIRED — it's an opt-in feature
# (only needed if you mount BackchannelLogoutView and register its URL with OneHux). Missing
# it only raises ImproperlyConfigured when that view is actually hit, not at import time, so
# integrators who don't use back-channel logout are never forced to configure it.


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
    if key == "BACKCHANNEL_LOGOUT_SIGNING_SECRET":
        raise ImproperlyConfigured(
            "ONEHUX_SSO['BACKCHANNEL_LOGOUT_SIGNING_SECRET'] is not set. This is the "
            "dedicated signing secret shown once when you registered your backchannel_logout_uri "
            "via PATCH /api/v1/applications/{id}/backchannel-logout/ — it is NOT your OAuth "
            "CLIENT_SECRET (that value is stored server-side only as a one-way hash and cannot "
            "sign anything). Required to verify an incoming logout_token in BackchannelLogoutView."
        )
    raise KeyError(key)
