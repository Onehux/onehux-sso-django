# tests/test_decorators.py
"""Real tests for onehux_login_required / OneHuxLoginRequiredMixin — the redirect-on-
TokenExpiredError safety net (see src/onehux_sso/decorators.py's module docstring for why this
exists: no reusable protection existed before it).

Covers exactly the scenario the production bug report was worried about: does
TokenExpiredError, raised deep inside a protected view, actually reach the user as a clean
redirect to /auth/login/ — or does it get lost somewhere (a 500, or a silent pass-through)?
Verified here with a real Django SessionMiddleware-built session and a real
reverse('onehux_sso:login') resolution — nothing mocked except the view body itself, which
deliberately raises TokenExpiredError to simulate an expired-token /userinfo call."""

from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse
from django.test import RequestFactory
from django.views import View

from onehux_sso.conf import get_setting
from onehux_sso.decorators import OneHuxLoginRequiredMixin, onehux_login_required
from onehux_sso.exceptions import TokenExpiredError

SESSION_KEY = None  # resolved lazily below since get_setting() needs Django settings configured


def _session_key():
    global SESSION_KEY
    if SESSION_KEY is None:
        SESSION_KEY = get_setting("SESSION_ACCESS_TOKEN_KEY")
    return SESSION_KEY


def _request(path="/dashboard/", access_token=None):
    """Build a real request with a real, saved session — SessionMiddleware.process_request
    attaches request.session; we then write directly to it the way CallbackView does."""
    factory = RequestFactory()
    request = factory.get(path)
    SessionMiddleware(lambda r: HttpResponse()).process_request(request)
    if access_token is not None:
        request.session[_session_key()] = access_token
        request.session.save()
    return request


# --- Function-view decorator ---

@onehux_login_required
def _protected_view(request):
    """A stand-in protected view: fetches the token from the session and calls something that
    behaves exactly like OneHuxClient.get_userinfo() would on an expired/invalid token —
    raising TokenExpiredError. Real integrator code looks exactly like this."""
    access_token = request.session[get_setting("SESSION_ACCESS_TOKEN_KEY")]
    if access_token == "expired-token":
        raise TokenExpiredError("The access token was rejected by /userinfo.")
    return HttpResponse(f"ok:{access_token}")


class TestOnehuxLoginRequiredDecorator:
    def test_no_access_token_redirects_to_login(self):
        request = _request(access_token=None)
        response = _protected_view(request)
        assert response.status_code == 302
        assert response.url.startswith("/auth/login/")
        assert "next=%2Fdashboard%2F" in response.url

    def test_valid_token_calls_through_to_view(self):
        request = _request(access_token="valid-token")
        response = _protected_view(request)
        assert response.status_code == 200
        assert response.content == b"ok:valid-token"

    def test_token_expired_error_redirects_not_500(self):
        """The core regression test: TokenExpiredError raised inside the view must never
        propagate as an unhandled exception — it must become a clean redirect to login."""
        request = _request(access_token="expired-token")
        response = _protected_view(request)
        assert response.status_code == 302
        assert response.url.startswith("/auth/login/")

    def test_token_expired_error_clears_the_dead_token_from_session(self):
        request = _request(access_token="expired-token")
        _protected_view(request)
        assert get_setting("SESSION_ACCESS_TOKEN_KEY") not in request.session


# --- Class-based-view mixin ---

class _ProtectedCBV(OneHuxLoginRequiredMixin, View):
    def get(self, request):
        access_token = request.session[get_setting("SESSION_ACCESS_TOKEN_KEY")]
        if access_token == "expired-token":
            raise TokenExpiredError("The access token was rejected by /userinfo.")
        return HttpResponse(f"ok:{access_token}")


class TestOneHuxLoginRequiredMixin:
    def test_no_access_token_redirects_to_login(self):
        request = _request(access_token=None)
        response = _ProtectedCBV.as_view()(request)
        assert response.status_code == 302
        assert response.url.startswith("/auth/login/")

    def test_valid_token_calls_through_to_view(self):
        request = _request(access_token="valid-token")
        response = _ProtectedCBV.as_view()(request)
        assert response.status_code == 200
        assert response.content == b"ok:valid-token"

    def test_token_expired_error_redirects_not_500(self):
        request = _request(access_token="expired-token")
        response = _ProtectedCBV.as_view()(request)
        assert response.status_code == 302
        assert response.url.startswith("/auth/login/")

    def test_token_expired_error_clears_the_dead_token_from_session(self):
        request = _request(access_token="expired-token")
        _ProtectedCBV.as_view()(request)
        assert get_setting("SESSION_ACCESS_TOKEN_KEY") not in request.session
