# Employment Hero read-only MCP server

A local [Model Context Protocol](https://modelcontextprotocol.io) server that
exposes a small set of **read-only** Employment Hero queries to Claude Desktop,
while keeping personal data out of the model.

It is a director-level HR KPI layer (turnover, retention, sickness, Bradford
Factor, training compliance, and so on), all computed server-side and surfaced
only as per-service aggregates. Phase 1 KPI tools are built; see
[docs/KPI_ROADMAP.md](docs/KPI_ROADMAP.md) for what is live, what needs a second
integration, and what needs figures only the directors hold. The KPI field
mappings are confirmed against the API reference and Postman collection; a few
tenant specifics (notably the employee-to-work-location link) are confirmed at
first connect with the `verify_api_schema` probe.

## What it does, and what it deliberately does not

It exposes organisation-structure data (organisations, teams, work locations)
and a single aggregate headcount. Every tool returns only an
allowlisted, non-personal shape. There are no write tools, and no tool returns
an employee's name, email, address, salary, date of birth, or tax/bank details.

### How PII is kept out of the model

The safety property does not depend on the model behaving. It is enforced in
code, before any result is serialized:

1. **Read-only OAuth scopes.** The integration requests only read scopes
   (`employees:list`, `teams:list`, ...; the full set is in
   [docs/ALLOWLIST.md](docs/ALLOWLIST.md)). With no write scope, the token
   cannot mutate anything even if asked.
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

**Lookups** (id + name only): `list_organisations`, `list_teams`,
`list_work_locations`, `employee_count`.

**KPIs** (per-service aggregates, no per-person data; periods default to the
trailing 12 months):

| Tool | Returns |
|------|---------|
| `staff_turnover` | leavers / average headcount per service |
| `staff_retention` | share employed at period start still in post at end |
| `leavers_by_length_of_service` | leavers bucketed by tenure (<3m … 2y+) |
| `early_attrition` | share of leavers within the early-leaver window |
| `starters_on_probation` | count currently in probation/trial |
| `absence_summary` | sick hours/days + long-term-absence counts |
| `bradford_hotspots` | Bradford Factor mean/max/over-threshold |
| `training_compliance` | mandatory/safety cert compliance % |

Every KPI returns one row per service (grouped by `service_grouping`, default
`work_location`) plus an "All services" total. Computation runs server-side; the
[KPI config](#kpi-configuration) supplies the sickness categories, certificate
lists, and thresholds. `list_departments` was removed (EH exposes no read scope
for departments).

## Prerequisites

- **An Employment Hero plan with API access (Platinum or above).** Without it,
  app registration in the Developer Portal is not available.
- A registered app in the
  [Developer Portal](https://developer.employmenthero.com/) giving you a
  **Client ID** and **Client Secret**. See [Employment Hero app
  setup](#employment-hero-app-setup) for the exact redirect URI, scopes, and the
  admin role required.
- Python 3.10+ (only for the manual install; the `.mcpb` extension provisions
  Python itself).

## Employment Hero app setup

Register one app in the Developer Portal ("Add New Application"). The same app
(one Client ID + Secret) is shared by every director; each person authorizes
themselves.

### Redirect URI

Employment Hero requires an **https** redirect URI. Enter exactly:

```
https://127.0.0.1:8765/callback
```

This is a local address, not a website, so there is nothing to host. The
extension's sign-in listener serves it over TLS using a self-signed certificate
generated on the machine, so the browser shows a one-time "your connection is
not private" warning that the user clicks through (see [docs/INSTALL.md](docs/INSTALL.md)).
Whatever you register here must match the extension's callback port (default
8765) and `EH_REDIRECT_URI` in the manual install.

### Administrator role required

Whoever does the one-time "connect Employment Hero" sign-in must be an
Employment Hero **administrator**, or have access to the relevant modules via
Permissions. Almost every scope below sits under the portal's "Administrator
Role Required" group. Only `Organisations -> Read` works for a standard user.

### Configured scopes

The app is registered ("NobleCare KPI Reader") with 22 read-only scopes in
`resource:action` form. The full list, and the per-scope mapping of what the
server reads internally versus what may ever reach the model, is in
[docs/ALLOWLIST.md](docs/ALLOWLIST.md). The same 22 strings are the `EH_SCOPES`
defaults in `.env.example`, `manifest.json`, and `config.py`; they must match
the app exactly, since EH scope sets are immutable once saved.

Two granted scopes (`employees:work_eligibility:show` and
`employees:onboard_polling_status`) are never called by any tool; the high-PII
portal scopes (Bank accounts, Pay details, Payslips, Tax declaration, Documents,
Emergency contacts, Superannuation) were left unticked at registration.

Notes:
- **Departments and Positions have no Read scope** (only Update/Create), so they
  cannot be used as the "by service" grouping. Use Teams, Work locations, or
  Cost centres.
- The portal shows friendly names; the exact scope strings appear on the app's
  View Application page in `resource:action` form (e.g. `employees:list`,
  `teams:list`). Copy them into `EH_SCOPES` (manual install) or the extension's
  "scopes" field so the sign-in request matches. The registered app's 22 scopes
  are the defaults in `.env.example` and `manifest.json`; the full
  scope-to-field mapping is in [docs/ALLOWLIST.md](docs/ALLOWLIST.md).
- The registered app has **no organisations scope** (it was not in the portal's
  configured list). `list_organisations` may therefore be refused; if it is,
  the organisation ID must be supplied directly. Verify on first live call.

## Install (recommended: Desktop Extension)

For non-technical users (directors), distribute the packaged `.mcpb` so install
is click-through, with no Python, `pip`, or config files. Full step-by-step:
[docs/INSTALL.md](docs/INSTALL.md). In short:

1. Build the bundle once (you, the maintainer):
   ```bash
   # name it after the manifest.json version, e.g. 0.4.0:
   npx -y @anthropic-ai/mcpb pack . "employment-hero-readonly-0.4.0.mcpb"
   ```
   Or just push a `v0.4.0` tag and let the release workflow build and publish it.
   (~20 KB; uses the `uv` server type, so Claude Desktop provisions Python and
   dependencies itself.)
2. Send that one file to each director.
3. They open Claude Desktop, go to Settings > Extensions, install the `.mcpb`,
   and paste the **Client ID**, **Client Secret**, and **Organisation ID** in
   the dialog (the credentials are stored in their OS keychain, not a file).
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
        "EH_ORG_ID": "your-organisation-id"
      }
    }
  }
}
```

`EH_SCOPES` and `EH_TOKEN_FILE` can be omitted: the defaults are the registered
app's 22 scopes and `~/.eh_mcp/token.json`.

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
- Whether `GET /api/v1/organisations` works without an organisations scope
  (none is configured on the app). If not, set `EH_ORG_ID`.
- Refresh-token lifetime and exact rotation behaviour.
- Data residency for your contracting region (AU vs UK).
