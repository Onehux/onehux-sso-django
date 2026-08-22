# Changelog

All notable changes to `onehux-sso` are documented here.

## 0.1.3

- **Added** `onehux_login_required` (function-view decorator) and `OneHuxLoginRequiredMixin`
  (class-based-view mixin) — a reusable redirect-to-login safety net for any protected view an
  integrator writes. Before this release, only `UserInfoView` and the example app caught
  `TokenExpiredError` themselves; every other custom protected view had nothing to lean on
  except hand-rolling that same `try/except` every time, so a missed catch let
  `TokenExpiredError` propagate as an unhandled exception (a real 500) instead of the clean
  redirect the rest of this package already promises. Investigated as part of a real
  propagation audit: `TokenExpiredError` raised from `OneHuxClient.get_userinfo()` was found
  to already be surfaced correctly (not silently swallowed) in every call site this package
  itself ships (`UserInfoView`, the example app) — the gap was the *absence* of a reusable
  protection mechanism for integrator-written views, not a swallowed exception in existing
  code. See README's new "Protecting your own views" section.
- **Documented** the Django session-cookie-lifetime vs. 15-minute-access-token mismatch: this
  package never sets `SESSION_COOKIE_AGE` and relies on the host project's own value (Django's
  default is 2 weeks), which is unrelated to and can vastly outlive the access token's real
  15-minute lifetime. README now states this explicitly and points at
  `onehux_login_required`/`OneHuxLoginRequiredMixin` as the actual safety net — a short cookie
  lifetime alone would not have fixed an app that never checks token validity.

## 0.1.2

- Bump to v0.1.2 — fix `__version__` never matching the published package version.

## 0.1.1

- Bump to v0.1.1 — README-only patch (real published install commands).

## 0.1.0

- Initial release: Authorization Code + PKCE flow against OneHux Accounts' real hosted login
  page, RP-initiated logout, OIDC Back-Channel Logout receiving support, public application
  launcher endpoint.
