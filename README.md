# onehux-sso

A real, installable Django app wrapping OneHux Accounts' Authorization Code + PKCE flow
against its real hosted login page — formalizing what
[the Django integration guide](https://accounts.onehux.com/dashboard/docs/integrate/backend/django)
otherwise only shows as copy-paste example code.

## Install

```bash
pip install -e /path/to/onehux_sso_client/django-package
```

(Not yet published to PyPI — install from source until that's decided.)

## Two hosts — don't mix them up

`accounts.onehux.com` serves the hosted login/logout pages a browser is redirected to.
`api-accounts.onehux.com` serves the actual OAuth API your backend calls server-to-server.
This package keeps them as two separate settings (`LOGIN_BASE_URL` / `API_BASE_URL`) precisely
because collapsing them into one host was a real, confirmed bug in the original integration
guides (see the backend repo's `README.md`, ADR-070) — the wrong host doesn't error loudly, it
silently 404s.

## Setup

1. Register a real confidential-client `Application` in your OneHux Accounts Organization
   (Dashboard → Applications), with a `redirect_uri` pointing at wherever you mount this
   package's `callback/` URL, **and** your `post_logout_redirect_uri` registered in that same
   list — OneHux Accounts validates both against the one `redirect_uris` list, not two
   separate ones.

2. Add to `INSTALLED_APPS`:

   ```python
   INSTALLED_APPS = [
       ...,
       "onehux_sso",
   ]
   ```

3. Add the settings block:

   ```python
   ONEHUX_SSO = {
       "CLIENT_ID": "onehux_client_...",
       "CLIENT_SECRET": "onehux_secret_...",
       "REDIRECT_URI": "https://yourapp.example.com/auth/callback/",
       "POST_LOGOUT_REDIRECT_URI": "https://yourapp.example.com/auth/logged-out/",
       # Everything below is optional — these are the defaults:
       "LOGIN_BASE_URL": "https://accounts.onehux.com",
       "API_BASE_URL": "https://api-accounts.onehux.com",
       "SCOPE": "openid profile email",
       "LOGIN_SUCCESS_REDIRECT": "/",
       "LOGOUT_SUCCESS_REDIRECT": "/",
       "SESSION_ACCESS_TOKEN_KEY": "onehux_access_token",
   }
   ```

4. Wire the URLs:

   ```python
   # yourproject/urls.py
   from django.urls import include, path

   urlpatterns = [
       ...,
       path("auth/", include("onehux_sso.urls")),
   ]
   ```

This gives you four real, working endpoints: `/auth/login/`, `/auth/callback/`,
`/auth/logout/`, and `/auth/userinfo/` (a ready-to-use JSON endpoint your own frontend can call
with `credentials: 'include'`, matching the BFF pattern — your frontend never talks to OneHux
directly).

## Using the client directly

If you'd rather wire your own views instead of using the ones above:

```python
from onehux_sso import OneHuxClient

client = OneHuxClient.from_settings()

pending = client.start_authorization()
# stash pending.state / pending.code_verifier in request.session, then:
# return HttpResponseRedirect(pending.authorization_url)

tokens = client.exchange_code(
    code=request.GET["code"],
    state=request.GET["state"],
    expected_state=request.session["onehux_sso_state"],
    code_verifier=request.session["onehux_sso_pkce_verifier"],
)

claims = client.get_userinfo(access_token=tokens.access_token)

logout_url = client.build_logout_url()
```

## Logging out at the IdP doesn't proactively notify this app — this is real, not a bug

RP-initiated logout (`client.build_logout_url()` / `/auth/logout/`) genuinely, immediately ends
the shared platform-wide session — confirmed by direct trace against the backend. But if the
user instead logs out of a *different* app, or directly at `accounts.onehux.com`, this app has
no way to find out proactively: OneHux Accounts does not implement OIDC Back-Channel Logout.
This app's own local session (`request.session[SESSION_ACCESS_TOKEN_KEY]`) will keep showing
"signed in" until its next real call to `/userinfo` fails with `TokenExpiredError` — bounded by
the access token's 15-minute lifetime, never sooner. Don't treat a locally-held session as a
live signal of the IdP's true logout state; treat it as valid only up to the token's own
lifetime, same discipline as the no-refresh-token note below.

## No refresh token today — this is real, not a bug

OneHux Accounts access tokens are a 15-minute, single-issue lifetime. This platform does not
currently issue a refresh token. `client.get_userinfo()` raises `onehux_sso.TokenExpiredError`
when the token has expired or been revoked — catch it and send the user back through
`client.start_authorization()` for a fresh login. There is no silent-refresh path to fall back
to; this package makes that explicit rather than hiding it behind a generic error.

## Example project

See `example/` for a complete, runnable Django project using this package end-to-end —
registered against a real disposable test `Application` and actually run through the full
browser flow against production, not just unit-tested in isolation.

## License

MIT (see `LICENSE`) — a default choice, not yet a final decision; change before any public
release if OneHux wants different terms.
