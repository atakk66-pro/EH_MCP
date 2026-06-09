"""Configuration loaded from environment variables (and an optional .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Loads .env if present. Does not override variables already set in the
# environment, so Claude Desktop's `env` block always wins over a stray .env.
load_dotenv(override=False)

DEFAULT_API_BASE = "https://api.employmenthero.com"
DEFAULT_OAUTH_BASE = "https://oauth.employmenthero.com"
DEFAULT_REDIRECT_URI = "http://localhost:8765/callback"
# Least-privilege, read-only scopes. employees:read is only needed for the
# employee_count aggregate tool. Never request a :write scope here.
DEFAULT_SCOPES = "urn:mainapp:organisations:read urn:mainapp:employees:read"
DEFAULT_TOKEN_FILE = os.path.expanduser("~/.eh_mcp/token.json")


@dataclass(frozen=True)
class Settings:
    client_id: str
    client_secret: str
    redirect_uri: str
    api_base: str
    oauth_base: str
    token_file: str
    scopes: str


def load_settings() -> Settings:
    """Read settings from the environment. Raises if required vars are missing."""
    missing = [k for k in ("EH_CLIENT_ID", "EH_CLIENT_SECRET") if not os.environ.get(k)]
    if missing:
        raise RuntimeError(
            "Missing required environment variables: "
            + ", ".join(missing)
            + ". Copy .env.example to .env and fill them in, or set them in the "
            "Claude Desktop config 'env' block."
        )
    return Settings(
        client_id=os.environ["EH_CLIENT_ID"],
        client_secret=os.environ["EH_CLIENT_SECRET"],
        redirect_uri=os.environ.get("EH_REDIRECT_URI", DEFAULT_REDIRECT_URI),
        api_base=os.environ.get("EH_API_BASE", DEFAULT_API_BASE).rstrip("/"),
        oauth_base=os.environ.get("EH_OAUTH_BASE", DEFAULT_OAUTH_BASE).rstrip("/"),
        token_file=os.environ.get("EH_TOKEN_FILE", DEFAULT_TOKEN_FILE),
        scopes=os.environ.get("EH_SCOPES", DEFAULT_SCOPES),
    )
