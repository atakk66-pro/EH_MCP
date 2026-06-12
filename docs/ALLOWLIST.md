# Data allowlist specification

This is the single source of truth for what Employment Hero data this server
may touch, and what may ever reach the model. It is derived from the 22 scopes
configured on the registered app ("NobleCare KPI Reader", from its View
Application page) plus the project's PII rules. If a field is not named in an
ALLOWED column below, it is blocked by default; new or unknown fields are
blocked until added here deliberately.

Two separate boundaries matter:

- **Server-internal reads** — fields the server may parse in memory to compute
  aggregates. These never leave the process.
- **Model-visible output** — what a tool may return to Claude. This is the
  boundary that protects personal data, enforced by the Pydantic allowlist
  models in `models.py` and by tools returning aggregates.

## Enforcement rules (restated)

1. Tools return only allowlist Pydantic models or plain numbers. Never raw API
   JSON, never `.model_dump()` of an upstream object.
2. `employee_id` is an internal correlation key only. It never appears in any
   tool output, log line, or error message.
3. No free-text field is ever read into output, aggregated, or logged. Leave
   request reasons and termination summaries can contain health and personal
   details (special category data under UK GDPR). Blocked entirely.
4. Identity, contact, pay, and eligibility fields are never read into outputs:
   names, email, phone, DOB, address, gender, marital status, salary, bank,
   tax/NI, right-to-work.
5. Aggregates must not be re-identifying: per-service figures only, never
   per-person rows. Where a service is so small that an aggregate identifies an
   individual, that is accepted residual risk for internal director use, but
   per-person breakdowns are still never offered.

## The configured scopes (the contract)

The app's scope set is immutable. The granted token can reach exactly these,
all read-only. There is no write scope and no organisations scope.

| # | Scope | Used by this server? |
|---|-------|----------------------|
| 1 | cost_centres:list | yes — org structure |
| 2 | employees:list | yes — core KPI input |
| 3 | employees:show | avoid — list covers everything needed |
| 4 | employees:onboard_polling_status | **never called** |
| 5 | employees_certifications:list | yes — training compliance |
| 6 | employees:leave_balances:list | yes — annual leave vs target |
| 7 | employees:rostered_shifts:job_status | yes — delivery/fill KPIs (Phase 2) |
| 8 | employees:rostered_shifts:shift_cost:show | yes — cost aggregates only (Phase 2) |
| 9 | employees:timesheet_entries:list | yes — hours/overtime (Phase 2) |
| 10 | employees:work_eligibility:show | **never called** |
| 11 | employing_entities:list | yes — org structure |
| 12 | leave_categories:list | yes — sickness/annual mapping |
| 13 | leave_requests:list | yes — sickness, Bradford |
| 14 | leave_requests:show | avoid — list covers it |
| 15 | pay_categories:list | yes — overtime classification |
| 16 | rostered_shifts:list | yes — Phase 2 |
| 17 | rostered_shifts:show | avoid — list covers it |
| 18 | teams:list | yes — org structure / grouping |
| 19 | teams:employees:list | yes — team headcounts |
| 20 | work_locations:list | yes — the "service" grouping |
| 21 | work_sites:list | yes — org structure |
| 22 | work_types:list | yes — hours classification |

`employees:work_eligibility:show` (right-to-work / immigration status) and
`employees:onboard_polling_status` were granted at app registration but no tool
calls them, so that data never enters the process. Do not add tools that do.

## Per-resource allowlist

Endpoint paths and field names are documentation-derived and must be confirmed
against the first live responses (see checklist at the end). The *rules* below
hold regardless of exact field spelling.

### Organisation structure (id + name only)

Resources: teams, work_locations, work_sites, work_types, cost_centres,
employing_entities, leave_categories, pay_categories.

| | |
|---|---|
| Server-internal | `id`, `name` (and `parent`/hierarchy ids if present) |
| Model-visible | `id`, `name` |
| Blocked | everything else — site addresses, contact people, manager fields, codes that embed personal data |

These power `list_teams`, `list_work_locations`, and the grouping dimension for
every per-service KPI. Work sites may carry street addresses; an address is a
location's data, not a person's, but it is still not needed, so it stays
blocked.

### Employees (`employees:list`)

| | |
|---|---|
| Server-internal | `id` (UUID, correlation only), `start_date`, `termination_date`, `status` (active/inactive/archived/terminated), `employment_type`, `trial_or_probation_type`, `trial_length` (days), `probation_length` (months), `teams` [{id,name}], `primary_cost_centre`/`secondary_cost_centres`, `location` (legacy work-location string), `job_title` |
| Model-visible | **nothing per-person.** Only aggregates: headcounts, turnover/retention rates, tenure-band counts, starters/leavers counts, probation counts — always per service or org-total |
| Blocked (confirmed against the docs, all PII) | `first_name`, `last_name`, `middle_name`, `full_name`, `full_legal_name`, `legal_name`, `known_as`, `title`, `pronouns`, `date_of_birth`, `account_email`/`email`/`personal_email`/`company_email`, `personal_mobile_number`/`company_mobile`/`company_landline`/`home_phone`, `address`/`residential_address`/`postal_address`, `gender`, `marital_status`, `nationality`, `abn`, `uk_tax_and_national_insurance` (UTR + NI number), `avatar_url`, `biography`, `termination_summary` (free-text reason), managers |

The full Employee schema is confirmed against the API reference. Two notes for
the KPI build:
- `id` is a **UUID string**, not an int (the allowlist mappers already coerce
  with `str()`).
