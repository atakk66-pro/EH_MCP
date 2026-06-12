"""Thin read-only HTTP client for the Employment Hero REST API.

Only GET requests are made. The client handles pagination and the common
response envelope, retries transient failures (401 re-auth, 429 and 5xx with
backoff), and translates other failures into clean EHError messages.

Response envelope (confirmed against developer.employmenthero.com/api-references):

    {"data": {"items": [...], "page_index": 1, "item_per_page": 20,
              "total_items": 50, "total_pages": 3}}

with page_index (min 1) and item_per_page (default 20, max 100). A bare list
directly under "data" is also handled defensively.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from typing import Any

import httpx

from .auth import TokenManager
from .config import Settings
from .errors import EHError, translate_http_error

logger = logging.getLogger("eh_mcp.client")

_MAX_ITEM_PER_PAGE = 100  # documented maximum; verify against live docs
_MAX_RETRIES = 3  # for 429 and 5xx
_MAX_BACKOFF_SECONDS = 30.0


def _sleep(seconds: float) -> None:
    # Indirection so tests can patch out the real delay.
    time.sleep(seconds)


def _backoff_seconds(attempt: int) -> float:
    return min(2.0**attempt, _MAX_BACKOFF_SECONDS)


def _retry_after_seconds(resp: httpx.Response, attempt: int) -> float:
    header = resp.headers.get("Retry-After")
    if header:
        try:
            # Clamp to [0, max]: a negative value (buggy proxy) would crash
            # time.sleep. HTTP-date form falls through to backoff.
            return max(0.0, min(float(header), _MAX_BACKOFF_SECONDS))
        except ValueError:
            pass
    return _backoff_seconds(attempt)


class EHClient:
    def __init__(
        self,
        settings: Settings,
        tokens: TokenManager,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._s = settings
        self._tokens = tokens
        # transport is an injection point for tests (httpx.MockTransport).
        self._http = httpx.Client(
            base_url=settings.api_base, timeout=30.0, transport=transport
        )

    def close(self) -> None:
        self._http.close()

    # -- requests --------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._tokens.access_token()}",
            "Accept": "application/json",
        }

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        attempt = 0
        reauthed = False
        while True:
            try:
                resp = self._http.get(path, params=params, headers=self._headers())
            except httpx.TransportError as exc:
                # Network blips are transient: retry with backoff, then fail
                # with a clean message (raw exception text never reaches the
                # model — it can embed URLs and internals).
                if attempt < _MAX_RETRIES:
                    delay = _backoff_seconds(attempt)
                    logger.warning(
                        "GET %s network error (%s), backing off %.1fs",
                        path,
                        type(exc).__name__,
                        delay,
                    )
                    _sleep(delay)
                    attempt += 1
                    continue
                raise EHError(
                    "Could not reach Employment Hero (network problem). Check "
                    "the internet connection and try again."
                ) from exc
            status = resp.status_code

            if status == 200:
                logger.info("GET %s -> 200 (%d bytes)", path, len(resp.content))
                try:
                    return resp.json()
                except ValueError as exc:
                    raise EHError(
                        "Employment Hero returned an unexpected (non-JSON) "
                        "response. Try again shortly."
                    ) from exc

            if status == 401 and not reauthed:
                # Access token may have expired between requests; refresh once.
                logger.info("GET %s -> 401, refreshing token and retrying", path)
                self._tokens.invalidate()
                reauthed = True
                continue

            transient = status == 429 or 500 <= status < 600
            if transient and attempt < _MAX_RETRIES:
                delay = (
                    _retry_after_seconds(resp, attempt)
                    if status == 429
                    else _backoff_seconds(attempt)
                )
                logger.warning(
                    "GET %s -> %d, backing off %.1fs (attempt %d/%d)",
                    path,
                    status,
                    delay,
                    attempt + 1,
                    _MAX_RETRIES,
                )
                _sleep(delay)
                attempt += 1
                continue

            logger.error("GET %s -> %d, giving up", path, status)
            raise translate_http_error(status)

    # -- envelope helpers ------------------------------------------------

    @staticmethod
    def _data(payload: Any) -> Any:
        if isinstance(payload, dict):
            return payload.get("data", payload)
        return payload

    @classmethod
    def _items(cls, payload: Any) -> list[dict[str, Any]]:
        data = cls._data(payload)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            items = data.get("items")
            if isinstance(items, list):
                return items
        # An unrecognised shape must be loud: silently returning [] would make
        # counts read as 0 and mislead the KPIs built on them.
        raise EHError(
            "Employment Hero returned an unexpected response shape for a list "
            "endpoint. The API format may have changed."
        )

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
            if total_pages is not None:
                # Pagination metadata is authoritative, even across an empty
                # page mid-stream.
                if page >= int(total_pages):
                    break
            else:
                # Bare-list envelope with no metadata: a short page means done.
                # A full page may mean more, so keep going until a short one.
                if len(items) < _MAX_ITEM_PER_PAGE:
                    break
            page += 1

    def sample(self, path: str) -> Any:
        """Fetch a single-item page for schema inspection.

        Returns the raw payload. The caller (verify_api_schema) types away every
        value before anything is returned to the model.
        """
        return self._get(path, params={"page_index": 1, "item_per_page": 1})

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
