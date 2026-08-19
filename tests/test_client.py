# tests/test_client.py
"""Real unit tests for OneHuxClient — PKCE generation/matching, every error-type branch, every
URL-building method, and logout_token HMAC verification. No live network calls: requests.post/
requests.get are mocked per test."""

import base64
import hashlib
import time
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

import jwt
import pytest

from onehux_sso.client import OneHuxClient
from onehux_sso.exceptions import (
    InvalidStateError,
    OrganizationNotFoundError,
    StepUpRequiredError,
    TokenExchangeError,
    TokenExpiredError,
)


def make_client(api_base_url="https://api.example.com"):
    return OneHuxClient(
        client_id="test-client-id",
        client_secret="test-client-secret",
        redirect_uri="https://app.example.com/auth/callback",
        post_logout_redirect_uri="https://app.example.com/auth/logged-out",
        login_base_url="https://accounts.example.com",
        api_base_url=api_base_url,
    )


def mock_response(json_body, status_code=200, ok=True):
    resp = Mock()
    resp.json.return_value = json_body
    resp.status_code = status_code
    resp.ok = ok
    return resp


# --- PKCE generation/matching ---

class TestStartAuthorization:
    def test_code_challenge_matches_verifier(self):
        client = make_client()
        pending = client.start_authorization()
        assert pending.code_verifier
        assert pending.state

        parsed = urlparse(pending.authorization_url)
        query = parse_qs(parsed.query)
        assert query["state"][0] == pending.state
        assert query["code_challenge_method"][0] == "S256"

        expected_challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(pending.code_verifier.encode()).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        assert query["code_challenge"][0] == expected_challenge

    def test_generates_fresh_values_each_call(self):
        client = make_client()
        first = client.start_authorization()
        second = client.start_authorization()
        assert first.state != second.state
        assert first.code_verifier != second.code_verifier


# --- exchange_code error branches ---

class TestExchangeCode:
    def test_invalid_state_error_on_mismatch(self):
        client = make_client()
        with pytest.raises(InvalidStateError):
            client.exchange_code(code="real-code", state="a", expected_state="b", code_verifier="v")

    def test_invalid_state_error_on_missing_code(self):
        client = make_client()
        with pytest.raises(InvalidStateError):
            client.exchange_code(code="", state="s", expected_state="s", code_verifier="v")

    @patch("onehux_sso.client.requests.post")
    def test_step_up_required_error(self, mock_post):
        mock_post.return_value = mock_response(
            {"error": "step_up_required", "error_description": "New device or location detected."},
            status_code=403,
            ok=False,
        )
        client = make_client()
        with pytest.raises(StepUpRequiredError) as exc_info:
            client.exchange_code(code="c", state="s", expected_state="s", code_verifier="v")
        assert exc_info.value.error_description == "New device or location detected."

    @patch("onehux_sso.client.requests.post")
    def test_token_exchange_error_on_other_oauth_error(self, mock_post):
        mock_post.return_value = mock_response(
            {"error": "invalid_grant", "error_description": "Authorization code is expired."},
            status_code=400,
            ok=False,
        )
        client = make_client()
        with pytest.raises(TokenExchangeError) as exc_info:
            client.exchange_code(code="c", state="s", expected_state="s", code_verifier="v")
        assert exc_info.value.error == "invalid_grant"
        assert exc_info.value.status_code == 400

    @patch("onehux_sso.client.requests.post")
    def test_success(self, mock_post):
        mock_post.return_value = mock_response(
            {
                "access_token": "at-123",
                "id_token": "id-456",
                "token_type": "Bearer",
                "expires_in": 900,
                "scope": "openid profile email",
            }
        )
        client = make_client()
        tokens = client.exchange_code(code="c", state="s", expected_state="s", code_verifier="v")
        assert tokens.access_token == "at-123"
        assert tokens.expires_in == 900


# --- get_userinfo ---

class TestGetUserinfo:
    @patch("onehux_sso.client.requests.get")
    def test_token_expired_error_on_non_2xx(self, mock_get):
        mock_get.return_value = mock_response({}, status_code=401, ok=False)
        client = make_client()
        with pytest.raises(TokenExpiredError):
            client.get_userinfo(access_token="expired")


# --- get_public_applications ---

class TestGetPublicApplications:
    @patch("onehux_sso.client.requests.get")
    def test_success(self, mock_get):
        mock_get.return_value = mock_response(
            [{"name": "ODS", "logo_url": "https://example.com/logo.png", "home_url": "https://ods.example.com"}]
        )
        client = make_client()
        apps = client.get_public_applications(org_slug="onehux")
        assert len(apps) == 1
        assert apps[0].name == "ODS"
        assert apps[0].home_url == "https://ods.example.com"

        called_url = mock_get.call_args[0][0]
        assert called_url == "https://api.example.com/api/v1/organizations/onehux/public-applications/"

    @patch("onehux_sso.client.requests.get")
    def test_organization_not_found_error(self, mock_get):
        mock_get.return_value = mock_response(
            {"error": "not_found", "error_description": "No Organization matches that slug."},
            status_code=404,
            ok=False,
        )
        client = make_client()
        with pytest.raises(OrganizationNotFoundError):
            client.get_public_applications(org_slug="nope")


