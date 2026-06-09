# Employment Hero read-only MCP server

A local [Model Context Protocol](https://modelcontextprotocol.io) server that
exposes a small set of **read-only** Employment Hero queries to Claude Desktop,
while keeping personal data out of the model.

## What it does, and what it deliberately does not

It exposes organisation-structure data (organisations, teams, departments, work
locations) and a single aggregate headcount. Every tool returns only an
allowlisted, non-personal shape. There are no write tools, and no tool returns
an employee's name, email, address, salary, date of birth, or tax/bank details.

### How PII is kept out of the model

The safety property does not depend on the model behaving. It is enforced in
code, before any result is serialized:

1. **Read-only OAuth scopes.** The integration requests only
   `urn:mainapp:...:read` scopes. With no write scope, the token cannot mutate
   anything even if asked.
2. **Only read tools are registered.** A tool that does not exist cannot be
   called. There is no create/update/delete tool in this server.
3. **Allowlist projection.** Every tool returns a Pydantic model
   (`models.py`) that declares only non-personal fields. Anything not on the
   model is structurally absent from the output. The mappers build the result
   from a positive list; they never spread or dump the raw API record.
4. **Aggregate over rows.** `employee_count` returns a single integer read from
   the pagination total. It never inspects an individual employee field.

If you extend this server, keep that order. The one footgun in any language is
returning the raw API JSON or dumping a full upstream object. Always go through
an allowlist model.

## Tools

| Tool | Returns | Scope needed |
|------|---------|--------------|
| `list_organisations()` | `[{id, name}]` | organisations:read |
| `list_teams(organisation_id)` | `[{id, name}]` | organisations:read |
| `list_departments(organisation_id)` | `[{id, name}]` | organisations:read |
| `list_work_locations(organisation_id)` | `[{id, name}]` | organisations:read |
| `employee_count(organisation_id)` | `int` | employees:read |

## Prerequisites

- **An Employment Hero plan with API access (Platinum or above).** Without it,
  app registration in the Developer Portal is not available.
- A registered app in the
  [Developer Portal](https://developer.employmenthero.com/) giving you a
  **Client ID** and **Client Secret**, with a redirect URI of
  `http://localhost:8765/callback` (or whatever you set in `EH_REDIRECT_URI`).
- Python 3.10+.

## Setup

```bash
# from the project root
pip install -e .

cp .env.example .env
# edit .env: set EH_CLIENT_ID and EH_CLIENT_SECRET

# one-time browser authorization; writes the refresh token to EH_TOKEN_FILE
python scripts/authorize.py
```

`authorize.py` opens the Employment Hero consent screen, captures the
authorization code on a local callback, and stores the rotating refresh token
(default `~/.eh_mcp/token.json`, mode 600). The server uses that refresh token
to mint 15-minute access tokens at runtime and rewrites the file each time
Employment Hero rotates it.

## Run it

```bash
python -m eh_mcp        # stdio server; Ctrl-C to stop
```

### Wire it into Claude Desktop

Add this to `claude_desktop_config.json` (on Linux:
`~/.config/Claude/claude_desktop_config.json`; macOS:
`~/Library/Application Support/Claude/claude_desktop_config.json`). Use the
absolute path to the Python interpreter that has the package installed:

```json
{
  "mcpServers": {
    "employment-hero": {
      "command": "/home/aran/miniconda3/envs/MP_venv/bin/python",
      "args": ["-m", "eh_mcp"],
      "env": {
        "EH_CLIENT_ID": "your-client-id",
        "EH_CLIENT_SECRET": "your-client-secret",
        "EH_SCOPES": "urn:mainapp:organisations:read urn:mainapp:employees:read",
        "EH_TOKEN_FILE": "/home/aran/.eh_mcp/token.json"
      }
    }
  }
}
```

Restart Claude Desktop. The tools appear under the `employment-hero` server.

Note: Claude Desktop is officially supported on macOS and Windows. On Linux the
config path above is the community convention.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

The test suite checks the allowlist: a raw record carrying personal fields must
map to only `{id, name}`.

## Caveats to verify against the live API

These came from documentation research and were not confirmed against a live
account (API access needs a paid plan). Check them before relying on them:

- The list-response envelope is assumed to be `{"data": {"items": [...],
  "total_pages": N, "total_items": M}}`. `client.py` also handles a bare list
  under `data`. Confirm the real shape and adjust `_items` / `_data` if needed.
- Rate limits (reported 20 req/s, 100 req/min) and the `item_per_page` maximum
  of 100.
- Whether `teams`, `departments`, and `work_locations` are all covered by the
  `organisations:read` scope, or need their own scopes.
- Refresh-token lifetime and exact rotation behaviour.
- Data residency for your contracting region (AU vs UK).
