# onehux_sso/views.py
"""Real, runnable Django views wiring OneHuxClient to a real Django session — the BFF
discipline the platform's own dashboard follows on itself: the access token lives only in
Django's server-side session store, never sent to the browser."""

from __future__ import annotations

from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from .client import OneHuxClient
from .conf import get_setting
from .exceptions import InvalidLogoutTokenError, InvalidStateError, TokenExchangeError, TokenExpiredError

_STATE_SESSION_KEY = "onehux_sso_state"
_VERIFIER_SESSION_KEY = "onehux_sso_pkce_verifier"
_SID_CACHE_KEY_PREFIX = "onehux_sso:sid:"


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

        # OIDC Back-Channel Logout (optional): index this Django session by the OneHux Session
        # id (`sid`) carried in the id_token, so a later logout_token POST to
        # BackchannelLogoutView can find and clear exactly this session. request.session.save()
        # is called explicitly here — the default lazy-create-on-write backend otherwise only
        # allocates a real session_key at response time, too late for this cache write.
        sid = client.extract_sid_from_id_token(id_token=tokens.id_token)
        if sid:
            request.session[get_setting("SESSION_SID_KEY")] = sid
            if not request.session.session_key:
                request.session.save()
            cache.set(
                f"{_SID_CACHE_KEY_PREFIX}{sid}",
                request.session.session_key,
                get_setting("BACKCHANNEL_LOGOUT_SID_CACHE_TTL"),
            )

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


@method_decorator(csrf_exempt, name="dispatch")
class BackchannelLogoutView(View):
    """
    POST /auth/backchannel-logout/ — OIDC Back-Channel Logout receiving endpoint (spec:
    openid-connect-backchannel-1_0.html §2.6). Register this exact URL (e.g.
    https://yourapp.example.com/auth/backchannel-logout/) via
    PATCH /api/v1/applications/{id}/backchannel-logout/ on OneHux, and set
    ONEHUX_SSO['BACKCHANNEL_LOGOUT_SIGNING_SECRET'] to the secret returned by that call.

    This is what makes an IdP-initiated logout (a user clicking "log out" directly on
    accounts.onehux.com, or an admin revoking their session) actually terminate THIS app's own
    local Django session in real time, rather than only being discovered the next time this
    app happens to call /userinfo and gets a 401. Without this view mounted and registered,
    IdP-initiated logout is real but silent from this app's point of view — the platform-side
    session is genuinely revoked immediately either way; only the notification is missing.

    csrf_exempt is correct and necessary here: this is a server-to-server POST from OneHux's
    own backend, with no browser session/cookie of its own to carry a CSRF token — the
    logout_token's own HS256 signature (verified below) is this endpoint's real authenticity
    check, not Django's CSRF middleware.

    Per spec: responds 200 on success (Django's own empty-body default becomes a 200, which the
    spec explicitly permits — some frameworks send 204 instead, and OPs are required to accept
    both), 400 on any validation failure, always with Cache-Control: no-store.
    """

    def post(self, request: HttpRequest) -> HttpResponse:
        logout_token = request.POST.get("logout_token", "")
        if not logout_token:
            return self._bad_request("Missing logout_token.")

        try:
            client = OneHuxClient.from_settings()
        except ImproperlyConfigured as exc:
            return self._bad_request(str(exc))

        try:
            payload = client.verify_logout_token(logout_token=logout_token)
        except InvalidLogoutTokenError as exc:
            return self._bad_request(str(exc))

        sid = payload.get("sid")
        if sid:
            session_key = cache.get(f"{_SID_CACHE_KEY_PREFIX}{sid}")
            if session_key:
                # Uses whatever SESSION_ENGINE this project is actually configured with (db,
                # cache, cached_db, ...) — never hardcodes the default db-backed engine, since
                # a foreign session_key must be deleted through the same store it was created
                # in, same pattern django.contrib.sessions' own management commands use.
                from importlib import import_module
                from django.conf import settings as django_settings
                engine = import_module(django_settings.SESSION_ENGINE)
                engine.SessionStore(session_key=session_key).delete()
                cache.delete(f"{_SID_CACHE_KEY_PREFIX}{sid}")
            # A miss here (already logged out locally, or this process never saw the login) is
            # a correct, spec-defined success case (§2.6: "the logout is considered to have
            # succeeded"), not an error — still responds 200 below.

        response = HttpResponse(status=200)
        response["Cache-Control"] = "no-store"
        return response

    def _bad_request(self, detail: str) -> HttpResponse:
        response = JsonResponse({"error": "invalid_request", "error_description": detail}, status=400)
        response["Cache-Control"] = "no-store"
        return response
