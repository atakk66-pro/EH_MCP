"""FastMCP stdio server exposing read-only Employment Hero tools.

Every tool returns an allowlist model from models.py or a plain number, so no
personal data is serialized to the model (see docs/ALLOWLIST.md). Only read
tools are registered: there is no write tool for the model to call.

Tools are async wrappers around blocking HTTP work run in a worker thread —
FastMCP calls sync tools directly on the event loop, so a blocking call (worst
case: the 300-second OAuth sign-in) would otherwise freeze the whole server,
including protocol pings.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from collections.abc import Callable
from typing import TypeVar

import anyio
from mcp.server.fastmcp import FastMCP

from .auth import TokenManager, has_stored_token
from .client import EHClient
from .config import Settings, load_settings
from .errors import EHError
from .models import NamedEntity, Organisation, to_named, to_org
from .oauth_flow import OAuthFlowError, run_authorization_flow

logger = logging.getLogger("eh_mcp.tools")

mcp = FastMCP("employment-hero-readonly")

T = TypeVar("T")

# The client is built lazily on first use so the module imports (and `--help`,
# tests, etc.) work without credentials present.
_client: EHClient | None = None
_client_lock = threading.Lock()
# Guards against two concurrent sign-in flows fighting over the loopback port.
_connect_lock = threading.Lock()


def _get_client() -> EHClient:
    global _client
    with _client_lock:
        if _client is None:
            settings = load_settings()
            _client = EHClient(settings, TokenManager(settings))
        return _client


def _drop_client() -> None:
    """Close and discard the cached client (e.g. after a fresh sign-in)."""
    global _client
    with _client_lock:
        if _client is not None:
            _client.close()
            _client = None


def _resolve_org(settings: Settings, organisation_id: str | None) -> str:
    org = organisation_id or settings.org_id
    if not org:
        raise EHError(
            "No organisation specified. Pass organisation_id, or set the "
            "Organisation ID in the extension settings (EH_ORG_ID) so it is "
            "used automatically."
        )
    return org


async def _run(fn: Callable[[], T]) -> T:
    return await anyio.to_thread.run_sync(fn)


@mcp.tool()
async def connect_employment_hero(force_reconnect: bool = False) -> str:
    """Sign in to Employment Hero. Run this once before asking for any data.

    Opens the browser to approve read-only access. If a working connection
    already exists this does nothing; pass force_reconnect=true to sign in
    again deliberately.
    """
    logger.info("tool connect_employment_hero force=%s", force_reconnect)
    try:
        settings = load_settings()
    except RuntimeError as exc:
        return f"Cannot connect: {exc}"

    def go() -> str:
        if not _connect_lock.acquire(blocking=False):
            return (
                "A sign-in is already in progress. Finish it in the browser, "
                "then check connection_status."
            )
        try:
            if not force_reconnect and has_stored_token(settings.token_file):
                try:
                    TokenManager(settings).access_token()
                    return (
                        "Already connected to Employment Hero. Use "
                        "force_reconnect=true to sign in again."
                    )
                except Exception:
                    # Stored token is stale or revoked: fall through to a
                    # fresh browser sign-in.
                    logger.info("stored token unusable, starting fresh sign-in")
            try:
                run_authorization_flow(settings)
            except OAuthFlowError as exc:
                return f"Could not connect to Employment Hero: {exc}"
            _drop_client()
            return (
                "Connected to Employment Hero. You can now ask for teams, work "
                "locations, and headcount."
            )
        finally:
            _connect_lock.release()

    return await _run(go)


@mcp.tool()
async def connection_status() -> str:
    """Report whether this machine has a saved Employment Hero connection."""
    logger.info("tool connection_status")
    try:
        settings = load_settings()
    except RuntimeError as exc:
        return f"Not configured: {exc}"
    if has_stored_token(settings.token_file):
        return (
            "A connection to Employment Hero is saved on this machine. If data "
            "requests fail, ask me to connect Employment Hero again."
        )
    return (
        "Not connected to Employment Hero yet. Ask me to connect Employment "
        "Hero to sign in."
    )


@mcp.tool()
async def list_organisations() -> list[Organisation]:
    """List the Employment Hero organisations this integration can access.

    Returns only id and name. No personal data. If the API refuses this (the
    registered app has no organisations scope) but an Organisation ID is
    configured, that organisation is returned instead.
    """
    logger.info("tool list_organisations")

    def go() -> list[Organisation]:
        try:
            return [to_org(r) for r in _get_client().paginate("/api/v1/organisations")]
        except EHError:
            settings = load_settings()
            if settings.org_id:
                return [
                    Organisation(id=settings.org_id, name="Configured organisation")
                ]
            raise

    return await _run(go)


@mcp.tool()
async def list_teams(organisation_id: str | None = None) -> list[NamedEntity]:
    """List teams (shown as 'Groups' in the UI) in an organisation.

    Returns only each team's id and name. No personal data. Requires the
    teams:list scope. organisation_id defaults to the configured one.
    """
    logger.info("tool list_teams organisation_id=%s", organisation_id)

    def go() -> list[NamedEntity]:
        org = _resolve_org(load_settings(), organisation_id)
        path = f"/api/v1/organisations/{org}/teams"
        return [to_named(r) for r in _get_client().paginate(path)]

    return await _run(go)


@mcp.tool()
async def list_work_locations(organisation_id: str | None = None) -> list[NamedEntity]:
    """List work locations (the care homes / services) in an organisation.

    Returns only each location's id and name. No personal data. Requires the
    work_locations:list scope. organisation_id defaults to the configured one.
    """
    logger.info("tool list_work_locations organisation_id=%s", organisation_id)

    def go() -> list[NamedEntity]:
        org = _resolve_org(load_settings(), organisation_id)
        path = f"/api/v1/organisations/{org}/work_locations"
        return [to_named(r) for r in _get_client().paginate(path)]

    return await _run(go)


@mcp.tool()
async def employee_count(organisation_id: str | None = None) -> int:
    """Return the total number of employees in an organisation.

    A single aggregate integer. Reads only the pagination total; no individual
    employee record or field is returned. Requires the employees:list scope.
    organisation_id defaults to the configured one.
    """
    logger.info("tool employee_count organisation_id=%s", organisation_id)

    def go() -> int:
        org = _resolve_org(load_settings(), organisation_id)
        path = f"/api/v1/organisations/{org}/employees"
        return _get_client().total_items(path)

    return await _run(go)


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
