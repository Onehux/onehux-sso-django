# onehux_sso/decorators.py
"""Reusable "protect this view" helpers — a function decorator (onehux_login_required) and a
class-based-view mixin (OneHuxLoginRequiredMixin), both doing the exact same thing.

Why this file exists: before it, this package shipped zero reusable protection for an
integrator's OWN views. UserInfoView and the example app both call
OneHuxClient.get_userinfo() and catch TokenExpiredError themselves, correctly, but every other
protected view an integrator writes had nothing to lean on except hand-rolling that same
try/except every single time — miss it once and TokenExpiredError propagates out of the view
as an unhandled exception (a 500 in production, not the clean "go sign in again" redirect the
README already promises everywhere else). That's the real gap this closes: TokenExpiredError
raised anywhere inside a wrapped view is caught here and turned into a redirect back to
onehux_sso:login — never left to bubble up as a 500, and never silently swallowed (the
session's stale access token is popped before redirecting, so a retried request doesn't loop
on the same dead token).

Mirrors django.contrib.auth.decorators.login_required's own shape deliberately (decorator +
functools.wraps, REDIRECT_FIELD_NAME query param) since that's the pattern any Django
integrator already knows — no new convention invented here."""

from __future__ import annotations

from functools import wraps

from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.urls import reverse
from django.utils.http import urlencode

from .conf import get_setting
from .exceptions import TokenExpiredError

REDIRECT_FIELD_NAME = "next"


def _redirect_to_login(request: HttpRequest) -> HttpResponseRedirect:
    """Build the redirect used by both the decorator and the mixin below: onehux_sso's own
    /auth/login/ (via reverse(), so it resolves correctly whatever prefix this project mounted
    onehux_sso.urls at), carrying ?next=<the page the user was trying to reach> the same way
    django.contrib.auth.views.redirect_to_login does."""
    login_url = reverse("onehux_sso:login")
    next_url = request.get_full_path()
    return HttpResponseRedirect(f"{login_url}?{urlencode({REDIRECT_FIELD_NAME: next_url})}")


def onehux_login_required(view_func):
    """Function-view decorator: redirects to onehux_sso:login if there's no access token in the
    session yet, AND catches TokenExpiredError raised anywhere during the wrapped view's
    execution (typically from a client.get_userinfo() call inside it) and redirects the same
    way — clearing the now-dead access token from the session first so a subsequent request
    doesn't immediately hit the same expired token again.

    Usage:
        @onehux_login_required
        def my_view(request):
            client = OneHuxClient.from_settings()
            access_token = request.session[get_setting("SESSION_ACCESS_TOKEN_KEY")]
            claims = client.get_userinfo(access_token=access_token)  # TokenExpiredError -> redirect
            ...
    """

    @wraps(view_func)
    def _wrapped(request: HttpRequest, *args, **kwargs) -> HttpResponse:
        access_token = request.session.get(get_setting("SESSION_ACCESS_TOKEN_KEY"))
        if not access_token:
            return _redirect_to_login(request)
        try:
            return view_func(request, *args, **kwargs)
        except TokenExpiredError:
            request.session.pop(get_setting("SESSION_ACCESS_TOKEN_KEY"), None)
            return _redirect_to_login(request)

    return _wrapped


class OneHuxLoginRequiredMixin:
    """Class-based-view equivalent of onehux_login_required — wraps dispatch() with the exact
    same session-presence check and TokenExpiredError-to-redirect handling. Put it first in the
    MRO, before View:

        class DashboardView(OneHuxLoginRequiredMixin, View):
            def get(self, request):
                client = OneHuxClient.from_settings()
                access_token = request.session[get_setting("SESSION_ACCESS_TOKEN_KEY")]
                claims = client.get_userinfo(access_token=access_token)
                ...
    """

    def dispatch(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        access_token = request.session.get(get_setting("SESSION_ACCESS_TOKEN_KEY"))
        if not access_token:
            return _redirect_to_login(request)
        try:
            return super().dispatch(request, *args, **kwargs)
        except TokenExpiredError:
            request.session.pop(get_setting("SESSION_ACCESS_TOKEN_KEY"), None)
            return _redirect_to_login(request)
