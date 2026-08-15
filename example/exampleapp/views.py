# exampleapp/views.py
"""The demo home page — exercises onehux_sso end to end against real production. Deliberately
plain (no template engine complexity) so the whole example is easy to read in one file."""

from django.http import HttpRequest, HttpResponse

from onehux_sso import OneHuxClient, TokenExpiredError
from onehux_sso.conf import get_setting

_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>onehux-sso example</title>
<style>body{{font-family:system-ui,sans-serif;max-width:640px;margin:3rem auto;padding:0 1rem}}
a.btn{{display:inline-block;padding:.5rem 1rem;border:1px solid #333;border-radius:4px;
text-decoration:none;color:#111;margin-right:.5rem}}
pre{{background:#f4f4f4;padding:1rem;overflow-x:auto;white-space:pre-wrap}}</style></head>
<body>{body}</body></html>"""


def home(request: HttpRequest) -> HttpResponse:
    access_token = request.session.get(get_setting("SESSION_ACCESS_TOKEN_KEY"))
    if not access_token:
        return HttpResponse(
            _PAGE.format(
                body="""
                <h1>onehux-sso example — signed out</h1>
                <p>Real end-to-end demo of the onehux_sso Django package against production.</p>
                <a class="btn" href="/auth/login/">Sign in</a>
                """
            )
        )

    client = OneHuxClient.from_settings()
    try:
        claims = client.get_userinfo(access_token=access_token)
    except TokenExpiredError as exc:
        return HttpResponse(
            _PAGE.format(
                body=f"""
                <h1>Token expired</h1>
                <pre>{exc}</pre>
                <a class="btn" href="/auth/login/">Sign in again</a>
                """
            ),
            status=401,
        )

    import json

    return HttpResponse(
        _PAGE.format(
            body=f"""
            <h1>onehux-sso example — signed in</h1>
            <p>Real claims from GET /api/v1/oauth/userinfo/:</p>
            <pre>{json.dumps(claims, indent=2)}</pre>
            <a class="btn" href="/auth/logout/">Log out (RP-initiated SLO)</a>
            <p style="margin-top:2rem;color:#666">To confirm true single-logout, separately open
            <a href="https://accounts.onehux.com/dashboard" target="_blank">accounts.onehux.com/dashboard</a>
            after logging out — it should demand login again.</p>
            """
        )
    )


def logged_out(request: HttpRequest) -> HttpResponse:
    return HttpResponse(
        _PAGE.format(
            body="""
            <h1>Logged out</h1>
            <p>Redirected back here by OneHux's own RP-initiated logout.</p>
            <a class="btn" href="/">Home</a>
            """
        )
    )
