"""The one-time interactive OAuth2 Authorization Code flow, runnable in-process.

Both the `connect_employment_hero` MCP tool and `scripts/authorize.py` call
`run_authorization_flow`: it opens the user's browser to the Employment Hero
consent screen, catches the redirect on a local loopback server, exchanges the
code, and stores the refresh token. No script execution is required of the user;
the tool drives it from inside Claude Desktop.
"""

from __future__ import annotations

import http.server
import logging
import threading
import time
import urllib.parse
import webbrowser

import httpx

from .auth import store_refresh_token
from .config import Settings

logger = logging.getLogger("eh_mcp.oauth")

_DEFAULT_TIMEOUT_SECONDS = 300


class OAuthFlowError(RuntimeError):
    """Raised when the interactive authorization flow cannot complete."""


def build_authorize_url(settings: Settings) -> str:
    query = urllib.parse.urlencode(
        {
            "client_id": settings.client_id,
            "redirect_uri": settings.redirect_uri,
            "response_type": "code",
            "scope": settings.scopes,
        }
    )
    return f"{settings.oauth_base}/oauth2/authorize?{query}"


def exchange_code_for_refresh_token(settings: Settings, code: str) -> str:
    """Exchange an authorization code for a refresh token and store it."""
    resp = httpx.post(
        f"{settings.oauth_base}/oauth2/token",
        data={
            "client_id": settings.client_id,
            "client_secret": settings.client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.redirect_uri,
        },
        timeout=30.0,
    )
    if resp.status_code != 200:
        raise OAuthFlowError(
            f"Token exchange with Employment Hero failed ({resp.status_code})."
        )
    refresh_token = resp.json().get("refresh_token")
    if not refresh_token:
        raise OAuthFlowError("Employment Hero did not return a refresh token.")
    store_refresh_token(settings.token_file, refresh_token)
    return refresh_token


def run_authorization_flow(
    settings: Settings,
    *,
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    open_browser: bool = True,
) -> str:
    """Run the full browser sign-in. Returns the refresh token on success."""
    redirect = urllib.parse.urlparse(settings.redirect_uri)
    host = redirect.hostname or "127.0.0.1"
    port = redirect.port or 8765
    result: dict[str, str] = {}

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" in params:
                result["code"] = params["code"][0]
                body, status = b"Employment Hero sign-in complete. You can close this tab.", 200
            elif "error" in params:
                result["error"] = params["error"][0]
                body, status = (f"Sign-in failed: {params['error'][0]}".encode(), 400)
            else:
                body, status = b"Waiting for the authorization code.", 400
            self.send_response(status)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args) -> None:  # silence default logging
            return

    try:
        server = http.server.HTTPServer((host, port), _Handler)
    except OSError as exc:
        raise OAuthFlowError(
            f"Could not start the sign-in listener on {host}:{port} ({exc}). "
            f"Close whatever is using port {port} and try connecting again."
        ) from exc

    authorize_url = build_authorize_url(settings)
    logger.info("Authorization URL: %s", authorize_url)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        if open_browser:
            webbrowser.open(authorize_url)
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if "code" in result or "error" in result:
                break
            time.sleep(0.5)
    finally:
        server.shutdown()

    if "error" in result:
        raise OAuthFlowError(
            f"Employment Hero returned an error during sign-in: {result['error']}."
        )
    code = result.get("code")
    if not code:
        raise OAuthFlowError(
            "Timed out waiting for you to approve access in the browser. "
            f"If the browser did not open, visit:\n{authorize_url}"
        )
    return exchange_code_for_refresh_token(settings, code)