# --- URL-building methods ---

class TestBuildLogoutUrl:
    def test_no_state_when_omitted(self):
        client = make_client()
        parsed = urlparse(client.build_logout_url())
        assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == "https://accounts.example.com/end-session"
        query = parse_qs(parsed.query)
        assert query["client_id"][0] == "test-client-id"
        assert query["post_logout_redirect_uri"][0] == "https://app.example.com/auth/logged-out"
        assert "state" not in query

    def test_includes_state_when_given(self):
        client = make_client()
        parsed = urlparse(client.build_logout_url(state="xyz"))
        assert parse_qs(parsed.query)["state"][0] == "xyz"


class TestBuildStepUpRedirectUrl:
    def test_correct_host_path_params_and_code_challenge(self):
        client = make_client()
        code_verifier = "abc123verifier"
        parsed = urlparse(client.build_step_up_redirect_url(code_verifier=code_verifier, state="state-xyz"))
        assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == "https://accounts.example.com/login/email-otp"
        query = parse_qs(parsed.query)
        assert query["reason"][0] == "step_up"
        assert query["client_id"][0] == "test-client-id"
        assert query["redirect_uri"][0] == "https://app.example.com/auth/callback"
        assert query["state"][0] == "state-xyz"

        expected_challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).rstrip(b"=").decode("ascii")
        )
        assert query["code_challenge"][0] == expected_challenge


# --- logout_token HMAC verification ---

def valid_claims():
    now = int(time.time())
    return {
        "iss": "https://accounts.onehux.com",
        "aud": "test-client-id",
        "iat": now,
        "exp": now + 120,
        "jti": "unique-id",
        "events": {"http://schemas.openid.net/event/backchannel-logout": {}},
        "sid": "session-123",
    }


class TestVerifyLogoutToken:
    """verify_logout_token() reads BACKCHANNEL_LOGOUT_SIGNING_SECRET via get_setting() — mocked
    directly per test rather than configuring real Django settings, since these tests exercise
    the client's own JWT logic, not Django settings resolution (already covered by conf.py's own
    design, not this file's job to re-test)."""

    def _client_with_secret(self, secret="shared-secret"):
        client = make_client()
        patcher = patch("onehux_sso.client.get_setting", return_value=secret)
        patcher.start()
        self.addfinalizer = patcher.stop
        return client, patcher

    def test_accepts_valid_token(self):
        client, patcher = self._client_with_secret()
        try:
            token = jwt.encode(valid_claims(), "shared-secret", algorithm="HS256")
            payload = client.verify_logout_token(logout_token=token)
            assert payload["sid"] == "session-123"
        finally:
            patcher.stop()

    def test_rejects_wrong_signature(self):
        client, patcher = self._client_with_secret()
        try:
            token = jwt.encode(valid_claims(), "wrong-secret", algorithm="HS256")
            with pytest.raises(Exception):
                client.verify_logout_token(logout_token=token)
        finally:
            patcher.stop()

    def test_rejects_expired_token(self):
        client, patcher = self._client_with_secret()
        try:
            claims = valid_claims()
            claims["exp"] = int(time.time()) - 60
            token = jwt.encode(claims, "shared-secret", algorithm="HS256")
            with pytest.raises(Exception):
                client.verify_logout_token(logout_token=token)
        finally:
            patcher.stop()

    def test_rejects_wrong_audience(self):
        client, patcher = self._client_with_secret()
        try:
            claims = valid_claims()
            claims["aud"] = "some-other-client"
            token = jwt.encode(claims, "shared-secret", algorithm="HS256")
            with pytest.raises(Exception):
                client.verify_logout_token(logout_token=token)
        finally:
            patcher.stop()

    def test_rejects_nonce_present(self):
        client, patcher = self._client_with_secret()
        try:
            claims = valid_claims()
            claims["nonce"] = "should-not-be-here"
            token = jwt.encode(claims, "shared-secret", algorithm="HS256")
            with pytest.raises(Exception):
                client.verify_logout_token(logout_token=token)
        finally:
            patcher.stop()

    def test_rejects_missing_events_claim(self):
        client, patcher = self._client_with_secret()
        try:
            claims = valid_claims()
            del claims["events"]
            token = jwt.encode(claims, "shared-secret", algorithm="HS256")
            with pytest.raises(Exception):
                client.verify_logout_token(logout_token=token)
        finally:
            patcher.stop()

    def test_rejects_missing_sub_and_sid(self):
        client, patcher = self._client_with_secret()
        try:
            claims = valid_claims()
            del claims["sid"]
            token = jwt.encode(claims, "shared-secret", algorithm="HS256")
            with pytest.raises(Exception):
                client.verify_logout_token(logout_token=token)
        finally:
            patcher.stop()
