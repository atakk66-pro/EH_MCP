"""OAuth2 token management for Employment Hero.

The server never performs the interactive authorization flow at runtime. Run
scripts/authorize.py once to obtain a refresh token; this module then exchanges
that refresh token for short-lived (15-minute) access tokens and persists the
rotated refresh token each time.

Read-only: this only ever calls the OAuth token endpoint. It never touches an
Employment Hero write endpoint.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time

import httpx

from .config import Settings

logger = logging.getLogger("eh_mcp.auth")

# Access tokens last ~15 minutes (900s). Refresh this many seconds early so a
# token never expires mid-request.
_EXPIRY_SKEW_SECONDS = 60


class TokenError(RuntimeError):
    """Raised when a token cannot be loaded, refreshed, or stored."""


def store_refresh_token(path: str, refresh_token: str) -> None:
    """Atomically write the refresh token to ``path`` with 0600 permissions.

    The temp file is created 0600 from the start (not chmodded after), so the
    token is never world-readable even briefly.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"refresh_token": refresh_token}, f)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def has_stored_token(path: str) -> bool:
    """True if ``path`` holds a usable refresh token (used for connection status)."""
    if not os.path.exists(path):
        return False
    try:
        with open(path) as f:
            return bool(json.load(f).get("refresh_token"))
    except (OSError, ValueError):
        return False


class TokenManager:
    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._lock = threading.Lock()
        self._access_token: str | None = None
        self._expires_at = 0.0  # time.monotonic() deadline

    def invalidate(self) -> None:
        """Force the next access_token() call to refresh."""
        with self._lock:
            self._access_token = None
            self._expires_at = 0.0

    def access_token(self) -> str:
        with self._lock:
            if self._access_token and time.monotonic() < self._expires_at:
                return self._access_token
            return self._refresh_locked()

    # -- internals -------------------------------------------------------

    def _refresh_locked(self) -> str:
        refresh_token = self._load_refresh_token()
        # EH reads token params from the query string, not the body (per the
        # official Postman collection).
        resp = httpx.post(
            f"{self._s.oauth_base}/oauth2/token",
            params={
                "client_id": self._s.client_id,
                "client_secret": self._s.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            timeout=30.0,
        )
        if resp.status_code != 200:
            # Never put the response body in the error: TokenError text reaches
            # the model via tool results, and OAuth bodies can carry tokens.
            logger.debug("Token refresh failed (%d): %s", resp.status_code, resp.text[:300])
            error_code = ""
            try:
                error_code = str(resp.json().get("error", ""))
            except ValueError:
                pass
            if error_code == "invalid_grant":
                raise TokenError(
                    "The Employment Hero connection has expired or was revoked. "
                    "Ask me to connect Employment Hero again."
                )
            raise TokenError(
                f"Could not refresh the Employment Hero connection (HTTP "
                f"{resp.status_code}). Try again, or ask me to connect "
                "Employment Hero again."
            )
        try:
            payload = resp.json()
        except ValueError:
            raise TokenError(
                "Employment Hero returned an unexpected response while "
                "refreshing the connection. Try again shortly."
            ) from None
        access = payload.get("access_token")
        if not access:
            # Do not interpolate the payload: it may contain token material.
            raise TokenError(
                "Employment Hero did not return an access token. Try again, or "
                "ask me to connect Employment Hero again."
            )

        # Employment Hero rotates refresh tokens: each refresh returns a new one
        # and the old one is invalidated. Persist the new one immediately.
        new_refresh = payload.get("refresh_token")
        if new_refresh and new_refresh != refresh_token:
            self._store_refresh_token(new_refresh)

        expires_in = int(payload.get("expires_in", 900))
        self._access_token = access
        self._expires_at = time.monotonic() + max(30, expires_in - _EXPIRY_SKEW_SECONDS)
        return access

    def _load_refresh_token(self) -> str:
        path = self._s.token_file
        if not os.path.exists(path):
            raise TokenError(
                "Employment Hero is not connected yet. Ask me to connect Employment "
                "Hero (the connect_employment_hero tool) to sign in, then try again."
            )
        try:
            with open(path) as f:
                data = json.load(f)
        except (OSError, ValueError) as exc:
            raise TokenError(
                "The stored Employment Hero connection is unreadable. Ask me to "
                "connect Employment Hero again."
            ) from exc
        refresh_token = data.get("refresh_token")
        if not refresh_token:
            raise TokenError(
                "The stored Employment Hero connection is incomplete. Ask me to "
                "connect Employment Hero again."
            )
        return refresh_token

    def _store_refresh_token(self, refresh_token: str) -> None:
        store_refresh_token(self._s.token_file, refresh_token)
