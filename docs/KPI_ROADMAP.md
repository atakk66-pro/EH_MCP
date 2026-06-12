# KPI roadmap (Employment Hero only)

This server's purpose is to give EH Noblecare directors HR/people KPIs in Claude
Desktop, read-only, with no personal data reaching the model. Every KPI is
computed per-employee server-side and surfaced only as a per-service aggregate.

Scope is Employment Hero only. Sage 50, finance KPIs (revenue, EBITDA, debtors,
cash), and care-operations KPIs (occupancy, cost per bed, average fee) are out of
scope: they are not in Employment Hero.

Everything below is derived from Employment Hero's public documentation. None of
it is verified against a live tenant yet, because API access needs a Platinum
plan. Treat field names and endpoints as assumptions to confirm with a real
token. See the caveats at the end.

## Build phases

### Phase 1 — core HR API, read scopes — BUILT (v0.3.0)
Tools live in `kpi.py` (pure computations, unit-tested) and `server.py`:
`staff_turnover`, `staff_retention`, `leavers_by_length_of_service`,
`early_attrition`, `starters_on_probation`, `absence_summary`,
`bradford_hotspots`, `training_compliance`. Each returns per-service rows plus an
"All services" total, grouped by `service_grouping` (default work_location),
with an "Unassigned" bucket when membership is unresolved. Pending live
confirmation: the employee-to-work-location link and the exact response field
names / status enums (the `verify_api_schema` probe settles both).

