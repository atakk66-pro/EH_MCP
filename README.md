# Employment Hero read-only MCP server

A local [Model Context Protocol](https://modelcontextprotocol.io) server that
exposes a small set of **read-only** Employment Hero queries to Claude Desktop,
while keeping personal data out of the model.

The goal is a director-level HR KPI layer (turnover, sickness, Bradford Factor,
training compliance, and so on), all computed server-side and surfaced only as
per-service aggregates. See [docs/KPI_ROADMAP.md](docs/KPI_ROADMAP.md) for what
is buildable now, what needs a second integration, and what needs figures only
the directors hold. The current code is the read-only foundation plus the
[config layer](#kpi-configuration) those KPIs depend on; the KPI tools land once
the schema is verified against a live token.

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

## Install (recommended: Desktop Extension)

For non-technical users (directors), distribute the packaged `.mcpb` so install
is click-through, with no Python, `pip`, or config files. Full step-by-step:
[docs/INSTALL.md](docs/INSTALL.md). In short:

1. Build the bundle once (you, the maintainer):
   ```bash
   npx -y @anthropic-ai/mcpb pack .
   ```
   This produces `employment-hero-readonly.mcpb` (~20 KB; uses the `uv` server
   type, so Claude Desktop provisions Python and dependencies itself).
2. Send that one file to each director.
3. They open Claude Desktop, go to Settings > Extensions, install the `.mcpb`,
   and paste the **Client ID** and **Client Secret** in the dialog (stored in
   their OS keychain, not a file).
4. In chat they say "connect Employment Hero" once. The `connect_employment_hero`
   tool opens their browser to approve read-only access, then stores their
   personal refresh token locally (`~/.eh_mcp/token.json`, mode 600). Each
   machine connects independently, which is what Employment Hero's refresh-token
   rotation requires.

The same Client ID/Secret are shared across directors (one EH app); each person
authorizes themselves. Until connected, the data tools return a friendly "not
connected" prompt so Claude walks them through it.

## Advanced: manual install (developers)

```bash
pip install -e .
cp .env.example .env          # set EH_CLIENT_ID and EH_CLIENT_SECRET
python scripts/authorize.py   # one-time browser sign-in (same flow as the tool)
python -m eh_mcp              # stdio server
```

Then add it to `claude_desktop_config.json` (Linux:
`~/.config/Claude/claude_desktop_config.json`; macOS:
`~/Library/Application Support/Claude/claude_desktop_config.json`), pointing
`command` at the Python interpreter that has the package installed:

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

Note: Claude Desktop is officially supported on macOS and Windows. On Linux the
config path above is the community convention.

## KPI configuration

Many KPIs depend on facts that do not exist in Employment Hero: which dimension
is a "service", which leave categories are sickness, which certificates are
mandatory, and per-service establishment/budget/target figures. These are
supplied in a directors-maintained YAML file.

```bash
cp kpi_config.example.yaml kpi_config.yaml
# edit kpi_config.yaml for your tenant, then validate it:
python -m eh_mcp.kpi_config kpi_config.yaml
```

The real `kpi_config.yaml` is gitignored (it is org-specific); the example is
committed. It holds IDs, names, and numbers only, never personal data. Point
`EH_KPI_CONFIG` at a different path if you keep it elsewhere. The KPI tools that
consume this config are not built yet; see
[docs/KPI_ROADMAP.md](docs/KPI_ROADMAP.md).

## Tests

```bash
pip install -e ".[dev]"
pytest
```

The suite covers the allowlist (a raw record with personal fields maps to only
`{id, name}`), the HTTP client (pagination, retries, error translation), the
token manager (refresh and rotation), and the KPI config loader.

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
