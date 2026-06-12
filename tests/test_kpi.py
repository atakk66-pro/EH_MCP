"""Unit tests for the pure KPI computations, with synthetic records.

These verify the maths and, importantly, that no per-person value appears in any
result and that the org-total row is always present and correct.
"""

from datetime import date

from eh_mcp import kpi
from eh_mcp.kpi_config import KpiConfig, Thresholds


def cfg(grouping="work_location", **kw):
    return KpiConfig(
        service_grouping=grouping,
        sickness_categories=kw.get("sickness", ("Sick Leave",)),
        mandatory_cert_names=kw.get("mandatory", ("Safeguarding",)),
        safety_cert_names=kw.get("safety", ("Fire Safety",)),
        thresholds=kw.get("thresholds", Thresholds()),
    )


def emp(id, start, term=None, loc="Oak House", **extra):
    e = {"id": id, "start_date": start, "termination_date": term, "location": loc}
    e.update(extra)
    return e


def total_row(rows):
    return next(r for r in rows if r.service_id == kpi.ORG_TOTAL_ID)


def svc_rows(rows):
    return [r for r in rows if r.service_id != kpi.ORG_TOTAL_ID]


# -- turnover ------------------------------------------------------------


def test_turnover_basic():
    ps, pe = date(2025, 1, 1), date(2025, 12, 31)
    employees = [
        emp("1", "2020-01-01"),  # active throughout
        emp("2", "2020-01-01", "2025-06-30"),  # leaver in period
        emp("3", "2024-01-01"),  # active throughout
        emp("4", "2026-01-01"),  # starts after period: not counted at start/end
    ]
    rows = kpi.turnover(employees, cfg(), ps, pe)
    t = total_row(rows)
    assert t.leavers == 1
    # headcount at start: ids 1,2,3 = 3; at end: 1,3 = 2; avg = 2.5
    assert t.average_headcount == 2.5
    assert t.turnover_rate_pct == 40.0  # 1 / 2.5 * 100


def test_turnover_groups_by_service_and_totals():
    ps, pe = date(2025, 1, 1), date(2025, 12, 31)
    employees = [
        emp("1", "2020-01-01", "2025-03-01", loc="Oak House"),
        emp("2", "2020-01-01", loc="Oak House"),
        emp("3", "2020-01-01", "2025-09-01", loc="Elm House"),
    ]
    rows = kpi.turnover(employees, cfg(), ps, pe)
    by_name = {r.service_name: r for r in rows}
    assert by_name["Oak House"].leavers == 1
    assert by_name["Elm House"].leavers == 1
    assert total_row(rows).leavers == 2


# -- retention -----------------------------------------------------------


def test_retention_stayer_based():
    ps, pe = date(2025, 1, 1), date(2025, 12, 31)
    employees = [
        emp("1", "2020-01-01"),  # stays
        emp("2", "2020-01-01", "2025-06-01"),  # leaves
        emp("3", "2025-07-01"),  # joined mid-period: not in starting headcount
    ]
    t = total_row(kpi.retention(employees, cfg(), ps, pe))
    assert t.starting_headcount == 2
    assert t.retained == 1
    assert t.retention_rate_pct == 50.0


# -- tenure bands --------------------------------------------------------


def test_leavers_by_length_of_service_bands():
    ps, pe = date(2025, 1, 1), date(2025, 12, 31)
    employees = [
        emp("1", "2025-01-01", "2025-02-01"),  # ~31 days -> <3m
        emp("2", "2024-01-01", "2025-03-01"),  # ~14 months -> 1-2y
        emp("3", "2018-01-01", "2025-03-01"),  # 7y -> 2y+
    ]
    t = total_row(kpi.leavers_by_length_of_service(employees, cfg(), ps, pe))
    assert t.leavers == 3
    assert t.bands["<3m"] == 1
    assert t.bands["1-2y"] == 1
    assert t.bands["2y+"] == 1


# -- early attrition -----------------------------------------------------


def test_early_attrition_window():
    ps, pe = date(2025, 1, 1), date(2025, 12, 31)
    employees = [
        emp("1", "2025-01-01", "2025-03-01"),  # ~59d <= 180 -> early
        emp("2", "2020-01-01", "2025-03-01"),  # long tenure -> not early
    ]
    t = total_row(kpi.early_attrition(employees, cfg(), ps, pe))
    assert t.count == 1
    assert t.denominator == 2
    assert t.rate_pct == 50.0


# -- probation -----------------------------------------------------------


