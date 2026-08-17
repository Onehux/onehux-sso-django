# onehux_sso/urls.py
"""Include as e.g. path('auth/', include('onehux_sso.urls')) in your project's urls.py — the
REDIRECT_URI / POST_LOGOUT_REDIRECT_URI you register with OneHux Accounts must match wherever
you mount this (e.g. https://yourapp.example.com/auth/callback/)."""

from django.urls import path

from .views import BackchannelLogoutView, CallbackView, LoginView, LogoutView, UserInfoView

app_name = "onehux_sso"

urlpatterns = [
    path("login/", LoginView.as_view(), name="login"),
    path("callback/", CallbackView.as_view(), name="callback"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("userinfo/", UserInfoView.as_view(), name="userinfo"),
    path("backchannel-logout/", BackchannelLogoutView.as_view(), name="backchannel_logout"),
]
