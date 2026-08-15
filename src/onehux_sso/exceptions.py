# onehux_sso/exceptions.py
"""Exceptions raised by the OneHux SSO client. Real backend error shapes (error/
error_description) are preserved, not swallowed into a generic message — a caller that wants
the raw OAuth error code can read exc.error directly."""


class OneHuxSSOError(Exception):
    """Base class for every error this package raises."""


class InvalidStateError(OneHuxSSOError):
    """The callback's state parameter didn't match what was stashed at redirect time, or
    code/state was missing outright — a real CSRF-protection failure, or a stale/replayed
    callback URL."""


class TokenExchangeError(OneHuxSSOError):
    """POST /api/v1/oauth/token/ returned a non-2xx response. Carries the real OAuth
    error/error_description from oauth.views._error_response() rather than a generic message,
    so a caller can distinguish e.g. invalid_grant (expired code) from invalid_client
    (misconfigured client_id/secret)."""

    def __init__(self, *, error: str, error_description: str, status_code: int):
        self.error = error
        self.error_description = error_description
        self.status_code = status_code
        super().__init__(f"{error}: {error_description}")


class TokenExpiredError(OneHuxSSOError):
    """GET /api/v1/oauth/userinfo/ rejected the access token.

    OneHux Accounts does not currently issue a refresh token (access tokens are 15-minute
    lifetime, single-use per login) — this is a real, permanent platform constraint as of this
    package's build, not a bug in this client. Callers must catch this and route the user back
    through OneHuxClient.build_authorization_redirect_url() for a fresh login; there is no
    silent-refresh path to fall back to."""
