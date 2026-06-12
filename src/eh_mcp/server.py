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
import urllib.parse
import webbrowser
from collections.abc import Callable
from datetime import date
from typing import TypeVar

import anyio
from mcp.server.fastmcp import FastMCP

from . import kpi
from .auth import TokenManager, has_stored_token
from .client import EHClient
from .config import Settings, load_settings
from .dates import add_days, parse_date
from .errors import EHError
from .kpi_config import KpiConfig, KpiConfigError, load_kpi_config
from .models import (
    AbsenceRow,
    BradfordRow,
    ComplianceRow,
    CountRow,
    NamedEntity,
    Organisation,
    RateRow,
    RetentionRow,
    TenureBandsRow,
    TurnoverRow,
    to_named,
    to_org,
)
from .oauth_flow import (
    OAuthFlowError,
    build_authorize_url,
    exchange_code_for_refresh_token,
)
from .schema import type_skeleton

logger = logging.getLogger("eh_mcp.tools")

mcp = FastMCP("employment-hero-readonly")

T = TypeVar("T")

# The client is built lazily on first use so the module imports (and `--help`,
# tests, etc.) work without credentials present.
_client: EHClient | None = None
_client_lock = threading.Lock()


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


def _token_works(settings: Settings) -> bool:
    try:
        TokenManager(settings).access_token()
        return True
    except Exception:
        return False


def _open_browser_async(url: str) -> None:
    """Best-effort browser launch off the tool call. If it fails, the user still
    has the URL in the connect response."""

    def go() -> None:
        try:
            webbrowser.open(url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not open browser: %s", exc)

    threading.Thread(target=go, daemon=True).start()


def _extract_code_and_state(text: str) -> tuple[str | None, str | None]:
    """Pull the code (and state) out of a pasted redirect URL, query string, or
    a bare code."""
    text = (text or "").strip().strip("<>\"'")
    query = ""
    if "://" in text:
        query = urllib.parse.urlparse(text).query
    elif "code=" in text:
        query = text.lstrip("?")
    if query:
        params = urllib.parse.parse_qs(query)
        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]
        if code:
            return code, state
    return (text or None), None


@mcp.tool()
async def connect_employment_hero(force_reconnect: bool = False) -> str:
    """Begin Employment Hero sign-in (no local server — works on locked-down
    networks). Returns a link to approve access; after approving, paste the
    address your browser lands on back to me using complete_employment_hero_signin.
    Does nothing if already connected, unless force_reconnect is true.
    """
    logger.info("tool connect_employment_hero force=%s", force_reconnect)
    try:
        settings = load_settings()
    except RuntimeError as exc:
        return f"Cannot connect: {exc}"

    if not force_reconnect and has_stored_token(settings.token_file):
        if await _run(lambda: _token_works(settings)):
            return "Already connected to Employment Hero."

    # EH's authorize endpoint accepts only client_id, redirect_uri,
    # response_type (per the official Postman collection); any extra parameter
    # (scope, state) is rejected with a 403.
    url = build_authorize_url(settings)
    _open_browser_async(url)
    return (
        "To connect Employment Hero:\n\n"
        "1. Open this link (it may also open by itself), sign in as an "
        f"administrator, and approve access:\n{url}\n\n"
        "2. After you approve, the browser will try to open a 127.0.0.1 page "
        'that fails to load ("can\'t reach this site"). That is expected and '
        "fine.\n\n"
        "3. Copy the FULL web address from that failed page's address bar (it "
        "contains 'code=') and paste it back to me: complete the Employment "
        "Hero sign-in with <that address>."
    )


@mcp.tool()
async def complete_employment_hero_signin(redirect_url_or_code: str) -> str:
    """Finish sign-in using the address (or code) from the page the browser
    landed on after you approved access in Employment Hero."""
    logger.info("tool complete_employment_hero_signin")
    try:
        settings = load_settings()
    except RuntimeError as exc:
        return f"Cannot connect: {exc}"

    code, _state = _extract_code_and_state(redirect_url_or_code)
    if not code:
        return (
            "I couldn't find a sign-in code in that. Paste the full web address "
            "from the page your browser landed on (it contains 'code=')."
        )

    def go() -> str:
        try:
            exchange_code_for_refresh_token(settings, code)
        except OAuthFlowError as exc:
            return f"Sign-in failed: {exc}"
        _drop_client()
        return (
            "Connected to Employment Hero. You can now ask for teams, work "
            "locations, and headcount."
        )

    return await _run(go)


