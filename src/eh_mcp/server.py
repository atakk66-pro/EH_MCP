"""FastMCP stdio server exposing read-only Employment Hero tools.

Every tool returns an allowlist model from models.py, so no personal data is
serialized to the model. Only read tools are registered: there is no write tool
for the model to call.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .auth import TokenManager
from .client import EHClient
from .config import load_settings
from .models import NamedEntity, Organisation, to_named, to_org

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
def list_organisations() -> list[Organisation]:
    """List the Employment Hero organisations this integration can access.

    Returns only id and name. No personal data.
    """
    client = _get_client()
    return [to_org(r) for r in client.paginate("/api/v1/organisations")]


@mcp.tool()
def list_teams(organisation_id: str) -> list[NamedEntity]:
    """List teams (shown as 'Groups' in the UI) in an organisation.

    Returns only each team's id and name. No personal data.
    """
    client = _get_client()
    path = f"/api/v1/organisations/{organisation_id}/teams"
    return [to_named(r) for r in client.paginate(path)]


@mcp.tool()
def list_departments(organisation_id: str) -> list[NamedEntity]:
    """List departments in an organisation.

    Returns only each department's id and name. No personal data.
    """
    client = _get_client()
    path = f"/api/v1/organisations/{organisation_id}/departments"
    return [to_named(r) for r in client.paginate(path)]


@mcp.tool()
def list_work_locations(organisation_id: str) -> list[NamedEntity]:
    """List work locations in an organisation.

    Returns only each location's id and name. No personal data.
    """
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
    client = _get_client()
    path = f"/api/v1/organisations/{organisation_id}/employees"
    return client.total_items(path)


def main() -> None:
    """Run the server over stdio (the transport Claude Desktop launches)."""
    mcp.run()


if __name__ == "__main__":
    main()
