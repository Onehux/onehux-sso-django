# tests/django_settings.py
"""Minimal Django settings module used only by pytest-django to run the view/decorator tests
in tests/test_decorators.py — real django.contrib.sessions middleware/session store, real
onehux_sso URLs included at /auth/, real ONEHUX_SSO config block. No database is used by any
test (SESSION_ENGINE defaults to db-backed, but session objects are built in-memory via
SessionMiddleware in each test rather than round-tripped through a real DB)."""

SECRET_KEY = "test-secret-key-not-for-production"

INSTALLED_APPS = [
    "django.contrib.sessions",
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "onehux_sso",
]

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# signed_cookies needs no database at all — every test session here is built directly via
# SessionMiddleware.process_request() in-process, never round-tripped through a real store.
SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"

ROOT_URLCONF = "tests.django_urls"

ONEHUX_SSO = {
    "CLIENT_ID": "test-client-id",
    "CLIENT_SECRET": "test-client-secret",
    "REDIRECT_URI": "https://app.example.com/auth/callback/",
    "POST_LOGOUT_REDIRECT_URI": "https://app.example.com/auth/logged-out/",
    "LOGIN_BASE_URL": "https://accounts.example.com",
    "API_BASE_URL": "https://api.example.com",
}

USE_TZ = True
