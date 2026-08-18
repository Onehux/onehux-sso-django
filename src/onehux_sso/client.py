# onehux_sso/client.py
"""OneHuxClient — PKCE generation, the hosted-login redirect, the authorization_code token
exchange, /userinfo, and the RP-initiated /end-session redirect. Deliberately Django-session-
agnostic at this layer (takes/returns plain dicts and strings) so it's testable without a
request object; onehux_sso.views wires it to a real Django session.

Two distinct hosts, by design (README.md ADR-070 in the backend repo, found by a real
end-to-end manual walkthrough against production): the hosted login/logout pages live on
LOGIN_BASE_URL, the actual OAuth API lives on the separate API_BASE_URL. Mixing them up
previously produced a silent 404 HTML body instead of a JSON error — this client never lets
that ambiguity exist, since the two are separate constructor arguments, not one shared value.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import jwt
import requests

from .conf import get_setting
from .exceptions import (
    InvalidLogoutTokenError,
    InvalidStateError,
    StepUpRequiredError,
    TokenExchangeError,
    TokenExpiredError,
)

LOGOUT_EVENT_CLAIM_KEY = "http://schemas.openid.net/event/backchannel-logout"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


@dataclass(frozen=True)
class PendingAuthorization:
    """The PKCE verifier + state a caller must persist (Django session) between the redirect
    and the callback — never round-tripped through the client's own browser-visible state."""

    code_verifier: str
    state: str
    authorization_url: str


@dataclass(frozen=True)
class TokenResult:
    """Mirrors oauth.views.TokenView's real response shape exactly (access_token, id_token,
    token_type, expires_in, scope) — no fields invented, none dropped."""

    access_token: str
    id_token: str
    token_type: str
    expires_in: int
    scope: str


