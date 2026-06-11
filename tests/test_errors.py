"""The HTTP error translation is the user-visible failure surface: every
message must be actionable for a non-technical user and contain no response
body content."""

import pytest

from eh_mcp.errors import EHError, translate_http_error


@pytest.mark.parametrize(
    ("status", "expect"),
    [
        (401, "connect employment hero"),
        (403, "scope"),
        (404, "id"),
        (429, "rate limit"),
        (500, "transient"),
        (503, "transient"),
        (418, "http 418"),
    ],
)
def test_messages_are_actionable(status, expect):
    err = translate_http_error(status)
    assert isinstance(err, EHError)
    assert expect in str(err).lower()


def test_401_does_not_mention_developer_script():
    assert "authorize.py" not in str(translate_http_error(401))
