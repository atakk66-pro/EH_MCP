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

### Phase 1 — core HR API, read scopes, buildable now
All from `GET /api/v1/organisations/{id}/employees`, `/leave_requests`, and
`/certifications`.

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

The Payroll product is rebranded **KeyPay**, a separate API
(`/api/v2/business/{businessId}/...`) with its own base URL, its own auth (a
per-business API key or its own OAuth client), and a separately licensed module.
The HR token cannot reach it. Overtime/agency/amendment have no native flags;
they are defined by your pay-category and work-type configuration, which an admin
must map once.

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

- **B1 — "service" dimension.** Map a care home / branch / round to team,
  department, work_location, or cost_centre. Configurable via
  `service_grouping`; the default is `team`. Confirm against live data.
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

## Key uncertainties to verify first

- **Timesheets/roster location.** Research disagreed on whether
  `timesheet_entries` / `rostered_shifts` are exposed in the v1 HR API or only in
  the separate Payroll product. This decides whether overtime / care-hours sit in
  Phase 1 (degraded) or Phase 2. Check what your HR token can actually read.
- **Field names.** `start_date`, `termination_date`, `probation_length`,
  `trial_or_probation_type`, `leave_category_name`, `total_hours`, cert
  `expiry_date`/`status`, and the `{"data": {"items": [...]}}` envelope are all
  documentation-derived. Confirm casing and nesting on a live response.
- **Sickness denominator.** Absence *rate* needs an FTE/contracted-hours figure
  the leave API does not cleanly provide; until that is settled, report absolute
  sick hours/days rather than a rate.
