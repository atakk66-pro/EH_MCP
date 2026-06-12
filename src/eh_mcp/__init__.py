"""Read-only Employment Hero MCP server.

PII safety lives in two places, both enforced server-side:
  1. The OAuth scopes requested (read-only, least-privilege).
  2. The Pydantic allowlist models that every tool returns.
See README.md for the full design.
"""

__version__ = "0.4.4"
