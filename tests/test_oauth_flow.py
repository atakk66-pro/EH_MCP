"""Tests for the shared OAuth flow helpers and connection-state helpers.

The interactive browser/loopback parts are not exercised here; the testable
units are the code-for-token exchange and the token-presence helpers.
"""

import json

import httpx
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


def make_settings(token_file, redirect="https://127.0.0.1:8765/callback"):
    return Settings(
        client_id="cid",
        client_secret="secret",
        redirect_uri=redirect,
        api_base="https://api.employmenthero.com",
        oauth_base="https://oauth.employmenthero.com",
        token_file=str(token_file),
        scopes="teams:list employees:list",
    )


def test_build_authorize_url_has_expected_params(tmp_path):
    url = build_authorize_url(make_settings(tmp_path / "t.json"))
    assert url.startswith("https://oauth.employmenthero.com/oauth2/authorize?")
    assert "response_type=code" in url
    assert "client_id=cid" in url
    assert "redirect_uri=https%3A%2F%2F127.0.0.1%3A8765%2Fcallback" in url


def test_build_authorize_url_includes_state_when_given(tmp_path):
    url = build_authorize_url(make_settings(tmp_path / "t.json"), state="abc123")
    assert "state=abc123" in url


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


def test_settings_replace_supported():
    import dataclasses

    s = make_settings("/tmp/x.json")
    s2 = dataclasses.replace(s, redirect_uri="https://127.0.0.1:9999/callback")
    assert "9999" in build_authorize_url(s2)


def test_full_flow_over_tls_loopback(monkeypatch, tmp_path):
    """End-to-end: TLS listener, state validation, code exchange, persistence.

    Runs the real run_authorization_flow with a real HTTPS server on a high
    port; the 'browser' is this test making httpx calls. A wrong-state callback
    must be rejected; the right-state one completes the flow.
    """
    import threading

    from eh_mcp import oauth_flow as flow

    token_file = tmp_path / "token.json"
    settings = make_settings(token_file, redirect="https://127.0.0.1:18765/callback")

    captured = {}
    monkeypatch.setattr(flow.webbrowser, "open", lambda url: captured.update(url=url))

    def fake_post(url, data=None, timeout=None):
        class R:
            status_code = 200

            @staticmethod
            def json():
                assert data["code"] == "good-code"
                return {"access_token": "at", "refresh_token": "rt-live"}

        return R()

    monkeypatch.setattr(flow.httpx, "post", fake_post)

    result = {}

    def run():
        result["token"] = flow.run_authorization_flow(settings, timeout_seconds=15)

    t = threading.Thread(target=run)
    t.start()
    # Wait for the listener to come up and the authorize URL to be built.
    deadline = 50
    while "url" not in captured and deadline:
        import time

        time.sleep(0.1)
        deadline -= 1
    assert "url" in captured, "flow never opened the browser"
    import urllib.parse

    state = urllib.parse.parse_qs(urllib.parse.urlparse(captured["url"]).query)["state"][0]

    client = httpx.Client(verify=False)
    # Wrong state: rejected, code not captured.
    r = client.get(f"https://127.0.0.1:18765/callback?code=evil&state=WRONG")
    assert r.status_code == 400
    # Correct state: accepted.
    r = client.get(f"https://127.0.0.1:18765/callback?code=good-code&state={state}")
    assert r.status_code == 200
    t.join(timeout=15)
    assert not t.is_alive(), "flow did not finish"
    assert result["token"] == "rt-live"
    assert json.loads(token_file.read_text())["refresh_token"] == "rt-live"
