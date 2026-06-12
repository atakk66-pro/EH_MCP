"""Pure KPI computations.

Each function takes already-fetched raw records plus the directors' KpiConfig
and returns a list of allowlist result models (per service, plus an org-total
row). No I/O here, so every function is unit-testable with synthetic data, and
no per-person value is ever placed in a result.

Field names follow the confirmed Employment Hero schema (see docs/ALLOWLIST.md):
employees carry id, start_date, termination_date, status, trial_or_probation_type,
trial_length (days), probation_length (months), teams[], primary_cost_centre,
and a legacy work-location reference. Records that cannot be parsed are skipped
rather than crashing the aggregate.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Callable

from .dates import add_days, add_months, days_between, parse_date
from .kpi_config import KpiConfig
from .models import (
    AbsenceRow,
    BradfordRow,
    ComplianceRow,
    CountRow,
    RateRow,
    RetentionRow,
    TenureBandsRow,
    TurnoverRow,
)

ORG_TOTAL_ID = "__all__"
ORG_TOTAL_NAME = "All services"
UNASSIGNED = ("__unassigned__", "Unassigned")

# Tenure bands for leavers-by-length-of-service (upper bound in days, inclusive).
_TENURE_BANDS = [
    ("<3m", 90),
    ("3-6m", 182),
    ("6-12m", 365),
    ("1-2y", 730),
    ("2y+", None),
]


def service_key(emp: dict, grouping: str) -> tuple[str, str]:
    """Return (id, name) of the service an employee belongs to, by grouping.

    An employee is counted under one service (the primary one) so headcounts
    stay sane. Unresolvable membership falls into an 'Unassigned' bucket so the
    org total is still complete.
    """
    if grouping == "team":
        teams = emp.get("teams") or []
        if teams and isinstance(teams[0], dict) and teams[0].get("id"):
            t = teams[0]
            return str(t["id"]), str(t.get("name") or "Unknown")
    elif grouping == "cost_centre":
        cc = emp.get("primary_cost_centre")
        if isinstance(cc, dict) and cc.get("id"):
            return str(cc["id"]), str(cc.get("name") or "Unknown")
    elif grouping == "work_location":
        # Prefer a structured work_location; fall back to the legacy string.
        for field in ("work_location", "primary_work_location"):
            wl = emp.get(field)
            if isinstance(wl, dict) and wl.get("id"):
                return str(wl["id"]), str(wl.get("name") or "Unknown")
        loc = emp.get("location")
        if isinstance(loc, str) and loc.strip():
            return loc.strip(), loc.strip()
    return UNASSIGNED


def _active_at(emp: dict, on: date) -> bool:
    start = parse_date(emp.get("start_date"))
    if start is None or start > on:
        return False
    term = parse_date(emp.get("termination_date"))
    return term is None or term > on


def _round(x: float, n: int = 1) -> float:
    return round(x, n)


def _finalise(
    rows: list, totals: dict, build_total: Callable[[dict], Any]
) -> list:
    """Sort per-service rows by name and append the org-total row last."""
    rows.sort(key=lambda r: r.service_name.lower())
    rows.append(build_total(totals))
    return rows


# -- employee-based KPIs -------------------------------------------------


def turnover(
    employees: list[dict], config: KpiConfig, period_start: date, period_end: date
) -> list[TurnoverRow]:
    g: dict[tuple, dict] = defaultdict(lambda: {"leavers": 0, "hc_start": 0, "hc_end": 0})
    for emp in employees:
        key = service_key(emp, config.service_grouping)
        bucket = g[key]
        if _active_at(emp, period_start):
            bucket["hc_start"] += 1
        if _active_at(emp, period_end):
            bucket["hc_end"] += 1
        term = parse_date(emp.get("termination_date"))
        if term and period_start <= term <= period_end:
            bucket["leavers"] += 1

    def row(sid: str, sname: str, b: dict) -> TurnoverRow:
        avg = (b["hc_start"] + b["hc_end"]) / 2
        rate = (b["leavers"] / avg * 100) if avg > 0 else 0.0
        return TurnoverRow(
            service_id=sid,
            service_name=sname,
            leavers=b["leavers"],
            average_headcount=_round(avg),
            turnover_rate_pct=_round(rate),
        )

    totals = {"leavers": 0, "hc_start": 0, "hc_end": 0}
    rows = []
    for (sid, sname), b in g.items():
        rows.append(row(sid, sname, b))
        for k in totals:
            totals[k] += b[k]
    return _finalise(rows, totals, lambda t: row(ORG_TOTAL_ID, ORG_TOTAL_NAME, t))


def retention(
    employees: list[dict], config: KpiConfig, period_start: date, period_end: date
) -> list[RetentionRow]:
    """Stayer-based: of those employed at period start, share still active at
    period end."""
    g: dict[tuple, dict] = defaultdict(lambda: {"start": 0, "retained": 0})
    for emp in employees:
        if not _active_at(emp, period_start):
            continue
        key = service_key(emp, config.service_grouping)
        g[key]["start"] += 1
        if _active_at(emp, period_end):
            g[key]["retained"] += 1

    def row(sid: str, sname: str, b: dict) -> RetentionRow:
        rate = (b["retained"] / b["start"] * 100) if b["start"] > 0 else 0.0
        return RetentionRow(
            service_id=sid,
            service_name=sname,
            starting_headcount=b["start"],
            retained=b["retained"],
            retention_rate_pct=_round(rate),
        )

    totals = {"start": 0, "retained": 0}
    rows = []
    for (sid, sname), b in g.items():
        rows.append(row(sid, sname, b))
        for k in totals:
            totals[k] += b[k]
    return _finalise(rows, totals, lambda t: row(ORG_TOTAL_ID, ORG_TOTAL_NAME, t))


def _leaver_tenures(
    employees: list[dict], grouping: str, period_start: date, period_end: date
):
    """Yield (service_key, tenure_days) for each leaver terminated in period."""
    for emp in employees:
        term = parse_date(emp.get("termination_date"))
        start = parse_date(emp.get("start_date"))
        if term is None or start is None:
            continue
        if not (period_start <= term <= period_end):
            continue
        yield service_key(emp, grouping), max(0, days_between(start, term))


def leavers_by_length_of_service(
    employees: list[dict], config: KpiConfig, period_start: date, period_end: date
) -> list[TenureBandsRow]:
    def empty_bands() -> dict[str, int]:
        return {name: 0 for name, _ in _TENURE_BANDS}

    g: dict[tuple, dict[str, int]] = defaultdict(empty_bands)
    for key, tenure in _leaver_tenures(
        employees, config.service_grouping, period_start, period_end
    ):
        for name, upper in _TENURE_BANDS:
            if upper is None or tenure < upper:
                g[key][name] += 1
                break

    def row(sid: str, sname: str, bands: dict[str, int]) -> TenureBandsRow:
        return TenureBandsRow(
            service_id=sid,
            service_name=sname,
            leavers=sum(bands.values()),
            bands=dict(bands),
        )

    totals = empty_bands()
    rows = []
    for (sid, sname), bands in g.items():
        rows.append(row(sid, sname, bands))
        for name in totals:
            totals[name] += bands[name]
    return _finalise(rows, totals, lambda t: row(ORG_TOTAL_ID, ORG_TOTAL_NAME, t))


def early_attrition(
    employees: list[dict], config: KpiConfig, period_start: date, period_end: date
) -> list[RateRow]:
    """Leavers whose tenure was at or below the early-attrition window, over all
    leavers in the period."""
    window = config.thresholds.early_attrition_window_days
    g: dict[tuple, dict] = defaultdict(lambda: {"early": 0, "leavers": 0})
    for key, tenure in _leaver_tenures(
        employees, config.service_grouping, period_start, period_end
    ):
        g[key]["leavers"] += 1
        if tenure <= window:
            g[key]["early"] += 1

    def row(sid: str, sname: str, b: dict) -> RateRow:
        rate = (b["early"] / b["leavers"] * 100) if b["leavers"] > 0 else 0.0
        return RateRow(
            service_id=sid,
            service_name=sname,
            count=b["early"],
            denominator=b["leavers"],
            rate_pct=_round(rate),
        )

    totals = {"early": 0, "leavers": 0}
    rows = []
    for (sid, sname), b in g.items():
        rows.append(row(sid, sname, b))
        for k in totals:
            totals[k] += b[k]
    return _finalise(rows, totals, lambda t: row(ORG_TOTAL_ID, ORG_TOTAL_NAME, t))


def _probation_end(emp: dict) -> date | None:
    start = parse_date(emp.get("start_date"))
    if start is None:
        return None
    ptype = emp.get("trial_or_probation_type")
    if ptype == "trial_period" and emp.get("trial_length"):
        try:
            return date.fromordinal(start.toordinal() + int(emp["trial_length"]))
        except (TypeError, ValueError):
            return None
    if emp.get("probation_length"):
        try:
            return add_months(start, int(emp["probation_length"]))
        except (TypeError, ValueError):
            return None
    return None


def starters_on_probation(
    employees: list[dict], config: KpiConfig, as_of: date
) -> list[CountRow]:
    g: dict[tuple, int] = defaultdict(int)
    for emp in employees:
        if not _active_at(emp, as_of):
            continue
        end = _probation_end(emp)
        if end is not None and end >= as_of:
            g[service_key(emp, config.service_grouping)] += 1

    def row(sid: str, sname: str, count: int) -> CountRow:
        return CountRow(service_id=sid, service_name=sname, count=count)

    total = 0
    rows = []
    for (sid, sname), count in g.items():
        rows.append(row(sid, sname, count))
        total += count
    rows.sort(key=lambda r: r.service_name.lower())
    rows.append(row(ORG_TOTAL_ID, ORG_TOTAL_NAME, total))
    return rows


# -- leave-based KPIs ----------------------------------------------------


def _employee_service_map(employees: list[dict], grouping: str) -> dict[str, tuple]:
    return {str(emp.get("id")): service_key(emp, grouping) for emp in employees if emp.get("id")}


def _sick_category_ids(leave_categories: list[dict], config: KpiConfig) -> set[str]:
    wanted = {c.strip().lower() for c in config.sickness_categories}
    ids = set()
    for cat in leave_categories:
        name = str(cat.get("name", "")).strip().lower()
        ltype = str(cat.get("leave_type", "")).strip().lower()
        if name in wanted or (ltype and ltype in wanted):
            cid = cat.get("id")
            if cid:
                ids.add(str(cid))
    return ids


def _request_hours(req: dict) -> float:
    hpd = req.get("hours_per_day")
    if isinstance(hpd, list):
        return sum(
            float(d.get("hours", 0) or 0) for d in hpd if isinstance(d, dict)
        )
    try:
        return float(req.get("total_hours", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def absence_summary(
    employees: list[dict],
    leave_requests: list[dict],
    leave_categories: list[dict],
    config: KpiConfig,
) -> list[AbsenceRow]:
    svc = _employee_service_map(employees, config.service_grouping)
    sick_ids = _sick_category_ids(leave_categories, config)
    lta_days = config.thresholds.long_term_absence_days
    g: dict[tuple, dict] = defaultdict(lambda: {"hours": 0.0, "days": 0, "lta": 0})

    for req in leave_requests:
        if sick_ids and str(req.get("leave_category_id", "")) not in sick_ids:
            continue
        key = svc.get(str(req.get("employee_id")), UNASSIGNED)
        bucket = g[key]
        bucket["hours"] += _request_hours(req)
        start = parse_date(req.get("start_date"))
        end = parse_date(req.get("end_date"))
        if start and end:
            span = days_between(start, end) + 1
            bucket["days"] += span
            if span >= lta_days:
                bucket["lta"] += 1

    def row(sid: str, sname: str, b: dict) -> AbsenceRow:
        return AbsenceRow(
            service_id=sid,
            service_name=sname,
            sick_hours=_round(b["hours"]),
            sick_days=int(b["days"]),
            long_term_absence_cases=b["lta"],
        )

    totals = {"hours": 0.0, "days": 0, "lta": 0}
    rows = []
    for (sid, sname), b in g.items():
        rows.append(row(sid, sname, b))
        for k in totals:
            totals[k] += b[k]
    return _finalise(rows, totals, lambda t: row(ORG_TOTAL_ID, ORG_TOTAL_NAME, t))


def bradford_hotspots(
    employees: list[dict],
    leave_requests: list[dict],
    leave_categories: list[dict],
    config: KpiConfig,
) -> list[BradfordRow]:
    """Bradford Factor B = S^2 * D per employee (S spells, D days), aggregated to
    service level. Per-person scores never leave this function."""
    svc = _employee_service_map(employees, config.service_grouping)
    sick_ids = _sick_category_ids(leave_categories, config)

    # Per-employee spell count and day total.
    per_emp: dict[str, dict] = defaultdict(lambda: {"spells": 0, "days": 0})
    for req in leave_requests:
        if sick_ids and str(req.get("leave_category_id", "")) not in sick_ids:
            continue
        eid = str(req.get("employee_id"))
        start = parse_date(req.get("start_date"))
        end = parse_date(req.get("end_date"))
        if not eid or start is None or end is None:
            continue
        per_emp[eid]["spells"] += 1
        per_emp[eid]["days"] += days_between(start, end) + 1

    threshold = 100  # common Bradford trigger point
    g: dict[tuple, list[int]] = defaultdict(list)
    for eid, v in per_emp.items():
        score = v["spells"] * v["spells"] * v["days"]
        g[svc.get(eid, UNASSIGNED)].append(score)

    def row(sid: str, sname: str, scores: list[int]) -> BradfordRow:
        return BradfordRow(
            service_id=sid,
            service_name=sname,
            employees_with_absence=len(scores),
            mean_bradford=_round(sum(scores) / len(scores)) if scores else 0.0,
            max_bradford=max(scores) if scores else 0,
            over_threshold=sum(1 for s in scores if s >= threshold),
        )

    all_scores: list[int] = []
    rows = []
    for (sid, sname), scores in g.items():
        rows.append(row(sid, sname, scores))
        all_scores.extend(scores)
    rows.sort(key=lambda r: r.service_name.lower())
    rows.append(row(ORG_TOTAL_ID, ORG_TOTAL_NAME, all_scores))
    return rows


# -- certification-based KPI ---------------------------------------------


def _cert_valid(cert: dict, as_of: date) -> bool:
    status = str(cert.get("status", "")).strip().lower()
    if status in ("expired", "revoked", "incomplete", "pending"):
        return False
    expiry = parse_date(cert.get("expiry_date"))
    if expiry is not None and expiry < as_of:
        return False
    return True


def training_compliance(
    employees_with_certs: list[tuple[dict, list[dict]]],
    config: KpiConfig,
    cert_set: str,
    as_of: date,
) -> list[ComplianceRow]:
    """cert_set is 'mandatory' or 'safety'. An employee is compliant if they hold
    a currently-valid cert for every required cert name in that set."""
    required = (
        config.mandatory_cert_names
        if cert_set == "mandatory"
        else config.safety_cert_names
    )
    required_lower = {r.strip().lower() for r in required}
    warn_days = config.thresholds.cert_expiry_warning_days

    g: dict[tuple, dict] = defaultdict(lambda: {"compliant": 0, "total": 0, "expiring": 0})
    for emp, certs in employees_with_certs:
        if not _active_at(emp, as_of):
            continue
        key = service_key(emp, config.service_grouping)
        bucket = g[key]
        bucket["total"] += 1
        held_valid = {
            str(c.get("name", "")).strip().lower()
            for c in certs
            if _cert_valid(c, as_of)
        }
        if required_lower and required_lower.issubset(held_valid):
            bucket["compliant"] += 1
        for c in certs:
            if str(c.get("name", "")).strip().lower() not in required_lower:
                continue
            expiry = parse_date(c.get("expiry_date"))
            if expiry is not None and as_of <= expiry <= add_days(as_of, warn_days):
                bucket["expiring"] += 1

    def row(sid: str, sname: str, b: dict) -> ComplianceRow:
        rate = (b["compliant"] / b["total"] * 100) if b["total"] > 0 else 0.0
        return ComplianceRow(
            service_id=sid,
            service_name=sname,
            cert_set=cert_set,
            compliant_employees=b["compliant"],
            total_employees=b["total"],
            compliance_rate_pct=_round(rate),
            expiring_soon=b["expiring"],
        )

    totals = {"compliant": 0, "total": 0, "expiring": 0}
    rows = []
    for (sid, sname), b in g.items():
        rows.append(row(sid, sname, b))
        for k in totals:
            totals[k] += b[k]
    return _finalise(rows, totals, lambda t: row(ORG_TOTAL_ID, ORG_TOTAL_NAME, t))
