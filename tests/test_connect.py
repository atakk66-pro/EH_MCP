"""The connect tool must return immediately (not block for the whole sign-in),
so the MCP tool call never times out. The sign-in finishes in the background and
connection_status reflects it."""

import asyncio
import time

from eh_mcp import server
from eh_mcp.auth import store_refresh_token
from eh_mcp.config import Settings


def _settings(tmp_path):
    return Settings(
        client_id="c",
        client_secret="s",
        redirect_uri="https://127.0.0.1:8765/callback",
        api_base="https://api.employmenthero.com",
        oauth_base="https://oauth.employmenthero.com",
        token_file=str(tmp_path / "token.json"),
        scopes="teams:list",
    )


def test_connect_returns_before_signin_finishes(monkeypatch, tmp_path):
    s = _settings(tmp_path)
    monkeypatch.setattr(server, "load_settings", lambda: s)
    server._auth_state.update(status="idle", detail="")
    if server._connect_lock.locked():
        server._connect_lock.release()

    def slow_flow(settings, state=None):
        time.sleep(0.3)  # simulate the user taking time in the browser
        store_refresh_token(settings.token_file, "rt-live")

    monkeypatch.setattr(server, "run_authorization_flow", slow_flow)

    t0 = time.monotonic()
    msg = asyncio.run(server.connect_employment_hero())
    elapsed = time.monotonic() - t0

    assert "Opening Employment Hero" in msg
    assert elapsed < 0.2, "connect blocked instead of returning immediately"
    assert server._auth_state["status"] == "in_progress"

    # The background thread completes the sign-in shortly after.
    for _ in range(50):
        if server._auth_state["status"] == "connected":
            break
        time.sleep(0.05)
    assert server._auth_state["status"] == "connected"


def test_connect_records_failure_without_raising(monkeypatch, tmp_path):
    s = _settings(tmp_path)
    monkeypatch.setattr(server, "load_settings", lambda: s)
    server._auth_state.update(status="idle", detail="")
    if server._connect_lock.locked():
        server._connect_lock.release()

    def boom(settings, state=None):
        raise RuntimeError("browser exploded")

    monkeypatch.setattr(server, "run_authorization_flow", boom)
    msg = asyncio.run(server.connect_employment_hero())
    assert "Opening Employment Hero" in msg  # still returns cleanly

    for _ in range(50):
        if server._auth_state["status"] == "failed":
            break
        time.sleep(0.05)
    assert server._auth_state["status"] == "failed"
    assert "browser exploded" in server._auth_state["detail"]
    # The lock must be released even on failure, so a retry can proceed.
    assert not server._connect_lock.locked()
