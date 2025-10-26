from __future__ import annotations

import urllib.parse as urlparse
from typing import Dict, Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
import app.auth as auth_mod
from itsdangerous import URLSafeSerializer


@pytest.fixture()
def client():
    return TestClient(app)


def parse_query(url: str) -> Dict[str, Any]:
    return dict(urlparse.parse_qsl(urlparse.urlsplit(url).query))


def test_login_missing_config_returns_500(client, monkeypatch):
    # Ensure missing client_id/redirect_uri
    monkeypatch.setattr(auth_mod.settings, "github_client_id", None)
    monkeypatch.setattr(auth_mod.settings, "github_redirect_uri", None)

    r = client.get("/auth/github/login", allow_redirects=False)
    assert r.status_code == 500
    assert "GitHub OAuth not configured" in r.json().get("detail", "")


def test_login_success_redirect_and_state_signed(client, monkeypatch):
    monkeypatch.setattr(auth_mod.settings, "github_client_id", "cid123")
    monkeypatch.setattr(auth_mod.settings,
                        "github_redirect_uri", "http://localhost/callback")

    r = client.get("/auth/github/login", allow_redirects=False)
    assert r.status_code in (302, 303, 307, 308)
    location = r.headers.get("location")
    assert location and location.startswith(
        "https://github.com/login/oauth/authorize")
    q = parse_query(location)

    assert q.get("client_id") == "cid123"
    assert q.get("redirect_uri") == "http://localhost/callback"
    # GitHub scopes should be encoded as space-separated string
    assert q.get("scope") == "repo read:user"
    assert "state" in q and q["state"]

    # Verify state is signed with our secret
    s = URLSafeSerializer(
        auth_mod.settings.session_secret_key, salt="github-oauth-state")
    s.loads(q["state"])  # should not raise


def test_callback_missing_code_returns_400(client):
    r = client.get("/auth/github/callback", allow_redirects=False)
    assert r.status_code == 400
    assert "Missing 'code'" in r.json().get("detail", "")


def test_callback_missing_state_returns_400(client, monkeypatch):
    monkeypatch.setattr(auth_mod.settings, "github_client_id", "cid123")
    monkeypatch.setattr(auth_mod.settings, "github_client_secret", "csec")
    monkeypatch.setattr(auth_mod.settings,
                        "github_redirect_uri", "http://localhost/callback")

    r = client.get("/auth/github/callback?code=abc", allow_redirects=False)
    assert r.status_code == 400
    assert "Missing OAuth state" in r.json().get("detail", "")


def test_callback_invalid_state_returns_400(client, monkeypatch):
    # First perform login to set a session value for expected state
    monkeypatch.setattr(auth_mod.settings, "github_client_id", "cid123")
    monkeypatch.setattr(auth_mod.settings,
                        "github_redirect_uri", "http://localhost/callback")

    r_login = client.get("/auth/github/login", allow_redirects=False)
    assert r_login.status_code in (302, 303, 307, 308)

    # Now hit callback with an invalid, unsigned state
    monkeypatch.setattr(auth_mod.settings, "github_client_secret", "csec")
    r = client.get("/auth/github/callback?code=abc&state=invalid",
                   allow_redirects=False)
    assert r.status_code == 400
    assert "Invalid OAuth state" in r.json().get("detail", "")


@pytest.mark.usefixtures("respx_mock")
def test_callback_success_sets_session_and_redirects(client, monkeypatch, respx_mock):
    # Configure settings
    monkeypatch.setattr(auth_mod.settings, "github_client_id", "cid123")
    monkeypatch.setattr(auth_mod.settings, "github_client_secret", "csec")
    monkeypatch.setattr(auth_mod.settings,
                        "github_redirect_uri", "http://localhost/callback")

    # Start login to obtain signed state and session cookie
    r_login = client.get("/auth/github/login", allow_redirects=False)
    assert r_login.status_code in (302, 303, 307, 308)
    q = parse_query(r_login.headers["location"])
    state = q["state"]

    # Mock GitHub token exchange and user fetch
    respx_mock.post("https://github.com/login/oauth/access_token").respond(200,
                                                                           json={"access_token": "tok-123"})
    respx_mock.get("https://api.github.com/user").respond(200,
                                                          json={"login": "octocat"})

    r_cb = client.get(
        f"/auth/github/callback?code=abc&state={state}", allow_redirects=False)
    assert r_cb.status_code in (302, 303, 307, 308)
    # Default success redirect: first allowed origin
    assert r_cb.headers.get("location") == "http://localhost:4000"


@pytest.mark.usefixtures("respx_mock")
def test_me_unauthenticated_401(client):
    r = client.get("/auth/github/me")
    assert r.status_code == 401
    assert r.json() == {"authenticated": False}


@pytest.mark.usefixtures("respx_mock")
def test_me_authenticated_after_callback_ok(client, monkeypatch, respx_mock):
    # Configure and login
    monkeypatch.setattr(auth_mod.settings, "github_client_id", "cid123")
    monkeypatch.setattr(auth_mod.settings, "github_client_secret", "csec")
    monkeypatch.setattr(auth_mod.settings,
                        "github_redirect_uri", "http://localhost/callback")

    r_login = client.get("/auth/github/login", allow_redirects=False)
    q = parse_query(r_login.headers["location"])
    state = q["state"]

    # Mock OAuth + user
    respx_mock.post("https://github.com/login/oauth/access_token").respond(200,
                                                                           json={"access_token": "tok-123"})
    respx_mock.get("https://api.github.com/user").respond(200,
                                                          json={"login": "octocat", "id": 1})

    client.get(
        f"/auth/github/callback?code=abc&state={state}", allow_redirects=False)

    r_me = client.get("/auth/github/me")
    assert r_me.status_code == 200
    data = r_me.json()
    assert data.get("authenticated") is True
    assert data.get("user", {}).get("login") == "octocat"
