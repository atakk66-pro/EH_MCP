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
# Employment Hero requires an https redirect URI. The local sign-in listener
# serves TLS with a self-signed cert (see oauth_flow.ensure_self_signed_cert).
DEFAULT_REDIRECT_URI = "https://127.0.0.1:8765/callback"
# The exact scopes configured on the registered EH app ("NobleCare KPI Reader",
# from its View Application page). EH's real scope format is resource:action,
# not the urn:mainapp:...:read form shown in some docs. All are read-only, and
# the app's scope set is immutable, so this list must match it exactly.
# work_eligibility and onboard_polling_status are granted to the token but no
# tool ever reads them (blocked by the allowlist; see docs/ALLOWLIST.md).
DEFAULT_SCOPES = " ".join(
    (
        "cost_centres:list",
        "employees:list",
        "employees:show",
        "employees:onboard_polling_status",
        "employees_certifications:list",
        "employees:leave_balances:list",
        "employees:rostered_shifts:job_status",
        "employees:rostered_shifts:shift_cost:show",
        "employees:timesheet_entries:list",
        "employees:work_eligibility:show",
        "employing_entities:list",
        "leave_categories:list",
        "leave_requests:list",
        "leave_requests:show",
        "pay_categories:list",
        "rostered_shifts:list",
        "rostered_shifts:show",
        "teams:list",
        "teams:employees:list",
        "work_locations:list",
        "work_sites:list",
        "work_types:list",
    )
)
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
    # The registered app has no organisations scope, so org discovery may be
    # refused. EH_ORG_ID supplies the organisation directly; tools fall back
    # to it when no organisation_id argument is given.
    org_id: str | None = None


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
        token_file=os.path.expanduser(
            os.environ.get("EH_TOKEN_FILE", DEFAULT_TOKEN_FILE)
        ),
        scopes=os.environ.get("EH_SCOPES", DEFAULT_SCOPES),
        org_id=os.environ.get("EH_ORG_ID") or None,
    )
