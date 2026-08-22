# tests/django_urls.py
"""Root URLconf for the pytest-django test settings — mounts onehux_sso.urls at /auth/ exactly
as the README's own Setup section instructs, so reverse('onehux_sso:login') resolves for real
in tests/test_decorators.py instead of relying on a mocked reverse()."""

from django.urls import include, path

urlpatterns = [
    path("auth/", include("onehux_sso.urls")),
]
