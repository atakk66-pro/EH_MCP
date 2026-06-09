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
import os
import threading
import time

import httpx

from .config import Settings

# Access tokens last ~15 minutes (900s). Refresh this many seconds early so a
# token never expires mid-request.
_EXPIRY_SKEW_SECONDS = 60


class TokenError(RuntimeError):
    """Raised when a token cannot be loaded, refreshed, or stored."""


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
        resp = httpx.post(
            f"{self._s.oauth_base}/oauth2/token",
            data={
                "client_id": self._s.client_id,
                "client_secret": self._s.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            timeout=30.0,
        )
        if resp.status_code != 200:
            raise TokenError(
                f"Token refresh failed ({resp.status_code}): {resp.text[:300]}"
            )
        payload = resp.json()
        access = payload.get("access_token")
        if not access:
            raise TokenError(f"No access_token in refresh response: {payload}")

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
                f"No token file at {path}. Run `python scripts/authorize.py` once "
                "to authorize the integration."
            )
        with open(path) as f:
            data = json.load(f)
        refresh_token = data.get("refresh_token")
        if not refresh_token:
            raise TokenError(f"Token file {path} has no refresh_token.")
        return refresh_token

    def _store_refresh_token(self, refresh_token: str) -> None:
        path = self._s.token_file
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w") as f:
            json.dump({"refresh_token": refresh_token}, f)
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
