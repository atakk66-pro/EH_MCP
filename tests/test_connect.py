"""Tests for the copy-paste sign-in flow (no local server): connect returns a
link, and complete exchanges the pasted code for a token."""

import asyncio

from eh_mcp import server
from eh_mcp.config import Settings


def _settings(tmp_path):
    return Settings(
        client_id="cid",
        client_secret="secret",
        redirect_uri="https://127.0.0.1:8765/callback",
        api_base="https://api.employmenthero.com",
        oauth_base="https://oauth.employmenthero.com",
        token_file=str(tmp_path / "token.json"),
        scopes="teams:list",
    )


def test_extract_code_from_full_url():
    code, state = server._extract_code_and_state(
        "https://127.0.0.1:8765/callback?code=ABC123&state=XYZ"
    )
    assert code == "ABC123"
    assert state == "XYZ"


def test_extract_code_from_bare_code():
    code, state = server._extract_code_and_state("RAWCODE")
    assert code == "RAWCODE"
    assert state is None


def test_extract_code_ignores_wrapping_quotes_and_brackets():
    code, _ = server._extract_code_and_state(
        "<https://127.0.0.1:8765/callback?code=Q1&state=s>"
    )
    assert code == "Q1"


def test_connect_returns_signin_link(monkeypatch, tmp_path):
    s = _settings(tmp_path)
    monkeypatch.setattr(server, "load_settings", lambda: s)
    monkeypatch.setattr(server, "_open_browser_async", lambda url: None)
    server._pending_state.clear()

    msg = asyncio.run(server.connect_employment_hero())
    assert "oauth.employmenthero.com/oauth2/authorize" in msg
    assert "code=" in msg  # instructs the user to copy the code-bearing URL
    assert server._pending_state.get("state")


def test_complete_exchanges_code_and_connects(monkeypatch, tmp_path):
    s = _settings(tmp_path)
    monkeypatch.setattr(server, "load_settings", lambda: s)
    captured = {}

    def fake_exchange(settings, code):
        from eh_mcp.auth import store_refresh_token

        captured["code"] = code
        store_refresh_token(settings.token_file, "rt-live")
        return "rt-live"

    monkeypatch.setattr(server, "exchange_code_for_refresh_token", fake_exchange)
    server._pending_state["state"] = "S1"

    msg = asyncio.run(
        server.complete_employment_hero_signin(
            "https://127.0.0.1:8765/callback?code=GOOD&state=S1"
        )
    )
    assert "Connected to Employment Hero" in msg
    assert captured["code"] == "GOOD"
    # state cleared after success
    assert "state" not in server._pending_state


def test_complete_rejects_state_mismatch(monkeypatch, tmp_path):
    s = _settings(tmp_path)
    monkeypatch.setattr(server, "load_settings", lambda: s)
    server._pending_state["state"] = "EXPECTED"

    msg = asyncio.run(
        server.complete_employment_hero_signin(
            "https://127.0.0.1:8765/callback?code=GOOD&state=WRONG"
        )
    )
    assert "different attempt" in msg.lower()


def test_complete_without_code_asks_again(monkeypatch, tmp_path):
    s = _settings(tmp_path)
    monkeypatch.setattr(server, "load_settings", lambda: s)
    msg = asyncio.run(server.complete_employment_hero_signin(""))
    assert "couldn't find a sign-in code" in msg.lower()
