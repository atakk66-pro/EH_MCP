"""Tests for the read-only HTTP client: pagination, envelope parsing, retries,
and error translation. All use a mocked httpx transport, no live API.
"""

import httpx
import pytest

from eh_mcp import client as client_mod
from eh_mcp.client import EHClient
from eh_mcp.config import Settings
from eh_mcp.errors import EHError


class FakeTokens:
    """Stand-in for TokenManager that never hits the network."""

    def __init__(self):
        self.invalidated = 0

    def access_token(self):
        return "fake-access-token"

    def invalidate(self):
        self.invalidated += 1


def make_client(handler, tokens=None):
    settings = Settings(
        client_id="cid",
        client_secret="secret",
        redirect_uri="http://localhost:8765/callback",
        api_base="https://api.employmenthero.com",
        oauth_base="https://oauth.employmenthero.com",
        token_file="/tmp/unused-token.json",
        scopes="urn:mainapp:organisations:read",
    )
    return EHClient(
        settings, tokens or FakeTokens(), transport=httpx.MockTransport(handler)
    )


def envelope(items, *, total_pages=1, total_items=None):
    data = {"items": items, "total_pages": total_pages}
    if total_items is not None:
        data["total_items"] = total_items
    return {"data": data}


def test_paginate_walks_all_pages_and_stops():
    def handler(request):
        page = int(httpx.QueryParams(request.url.query).get("page_index"))
        if page == 1:
            return httpx.Response(200, json=envelope([{"id": 1}, {"id": 2}], total_pages=2))
        if page == 2:
            return httpx.Response(200, json=envelope([{"id": 3}], total_pages=2))
        raise AssertionError(f"requested page {page}; should have stopped at 2")

    c = make_client(handler)
    items = list(c.paginate("/api/v1/organisations"))
    assert [i["id"] for i in items] == [1, 2, 3]


def test_total_items_reads_envelope_total():
    def handler(request):
        return httpx.Response(200, json=envelope([{"id": 1}], total_items=137))

    c = make_client(handler)
    assert c.total_items("/api/v1/organisations/x/employees") == 137


def test_bare_list_under_data_is_handled():
    def handler(request):
        return httpx.Response(200, json={"data": [{"id": "a"}, {"id": "b"}]})

    c = make_client(handler)
    assert [i["id"] for i in c.paginate("/api/v1/organisations")] == ["a", "b"]


def test_401_triggers_one_reauth_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(401, json={"error": "expired"})
        return httpx.Response(200, json=envelope([{"id": 1}]))

    tokens = FakeTokens()
    c = make_client(handler, tokens=tokens)
    items = list(c.paginate("/api/v1/organisations"))
    assert [i["id"] for i in items] == [1]
    assert tokens.invalidated == 1
    assert calls["n"] == 2


def test_429_backs_off_then_succeeds(monkeypatch):
    slept = []
    monkeypatch.setattr(client_mod, "_sleep", lambda s: slept.append(s))
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "2"}, json={})
        return httpx.Response(200, json=envelope([{"id": 9}], total_items=1))

    c = make_client(handler)
    assert c.total_items("/api/v1/organisations/x/employees") == 1
    assert slept == [2.0]


def test_403_raises_clean_error_with_scope_hint():
    def handler(request):
        return httpx.Response(403, json={"error": "forbidden"})

    c = make_client(handler)
    with pytest.raises(EHError) as excinfo:
        list(c.paginate("/api/v1/organisations"))
    assert "scope" in str(excinfo.value).lower()


def test_500_retries_then_gives_up(monkeypatch):
    monkeypatch.setattr(client_mod, "_sleep", lambda s: None)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(503, json={})

    c = make_client(handler)
    with pytest.raises(EHError):
        list(c.paginate("/api/v1/organisations"))
    # 1 initial attempt + _MAX_RETRIES retries
    assert calls["n"] == client_mod._MAX_RETRIES + 1
