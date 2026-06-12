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
import os
import secrets
import ssl
import threading
import time
import urllib.parse
import webbrowser

import httpx

from .auth import store_refresh_token
from .config import Settings

logger = logging.getLogger("eh_mcp.oauth")

_DEFAULT_TIMEOUT_SECONDS = 300
_CERT_NAME = "loopback-cert.pem"
_KEY_NAME = "loopback-key.pem"


def ensure_self_signed_cert(cert_dir: str) -> tuple[str, str]:
    """Return paths to a self-signed cert/key for the loopback HTTPS listener.

    Employment Hero requires an https redirect URI, so the local sign-in server
    must serve TLS. A self-signed cert for 127.0.0.1/localhost is generated once
    and cached. The browser shows a one-time "not private" warning the user
    clicks through; nothing leaves the machine, so this is safe for loopback.
    """
    cert_path = os.path.join(cert_dir, _CERT_NAME)
    key_path = os.path.join(cert_dir, _KEY_NAME)
    if os.path.exists(cert_path) and os.path.exists(key_path):
        return cert_path, key_path

    os.makedirs(cert_dir, exist_ok=True)

    import ipaddress
    from datetime import datetime, timedelta, timezone

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                    x509.DNSName("localhost"),
                ]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
        )
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path


class OAuthFlowError(RuntimeError):
    """Raised when the interactive authorization flow cannot complete."""


def build_authorize_url(settings: Settings, state: str | None = None) -> str:
    # The scope param IS required: EH grants the token only the scopes requested
    # here (intersected with the app's configured scopes). Without it the token
    # has no permissions and every API call 403s. The earlier 403 that looked
    # scope-related was actually the 127.0.0.1 redirect (now a hosted page).
    params = {
        "client_id": settings.client_id,
        "redirect_uri": settings.redirect_uri,
        "response_type": "code",
        "scope": settings.scopes,
    }
    if state:
        params["state"] = state
    return f"{settings.oauth_base}/oauth2/authorize?{urllib.parse.urlencode(params)}"


def exchange_code_for_refresh_token(settings: Settings, code: str) -> str:
    """Exchange an authorization code for a refresh token and store it."""
    # EH's token endpoint reads parameters from the query string, not the body
    # (confirmed from the official Postman collection).
    resp = httpx.post(
        f"{settings.oauth_base}/oauth2/token",
        params={
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
    state: str | None = None,
) -> str:
    """Run the full browser sign-in. Returns the refresh token on success.

    Usually called from a background thread (the connect tool returns
    immediately), so it can block for the full timeout without affecting the
    MCP tool call.
    """
    redirect = urllib.parse.urlparse(settings.redirect_uri)
    host = redirect.hostname or "127.0.0.1"
    port = redirect.port or 8765
    # Random per-flow state: the handler ignores any callback that does not
    # echo it back, so another local process or a malicious web page cannot
    # inject an attacker-chosen authorization code (login CSRF).
    expected_state = state or secrets.token_urlsafe(32)
    result: dict[str, str] = {}

    class _Handler(http.server.BaseHTTPRequestHandler):
        # Drop idle/stalled connections (e.g. a browser preconnect probe)
        # instead of letting one block the flow.
        timeout = 10

        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            state = params.get("state", [""])[0]
            if "code" in params and state == expected_state:
                result["code"] = params["code"][0]
                body, status = b"Employment Hero sign-in complete. You can close this tab.", 200
            elif "code" in params:
                # Wrong/missing state: do NOT capture the code.
                body, status = b"Sign-in rejected: state mismatch. Try connecting again.", 400
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
        # Threading server: a stalled connection must not block the real
        # callback or deadlock shutdown().
        server = http.server.ThreadingHTTPServer((host, port), _Handler)
        server.daemon_threads = True
    except OSError as exc:
        raise OAuthFlowError(
            f"Could not start the sign-in listener on {host}:{port} ({exc}). "
            f"Close whatever is using port {port} and try connecting again."
        ) from exc

    if redirect.scheme == "https":
        cert_dir = os.path.dirname(settings.token_file) or "."
        try:
            cert_path, key_path = ensure_self_signed_cert(cert_dir)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert_path, key_path)
            server.socket = context.wrap_socket(server.socket, server_side=True)
        except Exception as exc:
            server.server_close()
            raise OAuthFlowError(
                f"Could not set up the secure sign-in listener: {exc}"
            ) from exc

    authorize_url = build_authorize_url(settings, state=expected_state)
    logger.info("Authorization URL: %s", authorize_url)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        if open_browser:
            try:
                webbrowser.open(authorize_url)
            except Exception as exc:
                # A failure to launch the browser must not abort the flow: the
                # user can still open the URL manually (it is in the connect
                # tool's response and the logs).
                logger.warning("could not open browser automatically: %s", exc)
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if "code" in result or "error" in result:
                break
            time.sleep(0.5)
    finally:
        server.shutdown()
        server.server_close()

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
