"""Clean, non-PII errors surfaced to the model when an Employment Hero call fails.

Raw httpx exceptions and API response bodies are never passed to the model: a
body could echo back request context, and a stack trace is noise. Each failure
is translated to a short, actionable message instead.
"""

from __future__ import annotations


class EHError(RuntimeError):
    """A tool-level error with a clean message safe to show the model."""


_MESSAGES = {
    401: (
        "Authentication failed (401). The Employment Hero connection may have "
        "expired or been revoked. Ask me to connect Employment Hero again."
    ),
    403: (
        "Access denied by Employment Hero (403). The OAuth app is most likely "
        "missing a required read scope for this endpoint, or the plan does not "
        "include it."
    ),
    404: "Not found (404). Check the organisation_id (and any other id) you passed.",
    429: "Rate limited by Employment Hero (429). Try again in a few seconds.",
}


def translate_http_error(status_code: int) -> EHError:
    message = _MESSAGES.get(status_code)
    if message is None:
        if 500 <= status_code < 600:
            message = (
                f"Employment Hero API error ({status_code}). This is usually "
                "transient; try again shortly."
            )
        else:
            message = f"Employment Hero API returned HTTP {status_code}."
    return EHError(message)
