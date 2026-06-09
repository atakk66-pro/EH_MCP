"""The allowlist models must drop every field that is not explicitly declared.

This is the test that guards the core PII property: even if a raw Employment
Hero record carries personal fields, the mapped result must contain only the
allowlisted keys.
"""

from eh_mcp.models import to_named, to_org


def test_named_keeps_only_id_and_name():
    raw = {
        "id": 42,
        "name": "Engineering",
        # Fields that must NOT survive the allowlist:
        "manager_email": "jane@example.com",
        "manager_name": "Jane Doe",
        "headcount": 17,
        "cost_centre_code": "CC-9",
    }
    dumped = to_named(raw).model_dump()
    assert dumped == {"id": "42", "name": "Engineering"}
    assert "manager_email" not in dumped
    assert "manager_name" not in dumped


def test_org_keeps_only_id_and_name():
    raw = {
        "id": "org_1",
        "name": "Acme Pty Ltd",
        "abn": "12345678901",
        "primary_contact_email": "admin@acme.test",
    }
    dumped = to_org(raw).model_dump()
    assert dumped == {"id": "org_1", "name": "Acme Pty Ltd"}


def test_missing_fields_become_empty_strings():
    dumped = to_named({}).model_dump()
    assert dumped == {"id": "", "name": ""}
