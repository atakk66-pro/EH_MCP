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
