# onehux_sso/views.py
"""Real, runnable Django views wiring OneHuxClient to a real Django session — the BFF
discipline the platform's own dashboard follows on itself: the access token lives only in
Django's server-side session store, never sent to the browser."""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse
from django.views import View

from .client import OneHuxClient
from .conf import get_setting
from .exceptions import InvalidStateError, TokenExchangeError, TokenExpiredError

_STATE_SESSION_KEY = "onehux_sso_state"
_VERIFIER_SESSION_KEY = "onehux_sso_pkce_verifier"


class LoginView(View):
    """GET /auth/login/ — starts the flow: generates PKCE + state, stashes them in the
    session, redirects to the real hosted login page."""

    def get(self, request: HttpRequest) -> HttpResponse:
        client = OneHuxClient.from_settings()
        pending = client.start_authorization()
        request.session[_STATE_SESSION_KEY] = pending.state
        request.session[_VERIFIER_SESSION_KEY] = pending.code_verifier
        return HttpResponseRedirect(pending.authorization_url)


class CallbackView(View):
    """GET /auth/callback/ — verifies state, exchanges the code, stores the access token in
    the session, redirects to ONEHUX_SSO['LOGIN_SUCCESS_REDIRECT'] (default '/')."""

    def get(self, request: HttpRequest) -> HttpResponse:
        code = request.GET.get("code", "")
        state = request.GET.get("state", "")
        error = request.GET.get("error")
        if error:
            return HttpResponse(
                f"Sign-in failed: {error} — {request.GET.get('error_description', '')}",
                status=400,
            )

        expected_state = request.session.pop(_STATE_SESSION_KEY, None)
        code_verifier = request.session.pop(_VERIFIER_SESSION_KEY, None)

        client = OneHuxClient.from_settings()
        try:
            tokens = client.exchange_code(
                code=code, state=state, expected_state=expected_state, code_verifier=code_verifier
            )
        except InvalidStateError as exc:
            return HttpResponse(str(exc), status=400)
        except TokenExchangeError as exc:
            return HttpResponse(f"{exc.error}: {exc.error_description}", status=400)

        request.session[get_setting("SESSION_ACCESS_TOKEN_KEY")] = tokens.access_token
        return HttpResponseRedirect(get_setting("LOGIN_SUCCESS_REDIRECT"))


class LogoutView(View):
    """GET /auth/logout/ — clears the local session access token, then redirects through the
    real RP-initiated /end-session flow, ending the platform-wide session, not just this app's
    own local one."""

    def get(self, request: HttpRequest) -> HttpResponse:
        request.session.pop(get_setting("SESSION_ACCESS_TOKEN_KEY"), None)
        client = OneHuxClient.from_settings()
        return HttpResponseRedirect(client.build_logout_url())


class UserInfoView(View):
    """GET /auth/userinfo/ — a ready-to-use JSON endpoint for your own frontend to call
    (credentials: 'include'), matching the BFF pattern documented for the web-frontend
    integration guide: your frontend calls your own backend, never OneHux directly. Returns
    401 with the real TokenExpiredError message when the session's token is expired/invalid,
    so the caller knows to redirect through /auth/login/ again rather than retry."""

    def get(self, request: HttpRequest) -> HttpResponse:
        access_token = request.session.get(get_setting("SESSION_ACCESS_TOKEN_KEY"))
        if not access_token:
            return JsonResponse({"detail": "Not signed in."}, status=401)

        client = OneHuxClient.from_settings()
        try:
            claims = client.get_userinfo(access_token=access_token)
        except TokenExpiredError as exc:
            return JsonResponse({"detail": str(exc)}, status=401)
        return JsonResponse(claims)
