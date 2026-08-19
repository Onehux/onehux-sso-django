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

## Public application launcher

`GET /api/v1/organizations/{org_slug}/public-applications/` is a real, public, unauthenticated
platform endpoint — no `client_id`/`client_secret` involved, usable for any Organization by its
own slug, not just your own configured one. It returns only `name`/`logo_url`/`home_url` for
Applications that Organization has opted into public listing — a pure "what can I launch" list,
never a way to start a sign-in flow.

```python
apps = client.get_public_applications(org_slug="onehux")
# [PublicApplication(name="ODS", logo_url="https://...", home_url="https://...")]
```

Rendering is entirely up to you — this package ships the data method only, no template or
component. A plain, unstyled illustration (adapt this to your own design, don't copy it as-is):

```html
{% for app in public_applications %}
  <a href="{{ app.home_url }}">
    <img src="{{ app.logo_url }}" alt="{{ app.name }}">
    {{ app.name }}
  </a>
{% endfor %}
```

## Logging out — what actually happens, and how to hear about it immediately

Two distinct logout paths reach the platform's identical underlying session-revocation call
(`POST /api/v1/sessions/me/logout/`), and OneHux Accounts genuinely, immediately revokes the
platform-wide session either way — this was traced directly against the backend, not assumed.
What differs is how *this app* finds out:

- **RP-initiated logout** — the user clicks "log out" inside this app itself
  (`client.build_logout_url()` / `/auth/logout/`). This app already knows: it's the one that
  cleared `request.session[SESSION_ACCESS_TOKEN_KEY]` and drove the redirect. Nothing further
  to do.
- **IdP-initiated logout** — the user logs out of a *different* app, or directly at
  `accounts.onehux.com/dashboard`. The platform-wide session is revoked immediately and
  correctly, exactly the same as the RP-initiated case — but this app only finds out if it's
  listening for it.

**OneHux Accounts implements real OIDC Back-Channel Logout** (spec:
[openid-connect-backchannel-1_0](https://openid.net/specs/openid-connect-backchannel-1_0.html))
to close that gap: `BackchannelLogoutView` receives a signed `logout_token` POST the instant any
session tied to this app is revoked, anywhere, and clears the matching local Django session
immediately — not on the next stale `/userinfo` call.

**To turn this on:**

1. Mount the package's URLs as shown in Setup above — `BackchannelLogoutView` is already
   included at `/auth/backchannel-logout/` (adjust for whatever prefix you mounted at).
2. Register that exact URL with OneHux:
   ```
   PATCH /api/v1/applications/{id}/backchannel-logout/
   { "backchannel_logout_uri": "https://yourapp.example.com/auth/backchannel-logout/" }
   ```
   The response includes `backchannel_logout_secret` **exactly once** — this is a dedicated
   signing secret, deliberately **not** your `CLIENT_SECRET` (the backend stores that only as a
   one-way hash and can never read it back to sign anything with it).
3. Set `ONEHUX_SSO['BACKCHANNEL_LOGOUT_SIGNING_SECRET']` to that value.

Without steps 1–3, IdP-initiated logout is still real and immediate at the platform level — this
app just won't hear about it until its own next `/userinfo` call fails with `TokenExpiredError`,
bounded by the access token's 15-minute lifetime. With them wired up, both logout paths are
functionally immediate from this app's point of view too.

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

Apache License 2.0 — see `LICENSE`.
