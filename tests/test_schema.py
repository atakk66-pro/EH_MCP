"""The schema probe must reveal field names and types but never values, so it
cannot leak personal data even when the sample record is full of PII."""

from eh_mcp.schema import type_skeleton


def test_values_are_typed_away():
    raw = {
        "data": {
            "items": [
                {
                    "id": 4012,
                    "first_name": "Jane",
                    "email": "jane@example.com",
                    "salary": 31250.50,
                    "active": True,
                    "manager": None,
                    "teams": [{"id": 7, "name": "Oak House"}],
                }
            ],
            "total_pages": 12,
            "total_items": 240,
        }
    }
    skel = type_skeleton(raw)
    assert skel == {
        "data": {
            "items": [
                {
                    "id": "int",
                    "first_name": "str",
                    "email": "str",
                    "salary": "float",
                    "active": "bool",
                    "manager": "null",
                    "teams": [{"id": "int", "name": "str"}],
                }
            ],
            "total_pages": "int",
            "total_items": "int",
        }
    }


def test_no_personal_value_appears_anywhere():
    raw = {"name": "Jane Doe", "notes": "off sick with anxiety", "tfn": "123456789"}
    flat = repr(type_skeleton(raw))
    for leaked in ("Jane", "anxiety", "123456789"):
        assert leaked not in flat


def test_empty_list_and_depth_guard():
    assert type_skeleton([]) == "list[empty]"
    deep = {"a": {"b": {"c": {"d": {"e": {"f": {"g": "x"}}}}}}}
    # Recursion stops; output is finite and contains no value.
    assert "x" not in repr(type_skeleton(deep))
