"""FastMCP stdio server exposing read-only Employment Hero tools.

Every tool returns an allowlist model from models.py, so no personal data is
serialized to the model. Only read tools are registered: there is no write tool
for the model to call.
"""

from __future__ import annotations

import logging
import os
import sys

from mcp.server.fastmcp import FastMCP

from .auth import TokenManager, has_stored_token
from .client import EHClient
from .config import load_settings
from .models import NamedEntity, Organisation, to_named, to_org
from .oauth_flow import OAuthFlowError, run_authorization_flow

logger = logging.getLogger("eh_mcp.tools")

mcp = FastMCP("employment-hero-readonly")

# The client is built lazily on first use so the module imports (and `--help`,
# tests, etc.) work without credentials present.
_client: EHClient | None = None


def _get_client() -> EHClient:
    global _client
    if _client is None:
        settings = load_settings()
        _client = EHClient(settings, TokenManager(settings))
    return _client


@mcp.tool()
def connect_employment_hero() -> str:
    """Sign in to Employment Hero. Run this once before asking for any data.

    Opens your browser to approve read-only access. After you approve, this
    machine stays connected and you will not need to do it again.
    """
    logger.info("tool connect_employment_hero")
    try:
        settings = load_settings()
    except RuntimeError as exc:
        return f"Cannot connect: {exc}"
    try:
        run_authorization_flow(settings)
    except OAuthFlowError as exc:
        return f"Could not connect to Employment Hero: {exc}"
    # Drop any cached client so the next call picks up the new token.
    global _client
    _client = None
    return (
        "Connected to Employment Hero. You can now ask for organisations, teams, "
        "work locations, and headcount."
    )


@mcp.tool()
def connection_status() -> str:
    """Report whether this machine is signed in to Employment Hero."""
    logger.info("tool connection_status")
    try:
        settings = load_settings()
    except RuntimeError as exc:
        return f"Not configured: {exc}"
    if has_stored_token(settings.token_file):
        return "Connected to Employment Hero."
    return (
        "Not connected to Employment Hero yet. Ask me to connect Employment Hero "
        "to sign in."
    )


@mcp.tool()
def list_organisations() -> list[Organisation]:
    """List the Employment Hero organisations this integration can access.

    Returns only id and name. No personal data.
    """
    logger.info("tool list_organisations")
    client = _get_client()
    return [to_org(r) for r in client.paginate("/api/v1/organisations")]


@mcp.tool()
def list_teams(organisation_id: str) -> list[NamedEntity]:
    """List teams (shown as 'Groups' in the UI) in an organisation.

    Returns only each team's id and name. No personal data.
    """
    logger.info("tool list_teams organisation_id=%s", organisation_id)
    client = _get_client()
    path = f"/api/v1/organisations/{organisation_id}/teams"
    return [to_named(r) for r in client.paginate(path)]


@mcp.tool()
def list_departments(organisation_id: str) -> list[NamedEntity]:
    """List departments in an organisation.

    Returns only each department's id and name. No personal data.
    """
    logger.info("tool list_departments organisation_id=%s", organisation_id)
    client = _get_client()
    path = f"/api/v1/organisations/{organisation_id}/departments"
    return [to_named(r) for r in client.paginate(path)]


@mcp.tool()
def list_work_locations(organisation_id: str) -> list[NamedEntity]:
    """List work locations in an organisation.

    Returns only each location's id and name. No personal data.
    """
    logger.info("tool list_work_locations organisation_id=%s", organisation_id)
    client = _get_client()
    path = f"/api/v1/organisations/{organisation_id}/work_locations"
    return [to_named(r) for r in client.paginate(path)]


@mcp.tool()
def employee_count(organisation_id: str) -> int:
    """Return the total number of employees in an organisation.

    A single aggregate integer. Reads only the pagination total; no individual
    employee record or field is returned. Requires the urn:mainapp:employees:read
    scope.
    """
    logger.info("tool employee_count organisation_id=%s", organisation_id)
    client = _get_client()
    path = f"/api/v1/organisations/{organisation_id}/employees"
    return client.total_items(path)


def _configure_logging() -> None:
    """Log to stderr only. stdout is the MCP transport and must stay clean."""
    level = os.environ.get("EH_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        stream=sys.stderr,
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def main() -> None:
    """Run the server over stdio (the transport Claude Desktop launches)."""
    _configure_logging()
    mcp.run()


if __name__ == "__main__":
    main()
