# onehux_sso/apps.py
"""AppConfig — nothing to auto-register (no models, no signals); required only so
'onehux_sso' can sit in INSTALLED_APPS and its urls.py/templates (none yet) resolve normally."""

from django.apps import AppConfig


class OneHuxSSOConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "onehux_sso"
    verbose_name = "OneHux Accounts SSO"