class OneHuxClient:
    """A confidential OAuth 2.0 + PKCE client for OneHux Accounts.

    Construct directly, or via `OneHuxClient.from_settings()` to read every value from
    Django's `settings.ONEHUX_SSO` (see onehux_sso.conf and the package README).
    """

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        post_logout_redirect_uri: str,
        login_base_url: str = "https://accounts.onehux.com",
        api_base_url: str = "https://api-accounts.onehux.com",
        scope: str = "openid profile email",
        timeout: float = 10.0,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.post_logout_redirect_uri = post_logout_redirect_uri
        self.login_base_url = login_base_url.rstrip("/")
        self.api_base_url = api_base_url.rstrip("/")
        self.scope = scope
        self.timeout = timeout

    @classmethod
    def from_settings(cls) -> "OneHuxClient":
        """Build a client from Django's settings.ONEHUX_SSO dict (see onehux_sso.conf for the
        exact keys and defaults)."""
        return cls(
            client_id=get_setting("CLIENT_ID"),
            client_secret=get_setting("CLIENT_SECRET"),
            redirect_uri=get_setting("REDIRECT_URI"),
            post_logout_redirect_uri=get_setting("POST_LOGOUT_REDIRECT_URI"),
            login_base_url=get_setting("LOGIN_BASE_URL"),
            api_base_url=get_setting("API_BASE_URL"),
            scope=get_setting("SCOPE"),
        )

    def start_authorization(self) -> PendingAuthorization:
        """Generate a fresh PKCE pair + state and build the hosted-login redirect URL. The
        caller is responsible for persisting code_verifier/state server-side (Django session)
        until the callback — never in a cookie the browser itself can read."""
        code_verifier = _b64url(secrets.token_bytes(48))
        code_challenge = _b64url(hashlib.sha256(code_verifier.encode()).digest())
        state = _b64url(secrets.token_bytes(16))

        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "scope": self.scope,
            "state": state,
        }
        authorization_url = f"{self.login_base_url}/login?{urlencode(params)}"
        return PendingAuthorization(
            code_verifier=code_verifier, state=state, authorization_url=authorization_url
        )

    def exchange_code(
        self, *, code: str, state: str, expected_state: str, code_verifier: str
    ) -> TokenResult:
        """Verify state, then exchange `code` for real tokens via
        POST {API_BASE_URL}/api/v1/oauth/token/. Raises InvalidStateError on a state
        mismatch/missing code (never attempts the exchange in that case — a mismatched state
        is a real CSRF-protection failure, not something to silently proceed past), and
        TokenExchangeError carrying the real OAuth error/error_description on a non-2xx
        response."""
        if not code or not state or state != expected_state:
            raise InvalidStateError(
                "Callback state did not match the pending authorization, or code/state was "
                "missing — this callback is either stale, replayed, or forged."
            )

        response = requests.post(
            f"{self.api_base_url}/api/v1/oauth/token/",
            json={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code_verifier": code_verifier,
            },
            timeout=self.timeout,
        )
        body = response.json()
        if not response.ok:
            if body.get("error") == "step_up_required":
                # Deliberately distinct from TokenExchangeError: this is a recoverable, expected
                # mid-login prompt (device/location trust gate), not a failed exchange — the
                # caller (CallbackView) redirects the browser to complete step-up rather than
                # showing an error.
                raise StepUpRequiredError(error_description=body.get("error_description", ""))
            raise TokenExchangeError(
                error=body.get("error", "unknown_error"),
                error_description=body.get("error_description", ""),
                status_code=response.status_code,
            )
        return TokenResult(
            access_token=body["access_token"],
            id_token=body["id_token"],
            token_type=body["token_type"],
            expires_in=body["expires_in"],
            scope=body["scope"],
        )

    def build_step_up_redirect_url(self, *, code_verifier: str, state: str) -> str:
        """Build the redirect used when exchange_code() raises StepUpRequiredError (README.md
        ADR-076, backend repo). Reuses this SAME pending authorization's client_id/redirect_uri/
        scope/state, and re-derives code_challenge from the already-stored code_verifier (PKCE
        code_challenge is a pure function of code_verifier, so nothing extra needs to be
        persisted). Deep-links straight to the real hosted email-OTP step-up page — the exact
        same URL the platform's own first-party dashboard redirects to for this identical error
        (backend repo: frontend/src/lib/server/step-up.ts) — rather than the generic /login
        page, since the platform requires a step-up-caliber method specifically here. The
        caller MUST NOT discard the pending code_verifier/state before calling this: the
        browser will land back on this same app's callback shortly with a brand-new code for
        this same state, and CallbackView needs the still-stored code_verifier to exchange it."""
        code_challenge = _b64url(hashlib.sha256(code_verifier.encode()).digest())
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "scope": self.scope,
            "state": state,
            "reason": "step_up",
        }
        return f"{self.login_base_url}/login/email-otp?{urlencode(params)}"

    def get_userinfo(self, *, access_token: str) -> dict:
        """GET {API_BASE_URL}/api/v1/oauth/userinfo/ — real claims (sub, name, email, picture,
        roles, permissions, ...), recomputed live by the backend on every call, never cached
        here. Raises TokenExpiredError on any non-2xx response: OneHux Accounts access tokens
        are a 15-minute, single-issue lifetime with no refresh token today, so an expired/
        invalid token here means "send the user through start_authorization() again," not
        "retry" — this package makes that permanent platform constraint explicit rather than
        hiding it behind a generic error."""
        response = requests.get(
            f"{self.api_base_url}/api/v1/oauth/userinfo/",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=self.timeout,
        )
        if not response.ok:
            raise TokenExpiredError(
                "The access token was rejected by /userinfo — it has either expired (15-minute "
                "lifetime, no refresh token issued by this platform today) or was revoked. "
                "Send the user back through OneHuxClient.start_authorization()."
            )
        return response.json()

    def extract_sid_from_id_token(self, *, id_token: str) -> str | None:
        """
        Pull the `sid` claim out of `id_token` WITHOUT verifying its signature — this package
        has no way to verify an id_token's signature (OneHux Accounts signs it with a server-
        only key never shared with any client — the backend repo's own oauth.services
        .build_jwt() docstring flags this as a deliberate Phase-1 gap), and doesn't need to for
        this purpose: the token was retrieved directly from a client_secret-authenticated POST
        to /api/v1/oauth/token/ over TLS, not from an untrusted redirect parameter, so trusting
        its contents here (indexing this local session for a later logout_token match) is
        standard OIDC RP practice. Returns None if the token doesn't decode or has no sid claim
        — a missing index entry only means a future logout_token can't be matched to this
        session, never a security exposure (see BackchannelLogoutView's own docstring).
        """
        try:
            payload = jwt.decode(id_token, options={"verify_signature": False})
        except jwt.PyJWTError:
            return None
        return payload.get("sid")

    def verify_logout_token(self, *, logout_token: str) -> dict:
        """
        Real OIDC Back-Channel Logout validation (spec §2.6), HS256-verified against
        ONEHUX_SSO['BACKCHANNEL_LOGOUT_SIGNING_SECRET'] — the dedicated secret shown once at
        backchannel_logout_uri registration time, deliberately NOT this client's own
        CLIENT_SECRET (the backend cannot read that back to sign anything with it — see the
        backend repo's README.md ADR-074). Raises InvalidLogoutTokenError on any validation
        failure — signature, aud, missing/malformed events claim, a present nonce claim
        (forbidden per spec), or a missing sub/sid — the caller (BackchannelLogoutView) turns
        that into the spec-required HTTP 400.
        """
        secret = get_setting("BACKCHANNEL_LOGOUT_SIGNING_SECRET")
        try:
            payload = jwt.decode(
                logout_token, secret, algorithms=["HS256"], audience=self.client_id,
            )
        except jwt.PyJWTError as exc:
            raise InvalidLogoutTokenError(f"logout_token signature/claims invalid: {exc}")

        if "nonce" in payload:
            raise InvalidLogoutTokenError("logout_token MUST NOT contain a nonce claim.")
        events = payload.get("events")
        if not isinstance(events, dict) or LOGOUT_EVENT_CLAIM_KEY not in events:
            raise InvalidLogoutTokenError(
                f"logout_token is missing the required events claim ({LOGOUT_EVENT_CLAIM_KEY})."
            )
        if not payload.get("sub") and not payload.get("sid"):
            raise InvalidLogoutTokenError("logout_token must contain a sub claim, a sid claim, or both.")
        return payload

    def build_logout_url(self, *, state: str | None = None) -> str:
        """Build the RP-initiated logout redirect (README.md ADR-070, backend repo):
        post_logout_redirect_uri must already be registered in this Application's own
        redirect_uris list — the same list the login callback uses, not a separate one — or
        the platform rejects this with a real 400."""
        params = {
            "client_id": self.client_id,
            "post_logout_redirect_uri": self.post_logout_redirect_uri,
        }
        if state:
            params["state"] = state
        return f"{self.login_base_url}/end-session?{urlencode(params)}"
