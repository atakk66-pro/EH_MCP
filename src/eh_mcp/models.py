"""Allowlist response models.

Every tool returns one of these, never a raw Employment Hero record. The model
is a positive allowlist: any field not declared here is structurally absent from
the output, so it can never reach the model. This is the core PII control.

Do NOT add personal fields (name of a person, email, phone, DOB, address,
salary, tax/NI/TFN, bank details) to these models.
"""

from __future__ import annotations

from pydantic import BaseModel


class Organisation(BaseModel):
    """Non-PII view of an organisation."""

    id: str
    name: str


class NamedEntity(BaseModel):
    """Non-PII view of an org-structure entity: team, department, work location.

    Only the identifier and the entity's own name are exposed. The name here is
    the name of a *group or place*, not of a person.
    """

    id: str
    name: str


def to_org(raw: dict) -> Organisation:
    """Map a raw organisation record through the allowlist."""
    return Organisation(id=str(raw.get("id", "")), name=str(raw.get("name", "")))


def to_named(raw: dict) -> NamedEntity:
    """Map a raw org-structure record through the allowlist.

    Builds the result from an explicit positive list. Never spread or dump the
    raw record; that would defeat the allowlist.
    """
    return NamedEntity(id=str(raw.get("id", "")), name=str(raw.get("name", "")))


# -- KPI result models ---------------------------------------------------
#
# Every KPI tool returns a list of these. They carry only a service id/name and
# numbers — never a person's name, id, or any per-person row. The org-wide row
# uses service_id "__all__". See docs/ALLOWLIST.md.


class TurnoverRow(BaseModel):
    service_id: str
    service_name: str
    leavers: int
    average_headcount: float
    turnover_rate_pct: float


class RetentionRow(BaseModel):
    service_id: str
    service_name: str
    starting_headcount: int
    retained: int
    retention_rate_pct: float


class TenureBandsRow(BaseModel):
    service_id: str
    service_name: str
    leavers: int
    bands: dict[str, int]


class CountRow(BaseModel):
    service_id: str
    service_name: str
    count: int


class RateRow(BaseModel):
    service_id: str
    service_name: str
    count: int
    denominator: int
    rate_pct: float


class AbsenceRow(BaseModel):
    service_id: str
    service_name: str
    sick_hours: float
    sick_days: int
    long_term_absence_cases: int


class BradfordRow(BaseModel):
    service_id: str
    service_name: str
    employees_with_absence: int
    mean_bradford: float
    max_bradford: int
    over_threshold: int


class ComplianceRow(BaseModel):
    service_id: str
    service_name: str
    cert_set: str
    compliant_employees: int
    total_employees: int
    compliance_rate_pct: float
    expiring_soon: int
