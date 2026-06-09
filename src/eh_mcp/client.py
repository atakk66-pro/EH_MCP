"""Thin read-only HTTP client for the Employment Hero REST API.

Only GET requests are made. The client handles pagination and the common
response envelope, and re-authenticates once on a 401.

Response shape assumption: list endpoints return

    {"data": {"items": [...], "total_pages": N, "total_items": M, ...}}

Some endpoints may return the list directly under "data". Both are handled.
Verify against the live API reference for your account before relying on it.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx

from .auth import TokenManager
from .config import Settings

_MAX_ITEM_PER_PAGE = 100  # documented maximum; verify against live docs


class EHClient:
    def __init__(self, settings: Settings, tokens: TokenManager) -> None:
        self._s = settings
        self._tokens = tokens
        self._http = httpx.Client(base_url=settings.api_base, timeout=30.0)

    def close(self) -> None:
        self._http.close()

    # -- requests --------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._tokens.access_token()}",
            "Accept": "application/json",
        }

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = self._http.get(path, params=params, headers=self._headers())
        if resp.status_code == 401:
            # Access token may have expired between requests. Refresh once.
            self._tokens.invalidate()
            resp = self._http.get(path, params=params, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    # -- envelope helpers ------------------------------------------------

    @staticmethod
    def _data(payload: dict[str, Any]) -> Any:
        return payload.get("data", payload)

    @classmethod
    def _items(cls, payload: dict[str, Any]) -> list[dict[str, Any]]:
        data = cls._data(payload)
        if isinstance(data, dict):
            items = data.get("items")
            if isinstance(items, list):
                return items
            return []
        if isinstance(data, list):
            return data
        return []

    # -- public read operations -----------------------------------------

    def paginate(
        self, path: str, params: dict[str, Any] | None = None
    ) -> Iterator[dict[str, Any]]:
        """Yield every raw item across all pages of a list endpoint."""
        page = 1
        base = dict(params or {})
        while True:
            payload = self._get(
                path,
                params={**base, "page_index": page, "item_per_page": _MAX_ITEM_PER_PAGE},
            )
            items = self._items(payload)
            for item in items:
                yield item

            data = self._data(payload)
            total_pages = data.get("total_pages") if isinstance(data, dict) else None
            if not items or not total_pages or page >= int(total_pages):
                break
            page += 1

    def total_items(self, path: str, params: dict[str, Any] | None = None) -> int:
        """Return the total count for a list endpoint from pagination metadata.

        Requests a single item so the body is tiny, then reads total_items from
        the envelope. No individual record fields are inspected. Falls back to a
        full streamed count only if the envelope omits total_items.
        """
        payload = self._get(
            path, params={**(params or {}), "page_index": 1, "item_per_page": 1}
        )
        data = self._data(payload)
        if isinstance(data, dict) and data.get("total_items") is not None:
            return int(data["total_items"])
        return sum(1 for _ in self.paginate(path, params=params))