def test_starters_on_probation():
    as_of = date(2025, 6, 1)
    employees = [
        emp("1", "2025-05-01", probation_length=6),  # within 6 months
        emp("2", "2024-01-01", probation_length=6),  # probation long over
        emp("3", "2025-05-20", trial_or_probation_type="trial_period", trial_length=90),
        emp("4", "2025-05-01", "2025-05-15", probation_length=6),  # terminated
    ]
    t = total_row(kpi.starters_on_probation(employees, cfg(), as_of))
    assert t.count == 2  # ids 1 and 3


# -- absence + bradford --------------------------------------------------


def leave(emp_id, cat_id, start, end, hours=None):
    r = {
        "employee_id": emp_id,
        "leave_category_id": cat_id,
        "start_date": start,
        "end_date": end,
    }
    if hours is not None:
        r["hours_per_day"] = [{"date": start, "hours": hours}]
    return r


def test_absence_summary_filters_sick_and_counts_lta():
    employees = [emp("1", "2020-01-01", loc="Oak House")]
    cats = [
        {"id": "sick", "name": "Sick Leave", "leave_type": "sick"},
        {"id": "annual", "name": "Annual Leave", "leave_type": "annual"},
    ]
    requests = [
        leave("1", "sick", "2025-03-01", "2025-03-30", hours=8),  # 30 days >= 28 -> LTA
        leave("1", "sick", "2025-05-01", "2025-05-02", hours=8),  # short
        leave("1", "annual", "2025-06-01", "2025-06-10", hours=8),  # ignored
    ]
    t = total_row(kpi.absence_summary(employees, requests, cats, cfg()))
    assert t.long_term_absence_cases == 1
    assert t.sick_days == 30 + 2
    assert t.sick_hours == 16.0  # only the two single-day hours entries


def test_bradford_score_and_no_per_person_data():
    employees = [emp("1", "2020-01-01", loc="Oak House")]
    cats = [{"id": "sick", "name": "Sick Leave"}]
    # 3 separate one-day spells: S=3, D=3 -> B = 9*3 = 27
    requests = [
        leave("1", "sick", "2025-01-06", "2025-01-06"),
        leave("1", "sick", "2025-02-10", "2025-02-10"),
        leave("1", "sick", "2025-03-12", "2025-03-12"),
    ]
    rows = kpi.bradford_hotspots(employees, requests, cats, cfg())
    t = total_row(rows)
    assert t.max_bradford == 27
    assert t.employees_with_absence == 1
    # No employee id/name anywhere in the serialized output.
    blob = repr([r.model_dump() for r in rows])
    assert "Oak House" in blob  # service name is fine
    assert '"1"' not in blob and "employee_id" not in blob


# -- training compliance -------------------------------------------------


def test_training_compliance():
    as_of = date(2025, 6, 1)
    employees_with_certs = [
        (
            emp("1", "2020-01-01", loc="Oak House"),
            [{"name": "Safeguarding", "status": "valid", "expiry_date": "2026-01-01"}],
        ),
        (
            emp("2", "2020-01-01", loc="Oak House"),
            [{"name": "Safeguarding", "status": "expired", "expiry_date": "2024-01-01"}],
        ),
        (
            emp("3", "2020-01-01", loc="Oak House"),
            [{"name": "Safeguarding", "status": "valid", "expiry_date": "2025-06-15"}],
        ),
    ]
    t = total_row(kpi.training_compliance(employees_with_certs, cfg(), "mandatory", as_of))
    assert t.total_employees == 3
    assert t.compliant_employees == 2  # 1 and 3 valid; 2 expired
    assert t.compliance_rate_pct == round(2 / 3 * 100, 1)
    assert t.expiring_soon == 1  # id 3 expires 2025-06-15, within 30 days of 06-01


# -- grouping fallbacks --------------------------------------------------


def test_unassigned_bucket_when_grouping_field_missing():
    ps, pe = date(2025, 1, 1), date(2025, 12, 31)
    employees = [{"id": "1", "start_date": "2020-01-01", "termination_date": None}]
    rows = kpi.turnover(employees, cfg(grouping="work_location"), ps, pe)
    names = {r.service_name for r in svc_rows(rows)}
    assert names == {"Unassigned"}


def test_team_grouping_uses_first_team():
    ps, pe = date(2025, 1, 1), date(2025, 12, 31)
    employees = [
        {
            "id": "1",
            "start_date": "2020-01-01",
            "termination_date": None,
            "teams": [{"id": "t1", "name": "Care Team A"}],
        }
    ]
    rows = kpi.turnover(employees, cfg(grouping="team"), ps, pe)
    assert any(r.service_name == "Care Team A" for r in svc_rows(rows))