- The employee object's grouping fields are `teams`, cost centres, and a legacy
  `location` **string** — there is no documented `work_location_id` on the
  employee. Since "service" = work_location here, confirm during the pilot how an
  employee maps to a work location (the `location` string vs a separate
  membership endpoint); if only the string is available, group on it and resolve
  names via `work_locations:list`.

`employees:show` adds nothing the KPIs need; prefer `employees:list` so only
one code path parses employee records.

### Leave requests (`leave_requests:list`, `leave_categories:list`)

Endpoint `GET /api/v1/organisations/{org}/leave_requests?start_date=&end_date=`
— org-scoped and date-filterable (confirmed from the Postman collection).
Fields from the create body: `leave_category_id`, `start_date`, `end_date`,
`hours_per_day` (array of `{date, hours}`; total hours = sum), `comment`.

| | |
|---|---|
| Server-internal | `employee_id` (correlation), `leave_category_id` (name via `leave_categories:list`), `start_date`, `end_date`, `hours_per_day[].hours`, `status` |
| Model-visible | per-service aggregates: sick hours/days, spell counts, long-term-absence counts, Bradford mean/max/over-threshold counts, leave taken vs entitlement |
| Blocked | `comment` (free text, may contain health details), attachments, approver identity, per-person Bradford scores or absence histories |

Which category names count as sickness vs annual comes from
`kpi_config.yaml` (`sickness_categories`, `annual_leave_categories`), validated
against `leave_categories:list` at runtime. **Leave Category schema (confirmed
from the docs):** `id` (uuid), `name` (string), `leave_type` (enum), and
`external_id`. The `leave_type` enum may classify sickness vs annual more
robustly than name matching — confirm its values during the pilot.

### Leave balances (`employees:leave_balances:list`)

Schema confirmed from the docs: `category` (object), `balance` (number),
`accrued` (number), `taken` (number), `units` (string: days/hours).

| | |
|---|---|
| Server-internal | `employee_id` (correlation), `category`, `balance`, `accrued`, `taken`, `units` |
| Model-visible | per-service totals and averages (e.g. mean remaining annual leave, % of entitlement used) |
| Blocked | any per-person balance |

### Certifications (`employees_certifications:list`)

Per-employee endpoint `GET /api/v1/organisations/{org}/employees/{id}/certifications`
(the org-level `/certifications` endpoint needs a `certifications:list` scope we
do NOT hold). Training compliance iterates employees.

| | |
|---|---|
| Server-internal | `employee_id` (correlation), cert `name`/`type`, `status`, `expiry_date`, `completion_date` |
| Model-visible | per-service compliance % (against the `mandatory_cert_names` / `safety_cert_names` config allowlists), counts compliant/total, counts expiring within the warning window |
| Blocked | per-person certification lists or statuses, document/attachment fields, licence numbers |

### Timesheets and rosters (Phase 2)

Endpoints (confirmed from the Postman collection):
- Timesheets are **per-employee**:
  `GET /api/v1/organisations/{org}/employees/{id}/timesheet_entries?start_date=&end_date=`
  — care-hours KPIs iterate employees. Fields: `date`, `start_time`, `end_time`,
  `units` (hours), `breaks[]`, `position_id`, `comment`.
- Rostered shifts are **org-scoped and location-filterable**:
  `GET /api/v1/organisations/{org}/rostered_shifts?from_date=&to_date=&statuses=&location_ids=&member_ids=`
  — delivery/coverage by work location in one query. Fields: `start_date_time`,
  `end_date_time`, `member_ids`, `breaks[]`, `notes`, `published`, status.

| | |
|---|---|
| Server-internal | `employee_id` / `member_ids` (correlation), shift/entry start/end times, `units`/hours, `breaks`, `location_ids`, `position_id`, work type / pay category ids, shift status |
| Model-visible | per-service aggregates: total care hours, overtime % (via the pay-category mapping in config), rostered vs delivered hours, lateness % beyond the grace period, unfilled-shift counts |
| Blocked | per-person rows, individual shift times tied to a person, `notes`/`comment` free text |

### Shift cost (`employees:rostered_shifts:shift_cost:show`)

| | |
|---|---|
| Server-internal | per-shift cost figures |
| Model-visible | per-service or per-period **totals** only (e.g. staffing cost per service per week) |
| Blocked | any cost tied to an identifiable person or single shift — cost joined with shift + person is effectively pay data |

### Never called at all

`employees:work_eligibility:show` (right-to-work / immigration status) and
`employees:onboard_polling_status`. No tool, no client method, no internal
read. If a future KPI seems to need them, that is a design smell — escalate
instead.

## The organisations gap

The app has **no organisations scope**. Every documented endpoint nests under
`/api/v1/organisations/{org_id}/...`, so:

- `list_organisations` may be refused. Verify on the first live call; it may
  also work if EH treats basic org listing as implicit for the token holder.
- If refused, the organisation ID must come from configuration (an
  `EH_ORG_ID` env var / extension setting) rather than discovery. The tools
  should accept that as the default so directors never have to know an org ID.

## First-live-call verification checklist

Confirm before building the KPI tools on top:

1. Whether `GET /api/v1/organisations` works without an organisations scope.
2. The list envelope shape (`data.items` / `total_pages` / `total_items`).
3. Exact field names on employees (start/termination dates, probation fields,
   status casing) and on leave_requests (`leave_category_name` vs id,
   `total_hours` units — hours vs days).
4. That `leave_categories:list` names match the `sickness_categories` config.
5. Pagination limits (`item_per_page` max) and rate-limit headers.

Use a schema-shaped probe for this (structure and field names only, never
values) so verification itself cannot leak personal data.
