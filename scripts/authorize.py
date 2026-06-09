"""One-time Employment Hero OAuth2 authorization (Authorization Code flow).

Run once on your workstation:

    python scripts/authorize.py

It opens your browser to the Employment Hero consent screen, captures the
returned authorization code on a local callback, exchanges it for tokens, and
writes the refresh token to EH_TOKEN_FILE (default ~/.eh_mcp/token.json). The
MCP server then uses that refresh token to mint short-lived access tokens.

Read-only: this requests only the scopes in EH_SCOPES.
"""

from __future__ import annotations

import http.server
import json
import os
import sys
import threading
import time
import urllib.parse
import webbrowser

import httpx

# Allow running straight from the repo without installing the package.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from eh_mcp.config import load_settings  # noqa: E402

_AUTH_TIMEOUT_SECONDS = 300
_result: dict[str, str] = {}


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)
        if "code" in params:
            _result["code"] = params["code"][0]
            body = b"Authorization complete. You can close this tab."
            status = 200
        elif "error" in params:
            _result["error"] = params["error"][0]
            body = f"Authorization failed: {params['error'][0]}".encode()
            status = 400
        else:
            body = b"No authorization code in callback."
            status = 400
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # silence default logging
        return


def main() -> None:
    settings = load_settings()
    redirect = urllib.parse.urlparse(settings.redirect_uri)
    host = redirect.hostname or "localhost"
    port = redirect.port or 8765

    authorize_url = f"{settings.oauth_base}/oauth2/authorize?" + urllib.parse.urlencode(
        {
            "client_id": settings.client_id,
            "redirect_uri": settings.redirect_uri,
            "response_type": "code",
            "scope": settings.scopes,
        }
    )

    server = http.server.HTTPServer((host, port), _CallbackHandler)
    threading.Thread(target=server.handle_request, daemon=True).start()

    print("Opening your browser to authorize the integration.")
    print(f"If it does not open, visit this URL manually:\n\n{authorize_url}\n")
    webbrowser.open(authorize_url)

    deadline = time.monotonic() + _AUTH_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if "code" in _result or "error" in _result:
            break
        time.sleep(0.5)

    if "error" in _result:
        sys.exit(f"Authorization error from Employment Hero: {_result['error']}")
    code = _result.get("code")
    if not code:
        sys.exit("Timed out waiting for the authorization callback.")

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
        sys.exit(f"Token exchange failed ({resp.status_code}): {resp.text[:300]}")

    payload = resp.json()
    refresh_token = payload.get("refresh_token")
    if not refresh_token:
        sys.exit(f"No refresh_token in token response: {payload}")

    path = settings.token_file
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump({"refresh_token": refresh_token}, f)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    print(f"Saved refresh token to {path}. You can now run the MCP server.")


if __name__ == "__main__":
    main()
