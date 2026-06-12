"""Tests for the OAuth2 token manager: refresh, caching, rotation, and the
missing-token error. httpx.post is mocked, so no live OAuth call is made.
"""

import json

import pytest

from eh_mcp import auth as auth_mod
from eh_mcp.auth import TokenError, TokenManager
from eh_mcp.config import Settings


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def make_settings(token_file):
    return Settings(
        client_id="cid",
        client_secret="secret",
        redirect_uri="https://127.0.0.1:8765/callback",
        api_base="https://api.employmenthero.com",
        oauth_base="https://oauth.employmenthero.com",
        token_file=str(token_file),
        scopes="teams:list employees:list",
    )


def write_token(path, refresh_token):
    path.write_text(json.dumps({"refresh_token": refresh_token}))


def test_refresh_returns_access_token_and_caches(monkeypatch, tmp_path):
    token_file = tmp_path / "token.json"
    write_token(token_file, "rt-1")
    posts = []

    def fake_post(url, params=None, timeout=None):
        posts.append(params)
        return FakeResponse(200, {"access_token": "at-1", "expires_in": 900})

    monkeypatch.setattr(auth_mod.httpx, "post", fake_post)
    mgr = TokenManager(make_settings(token_file))

    assert mgr.access_token() == "at-1"
    # Second call is served from cache; no extra POST.
    assert mgr.access_token() == "at-1"
    assert len(posts) == 1
    assert posts[0]["grant_type"] == "refresh_token"
    assert posts[0]["refresh_token"] == "rt-1"


def test_rotated_refresh_token_is_persisted(monkeypatch, tmp_path):
    token_file = tmp_path / "token.json"
    write_token(token_file, "rt-1")

    def fake_post(url, params=None, timeout=None):
        return FakeResponse(
            200, {"access_token": "at-1", "refresh_token": "rt-2", "expires_in": 900}
        )

    monkeypatch.setattr(auth_mod.httpx, "post", fake_post)
    mgr = TokenManager(make_settings(token_file))
    mgr.access_token()

    stored = json.loads(token_file.read_text())
    assert stored["refresh_token"] == "rt-2"


def test_invalidate_forces_new_refresh(monkeypatch, tmp_path):
    token_file = tmp_path / "token.json"
    write_token(token_file, "rt-1")
    posts = []

    def fake_post(url, params=None, timeout=None):
        posts.append(params)
        return FakeResponse(200, {"access_token": "at", "expires_in": 900})

    monkeypatch.setattr(auth_mod.httpx, "post", fake_post)
    mgr = TokenManager(make_settings(token_file))

    mgr.access_token()
    mgr.invalidate()
    mgr.access_token()
    assert len(posts) == 2


def test_missing_token_file_raises(tmp_path):
    mgr = TokenManager(make_settings(tmp_path / "does-not-exist.json"))
    with pytest.raises(TokenError):
        mgr.access_token()


def test_failed_refresh_raises(monkeypatch, tmp_path):
    token_file = tmp_path / "token.json"
    write_token(token_file, "rt-1")

    def fake_post(url, params=None, timeout=None):
        return FakeResponse(400, {"error": "invalid_grant"})

    monkeypatch.setattr(auth_mod.httpx, "post", fake_post)
    mgr = TokenManager(make_settings(token_file))
    with pytest.raises(TokenError):
        mgr.access_token()


def test_invalid_grant_message_is_friendly_and_leak_free(monkeypatch, tmp_path):
    token_file = tmp_path / "token.json"
    write_token(token_file, "rt-1")
    body = {"error": "invalid_grant", "error_description": "secret-internals-xyz"}
    monkeypatch.setattr(auth_mod.httpx, "post", lambda *a, **k: FakeResponse(400, body))
    mgr = TokenManager(make_settings(token_file))
    with pytest.raises(TokenError) as excinfo:
        mgr.access_token()
    msg = str(excinfo.value)
    assert "connect employment hero" in msg.lower()
    assert "secret-internals-xyz" not in msg
    assert "invalid_grant" not in msg


def test_generic_refresh_failure_never_echoes_body(monkeypatch, tmp_path):
    token_file = tmp_path / "token.json"
    write_token(token_file, "rt-1")
    body = {"weird": "payload", "refresh_token": "LEAKED-TOKEN"}
    monkeypatch.setattr(auth_mod.httpx, "post", lambda *a, **k: FakeResponse(500, body))
    mgr = TokenManager(make_settings(token_file))
    with pytest.raises(TokenError) as excinfo:
        mgr.access_token()
    assert "LEAKED-TOKEN" not in str(excinfo.value)


def test_missing_access_token_never_echoes_payload(monkeypatch, tmp_path):
    token_file = tmp_path / "token.json"
    write_token(token_file, "rt-1")
    body = {"refresh_token": "LEAKED-TOKEN"}
    monkeypatch.setattr(auth_mod.httpx, "post", lambda *a, **k: FakeResponse(200, body))
    mgr = TokenManager(make_settings(token_file))
    with pytest.raises(TokenError) as excinfo:
        mgr.access_token()
    assert "LEAKED-TOKEN" not in str(excinfo.value)


def test_corrupt_token_file_raises_token_error(tmp_path):
    token_file = tmp_path / "token.json"
    token_file.write_text("{not valid json")
    mgr = TokenManager(make_settings(token_file))
    with pytest.raises(TokenError) as excinfo:
        mgr.access_token()
    assert "connect employment hero" in str(excinfo.value).lower()
