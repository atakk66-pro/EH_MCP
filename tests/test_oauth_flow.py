"""Tests for the shared OAuth flow helpers and connection-state helpers.

The interactive browser/loopback parts are not exercised here; the testable
units are the code-for-token exchange and the token-presence helpers.
"""

import json

import pytest

from eh_mcp import oauth_flow as flow_mod
from eh_mcp.auth import has_stored_token, store_refresh_token
from eh_mcp.config import Settings
from eh_mcp.oauth_flow import (
    OAuthFlowError,
    build_authorize_url,
    ensure_self_signed_cert,
    exchange_code_for_refresh_token,
)


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def make_settings(token_file):
    return Settings(
        client_id="cid",
        client_secret="secret",
        redirect_uri="http://localhost:8765/callback",
        api_base="https://api.employmenthero.com",
        oauth_base="https://oauth.employmenthero.com",
        token_file=str(token_file),
        scopes="urn:mainapp:organisations:read",
    )


def test_build_authorize_url_has_expected_params(tmp_path):
    url = build_authorize_url(make_settings(tmp_path / "t.json"))
    assert url.startswith("https://oauth.employmenthero.com/oauth2/authorize?")
    assert "response_type=code" in url
    assert "client_id=cid" in url
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8765%2Fcallback" in url


def test_exchange_code_stores_and_returns_refresh_token(monkeypatch, tmp_path):
    token_file = tmp_path / "token.json"

    def fake_post(url, data=None, timeout=None):
        assert data["grant_type"] == "authorization_code"
        assert data["code"] == "the-code"
        return FakeResponse(200, {"access_token": "at", "refresh_token": "rt-new"})

    monkeypatch.setattr(flow_mod.httpx, "post", fake_post)
    rt = exchange_code_for_refresh_token(make_settings(token_file), "the-code")
    assert rt == "rt-new"
    assert json.loads(token_file.read_text())["refresh_token"] == "rt-new"


def test_exchange_code_non_200_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(
        flow_mod.httpx, "post", lambda *a, **k: FakeResponse(400, {"error": "bad"})
    )
    with pytest.raises(OAuthFlowError):
        exchange_code_for_refresh_token(make_settings(tmp_path / "t.json"), "x")


def test_exchange_code_without_refresh_token_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(
        flow_mod.httpx, "post", lambda *a, **k: FakeResponse(200, {"access_token": "at"})
    )
    with pytest.raises(OAuthFlowError):
        exchange_code_for_refresh_token(make_settings(tmp_path / "t.json"), "x")


def test_has_stored_token_roundtrip(tmp_path):
    path = str(tmp_path / "token.json")
    assert has_stored_token(path) is False
    store_refresh_token(path, "rt-1")
    assert has_stored_token(path) is True


def test_has_stored_token_false_for_empty_token(tmp_path):
    path = tmp_path / "token.json"
    path.write_text(json.dumps({"refresh_token": ""}))
    assert has_stored_token(str(path)) is False


def test_self_signed_cert_generated_and_reused(tmp_path):
    cert1, key1 = ensure_self_signed_cert(str(tmp_path))
    assert cert1.endswith(".pem") and key1.endswith(".pem")
    contents = (tmp_path / "loopback-cert.pem").read_text()
    assert "BEGIN CERTIFICATE" in contents
    # A second call reuses the same files rather than regenerating.
    before = (tmp_path / "loopback-key.pem").read_bytes()
    cert2, key2 = ensure_self_signed_cert(str(tmp_path))
    assert (cert2, key2) == (cert1, key1)
    assert (tmp_path / "loopback-key.pem").read_bytes() == before


def test_https_settings_parse_host_and_port():
    s = make_settings("/tmp/x.json")
    s = s.__class__(**{**s.__dict__, "redirect_uri": "https://127.0.0.1:8765/callback"})
    url = build_authorize_url(s)
    assert "redirect_uri=https%3A%2F%2F127.0.0.1%3A8765%2Fcallback" in url