All from `GET /api/v1/organisations/{id}/employees`, `/leave_requests`, and the
per-employee certifications endpoint (the app has `employees_certifications:list`;
no org-level certifications scope is configured, so training compliance is
computed by iterating employees' certifications).

| KPI | Computable | Source / method |
|-----|-----------|-----------------|
| Staff turnover | yes | employees: leavers (termination_date in period) / average headcount |
| Retention (annualised) | yes | employees: 1 − turnover, or stayer-based, scaled to 12 months |
| Leavers by length of service | yes | employees: tenure bands from termination_date − start_date |
| Early attrition | yes | employees: leavers with tenure ≤ threshold (config) |
| Starters on probation | yes | employees: active, today < start_date + probation_length |
| Sickness / absence rate | partial | leave_requests (sick categories); rate needs an FTE/contracted-hours denominator |
| Long-term absence | yes | leave_requests: sick spells ≥ long_term_absence_days |
| Bradford Factor | yes | leave_requests: S²×D per employee, aggregated to service |
| Absence hotspots | yes | leave_requests ranked by absence/Bradford per service |
| Mandatory training % | yes | certifications valid, vs mandatory_cert_names allowlist |
| Safety certs | yes | certifications: % valid + count expiring within warning window |

### Phase 2 — EH Payroll / time (separate product)
Overtime %, total care hours by service, delivery vs rostered, lateness, agency
split, payroll amendments %. These need timesheet/roster/pay-category data.

The registered app's scopes settle what earlier research left ambiguous: the
hours data IS in this Controls API. `employees:timesheet_entries:list`,
`rostered_shifts:list`, `employees:rostered_shifts:job_status`,
`pay_categories:list`, and `work_types:list` are all granted, so total care
hours, overtime %, delivery vs rostered, and lateness are reachable with the
same token. Only pay-run-level KPIs (payroll amendments %) would need the
separate KeyPay Payroll product. Overtime/agency have no native flags; they are
defined by your pay-category and work-type configuration, which an admin must
map once in `kpi_config.yaml`.

### Phase 3 — recruitment / ATS (mostly not API-available)
Time-to-hire and offer acceptance have **no read API**. The public ATS API is a
careers-page job-syndication feed (jobs/departments/countries only); it exposes
no candidates, applications, offers, or hire dates. They exist only as in-product
CSV/PDF reports (Time to Hire, Candidate Flow). Probation pass rate can only be
**inferred** (terminated within start_date + probation_length), which conflates
genuine failures with ordinary early leavers; ship it labelled approximate or
hold it.

### Phase 4 — needs directors-supplied config
Annual leave vs target, budgeted-hours variance, delivery vs commissioned hours,
vacancy rate, supervision/observations/staff-meeting completion. These need
targets/budgets/establishment figures that do not exist in Employment Hero, so
they come from `kpi_config.yaml` (see `kpi_config.example.yaml`). Vacancy rate is
not computable at all without an establishment headcount per service.

## Blockers (decisions and inputs needed)

- **B1 — "service" dimension. RESOLVED:** care homes are configured as work
  locations in this tenant, so the default `service_grouping` is
  `work_location` (still configurable to team or cost_centre).
- **B2 / B3 — targets/establishment.** Supplied through `kpi_config.yaml`,
  keyed by EH IDs only. Vacancy rate needs establishment_headcount; budgeted
  variance needs budgeted_hours; annual leave vs target needs entitlement.
- **B4 — Payroll credentials.** Confirm Noblecare can issue Payroll (KeyPay) API
  access and on what auth model. Blocks all of Phase 2.
- **B5 — overtime/agency/amendment definitions.** Map pay-category / work-type
  IDs to overtime vs agency; agree what "amendment" means.
- **B7 — sickness categories.** EH returns a category name, not a flag. Set
  `sickness_categories` to your tenant's sick category names.
- **B8 — cert allowlists.** Set `mandatory_cert_names` and `safety_cert_names`.
- **B9 — recruitment KPIs.** Decide: report-only, or add a CSV-ingestion path
  that aggregates candidate rows to days/counts server-side before anything
  reaches the model.
- **B10 — data-availability checks.** Verify against a live tenant whether v1 HR
  exposes HR cases and form/submission data, and confirm field names/casing and
  the list-response envelope.
- **B11 — probation outcome.** No probation-outcome field exists; pass rate is
  inference-only.

## First tranche (when schema is verified)

Recommended Phase 1 tools to build first, each returning only aggregates/counts
(new allowlist models, no names, no employee IDs):

- `staff_turnover(organisation_id, period_start, period_end)` → per service:
  leavers, average_headcount, turnover_rate. Do **not** filter active-only;
  terminated employees carry the termination_date and are needed.
- `retention_annualised(...)` → per-service annualised retention.
- `leavers_by_length_of_service(...)` → per-service tenure-band counts.
- `early_attrition(..., window_days=180)` → per-service count + rate.
- `starters_on_probation(...)` → per-service count of active staff in probation.
- `absence_summary(...)` → per-service sick hours/days + long-term-absence count.
- `bradford_hotspots(..., period_weeks=52)` → per-service mean/max Bradford and
  over-threshold count. Never a per-person score tied to identity.
- `training_compliance(..., cert_set='mandatory'|'safety')` → per-service
  compliance % and expiring-soon count.

## Confirmed from the Developer Portal scope list

The "Add New Application" scope list (EH Controls API.pdf) resolves two earlier
uncertainties:

- **Timesheets and rosters are in this Controls API**, not only the separate
  KeyPay Payroll product. `Timesheet entries`, `Rostered shifts`, and
  `Pay categories` are all selectable Read scopes here, so the Phase 2 hours data
  (care hours, overtime, delivery, lateness) is reachable with the same token.
  Overtime classification still needs the pay-category mapping (B5).
- **Departments and Positions are not readable** (Update/Create scopes only, no
  Read). The `list_departments` tool has been removed, and "department" cannot
  be the service grouping. Use Teams, Work locations, or Cost centres. Leave
  categories *are* readable, which helps confirm the sickness/annual mapping
  (B7). The registered app's actual 22 scopes (resource:action format) are
  catalogued in [ALLOWLIST.md](ALLOWLIST.md).

## Confirmed (API reference + Postman collection)

- **Base URL + paths: CONFIRMED.** `https://api.employmenthero.com/api` +
  `/v1/organisations/...`; the server's `/api/v1/...` paths are correct.
- **Envelope and pagination: CONFIRMED.** `{"data": {"items": [...],
  "page_index", "item_per_page", "total_items", "total_pages"}}`; `item_per_page`
  max 100. `client.py` already matches.
- **Employee schema: CONFIRMED.** Real field names (`id` UUID; `start_date`,
  `termination_date`, `status`, `employment_type`, `trial_or_probation_type`,
  `trial_length`/`probation_length`, `teams`, cost centres). Full PII list in
  [ALLOWLIST.md](ALLOWLIST.md). Endpoint: `/employees?member_type=`.
- **Endpoint map + scoping: CONFIRMED** from the Postman collection. Org-scoped:
  employees, leave_requests (date-filterable), leave_categories, rostered_shifts
  (location/date/status-filterable), teams, teams/{id}/employees (headcount),
  work_locations, cost_centres, certifications-needs-scope-we-lack. Per-employee:
  timesheet_entries, leave_balances, certifications (the granted scope) — these
  KPIs iterate employees. Field names from create bodies are in ALLOWLIST.md.
- **`GET /organisations` exists** (`/v1/organisations`); the only open part is
  whether the token's scope set permits it.

## Still to verify (pilot probe or admin docs view)

- **Employee → work_location membership.** "service" = work_location, but the
  employee object documents only a legacy `location` *string* plus `teams` and
  cost centres, and the employees endpoint has no location filter. Confirm how to
  group employee-level KPIs (headcount/turnover) by work location. Roster/cost
  KPIs already filter by `location_ids`, so those are fine.
- **Exact response fields + status enums.** Create-body field names are known;
  confirm the response field names and the `status` value sets for leave_requests
  and timesheets via `verify_api_schema`.
- **Tenant specifics.** Your leave category names / `leave_type` values (for the
  sickness mapping) and whether `GET /organisations` is permitted.
- **Sickness denominator.** Absence *rate* needs an FTE/contracted-hours figure
  the leave API does not cleanly provide; until settled, report absolute sick
  hours/days rather than a rate.