@mcp.tool()
async def connection_status() -> str:
    """Report whether this machine is signed in to Employment Hero."""
    logger.info("tool connection_status")
    try:
        settings = load_settings()
    except RuntimeError as exc:
        return f"Not configured: {exc}"
    if has_stored_token(settings.token_file):
        if await _run(lambda: _token_works(settings)):
            return "Connected to Employment Hero."
        return (
            "A saved connection exists but is not working. Ask me to connect "
            "Employment Hero again."
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


# -- developer schema probe (off unless EH_DEBUG_SCHEMA is set) -----------

_SCHEMA_ENDPOINTS = {
    "organisations": "/api/v1/organisations",
    "teams": "/api/v1/organisations/{org}/teams",
    "work_locations": "/api/v1/organisations/{org}/work_locations",
    "cost_centres": "/api/v1/organisations/{org}/cost_centres",
    "work_sites": "/api/v1/organisations/{org}/work_sites",
    "work_types": "/api/v1/organisations/{org}/work_types",
    "employing_entities": "/api/v1/organisations/{org}/employing_entities",
    "employees": "/api/v1/organisations/{org}/employees",
    "leave_requests": "/api/v1/organisations/{org}/leave_requests",
    "leave_categories": "/api/v1/organisations/{org}/leave_categories",
    "pay_categories": "/api/v1/organisations/{org}/pay_categories",
    "rostered_shifts": "/api/v1/organisations/{org}/rostered_shifts",
}


async def verify_api_schema(
    resource: str, organisation_id: str | None = None
) -> dict:
    """[Developer setup] Report the STRUCTURE of one Employment Hero list
    endpoint: field names and value types only, never any values, so no
    personal data is returned. Use this once after connecting to confirm the
    live API shape. resource must be one of the configured endpoint names;
    organisation_id defaults to the configured one.
    """
    logger.info("tool verify_api_schema resource=%s org=%s", resource, organisation_id)
    if resource not in _SCHEMA_ENDPOINTS:
        return {
            "error": f"Unknown resource '{resource}'.",
            "choices": sorted(_SCHEMA_ENDPOINTS),
        }

    def go() -> dict:
        try:
            settings = load_settings()
            template = _SCHEMA_ENDPOINTS[resource]
            if "{org}" in template:
                template = template.format(org=_resolve_org(settings, organisation_id))
            payload = _get_client().sample(template)
            return {"resource": resource, "ok": True, "schema": type_skeleton(payload)}
        except (EHError, RuntimeError) as exc:
            return {"resource": resource, "ok": False, "error": str(exc)}

    return await _run(go)


def _debug_schema_enabled() -> bool:
    return str(os.environ.get("EH_DEBUG_SCHEMA", "")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


if _debug_schema_enabled():
    mcp.tool()(verify_api_schema)


# -- KPI tools -----------------------------------------------------------


def _load_kpi() -> KpiConfig:
    # If no config file exists, fall back to safe defaults. Headcount-based KPIs
    # (turnover, retention, tenure, probation) work out of the box; the
    # sickness/training KPIs need the category and certificate lists, so they
    # return zeros until kpi_config.yaml supplies them.
    try:
        return load_kpi_config()
    except KpiConfigError:
        logger.info("no KPI config found; using defaults (work_location grouping)")
        return KpiConfig(service_grouping="work_location")


def _parse_period(period_start: str | None, period_end: str | None) -> tuple[date, date]:
    end = parse_date(period_end) or date.today()
    start = parse_date(period_start) or add_days(end, -365)
    if start > end:
        raise EHError("period_start is after period_end.")
    return start, end


def _employees(org: str) -> list[dict]:
    # No member_type filter: terminated employees carry termination_date and are
    # needed for turnover/retention.
    return list(_get_client().paginate(f"/api/v1/organisations/{org}/employees"))


def _leave_requests(org: str, start: date, end: date) -> list[dict]:
    return list(
        _get_client().paginate(
            f"/api/v1/organisations/{org}/leave_requests",
            params={"start_date": start.isoformat(), "end_date": end.isoformat()},
        )
    )


def _leave_categories(org: str) -> list[dict]:
    return list(_get_client().paginate(f"/api/v1/organisations/{org}/leave_categories"))


@mcp.tool()
async def staff_turnover(
    organisation_id: str | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
) -> list[TurnoverRow]:
    """Staff turnover per service: leavers in the period over average headcount.

    Dates are YYYY-MM-DD; default is the trailing 12 months. Returns one row per
    service plus an "All services" total. Aggregates only — no per-person data.
    """
    logger.info("tool staff_turnover org=%s", organisation_id)

    def go() -> list[TurnoverRow]:
        org = _resolve_org(load_settings(), organisation_id)
        start, end = _parse_period(period_start, period_end)
        return kpi.turnover(_employees(org), _load_kpi(), start, end)

    return await _run(go)


@mcp.tool()
async def staff_retention(
    organisation_id: str | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
) -> list[RetentionRow]:
    """Staff retention per service: of those employed at the start of the period,
    the share still employed at the end. Dates YYYY-MM-DD, default trailing 12
    months. Aggregates only.
    """
    logger.info("tool staff_retention org=%s", organisation_id)

    def go() -> list[RetentionRow]:
        org = _resolve_org(load_settings(), organisation_id)
        start, end = _parse_period(period_start, period_end)
        return kpi.retention(_employees(org), _load_kpi(), start, end)

    return await _run(go)


@mcp.tool()
async def leavers_by_length_of_service(
    organisation_id: str | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
) -> list[TenureBandsRow]:
    """Leavers in the period bucketed by length of service (<3m, 3-6m, 6-12m,
    1-2y, 2y+), per service. Dates YYYY-MM-DD, default trailing 12 months.
    """
    logger.info("tool leavers_by_length_of_service org=%s", organisation_id)

    def go() -> list[TenureBandsRow]:
        org = _resolve_org(load_settings(), organisation_id)
        start, end = _parse_period(period_start, period_end)
        return kpi.leavers_by_length_of_service(_employees(org), _load_kpi(), start, end)

    return await _run(go)


@mcp.tool()
async def early_attrition(
    organisation_id: str | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
) -> list[RateRow]:
    """Early attrition per service: of leavers in the period, the share whose
    tenure was within the early-leaver window (set in the KPI config, default
    180 days). Dates YYYY-MM-DD, default trailing 12 months.
    """
    logger.info("tool early_attrition org=%s", organisation_id)

    def go() -> list[RateRow]:
        org = _resolve_org(load_settings(), organisation_id)
        start, end = _parse_period(period_start, period_end)
        return kpi.early_attrition(_employees(org), _load_kpi(), start, end)

    return await _run(go)


@mcp.tool()
async def starters_on_probation(
    organisation_id: str | None = None, as_of: str | None = None
) -> list[CountRow]:
    """Count of active employees currently within their probation/trial period,
    per service. as_of is YYYY-MM-DD (default today).
    """
    logger.info("tool starters_on_probation org=%s", organisation_id)

    def go() -> list[CountRow]:
        org = _resolve_org(load_settings(), organisation_id)
        ref = parse_date(as_of) or date.today()
        return kpi.starters_on_probation(_employees(org), _load_kpi(), ref)

    return await _run(go)


@mcp.tool()
async def absence_summary(
    organisation_id: str | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
) -> list[AbsenceRow]:
    """Sickness absence per service: total sick hours/days and a count of
    long-term-absence spells (the threshold is in the KPI config, default 28
    days). Sick leave is identified by the configured sickness categories. Dates
    YYYY-MM-DD, default trailing 12 months. Aggregates only.
    """
    logger.info("tool absence_summary org=%s", organisation_id)

    def go() -> list[AbsenceRow]:
        org = _resolve_org(load_settings(), organisation_id)
        start, end = _parse_period(period_start, period_end)
        config = _load_kpi()
        return kpi.absence_summary(
            _employees(org),
            _leave_requests(org, start, end),
            _leave_categories(org),
            config,
        )

    return await _run(go)


@mcp.tool()
async def bradford_hotspots(
    organisation_id: str | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
) -> list[BradfordRow]:
    """Bradford Factor absence hotspots per service: mean and max Bradford score
    and the count of employees over the trigger threshold (100). Per-person
    scores are never returned. Dates YYYY-MM-DD, default trailing 12 months.
    """
    logger.info("tool bradford_hotspots org=%s", organisation_id)

    def go() -> list[BradfordRow]:
        org = _resolve_org(load_settings(), organisation_id)
        start, end = _parse_period(period_start, period_end)
        config = _load_kpi()
        return kpi.bradford_hotspots(
            _employees(org),
            _leave_requests(org, start, end),
            _leave_categories(org),
            config,
        )

    return await _run(go)


@mcp.tool()
async def training_compliance(
    cert_set: str = "mandatory",
    organisation_id: str | None = None,
    as_of: str | None = None,
) -> list[ComplianceRow]:
    """Training/certification compliance per service: the share of active
    employees holding every required certificate in the set, plus a count
    expiring soon. cert_set is 'mandatory' or 'safety' (the required names come
    from the KPI config). as_of is YYYY-MM-DD (default today).

    Note: certifications are read per employee, so this iterates the whole
    employee list and can be slow for large organisations.
    """
    logger.info("tool training_compliance set=%s org=%s", cert_set, organisation_id)
    if cert_set not in ("mandatory", "safety"):
        raise EHError("cert_set must be 'mandatory' or 'safety'.")

    def go() -> list[ComplianceRow]:
        org = _resolve_org(load_settings(), organisation_id)
        ref = parse_date(as_of) or date.today()
        client = _get_client()
        employees = _employees(org)
        pairs: list[tuple[dict, list[dict]]] = []
        for emp in employees:
            emp_id = emp.get("id")
            if not emp_id:
                continue
            certs = list(
                client.paginate(
                    f"/api/v1/organisations/{org}/employees/{emp_id}/certifications"
                )
            )
            pairs.append((emp, certs))
        return kpi.training_compliance(pairs, _load_kpi(), cert_set, ref)

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
