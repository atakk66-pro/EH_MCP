"""Directors-supplied KPI configuration.

None of this exists in Employment Hero, so it is supplied here: which dimension
counts as a "service", which leave categories are sickness, which certificates
are mandatory/safety, the KPI thresholds, and the per-service
establishment/budget/target figures the Phase 4 KPIs need.

The file is keyed by Employment Hero IDs and names only. It must never contain
personal data, which preserves the server's allowlist posture.

Validate a file with:  python -m eh_mcp.kpi_config [path]
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any

import yaml

DEFAULT_PATH = os.environ.get("EH_KPI_CONFIG", "kpi_config.yaml")
# department and position are NOT readable via the Controls API (no Read scope —
# only Update/Create), so they cannot be a service grouping. Confirmed from the
# Developer Portal "Add New Application" scope list.
ALLOWED_GROUPINGS = ("team", "work_location", "cost_centre")
ALLOWED_ATTRITION_MODES = ("fixed_days", "within_probation")

_KNOWN_TOP_LEVEL = {
    "service_grouping",
    "sickness_categories",
    "annual_leave_categories",
    "mandatory_cert_names",
    "safety_cert_names",
    "thresholds",
    "services",
}
_KNOWN_SERVICE_KEYS = {
    "id",
    "name",
    "establishment_headcount",
    "establishment_fte",
    "budgeted_hours_per_period",
    "contracted_hours_per_period",
    "leave_entitlement_days",
}


class KpiConfigError(RuntimeError):
    """Raised when the KPI config file is missing or fails validation."""


@dataclass(frozen=True)
class Thresholds:
    early_attrition_window_days: int = 180
    early_attrition_mode: str = "fixed_days"
    long_term_absence_days: int = 28
    bradford_period_weeks: int = 52
    cert_expiry_warning_days: int = 30
    lateness_grace_minutes: int = 5


@dataclass(frozen=True)
class ServiceTarget:
    id: str
    name: str
    establishment_headcount: int | None = None
    establishment_fte: float | None = None
    budgeted_hours_per_period: float | None = None
    contracted_hours_per_period: float | None = None
    leave_entitlement_days: float | None = None


@dataclass(frozen=True)
class KpiConfig:
    service_grouping: str
    sickness_categories: tuple[str, ...] = ()
    annual_leave_categories: tuple[str, ...] = ()
    mandatory_cert_names: tuple[str, ...] = ()
    safety_cert_names: tuple[str, ...] = ()
    thresholds: Thresholds = field(default_factory=Thresholds)
    services: tuple[ServiceTarget, ...] = ()
    warnings: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> KpiConfig:
        if not isinstance(raw, dict):
            raise KpiConfigError("Config root must be a mapping (YAML object).")

        warnings = [
            f"Unknown top-level key ignored: {k}"
            for k in raw
            if k not in _KNOWN_TOP_LEVEL
        ]

        grouping = raw.get("service_grouping", "team")
        if grouping not in ALLOWED_GROUPINGS:
            raise KpiConfigError(
                f"service_grouping must be one of {ALLOWED_GROUPINGS}, got {grouping!r}."
            )

        thresholds = _parse_thresholds(raw.get("thresholds", {}) or {})
        services = tuple(
            _parse_service(s, i) for i, s in enumerate(raw.get("services", []) or [])
        )
        for s in services:
            warnings.extend(s_warn for s_warn in _service_warnings(s))

        return cls(
            service_grouping=grouping,
            sickness_categories=_str_tuple(raw, "sickness_categories"),
            annual_leave_categories=_str_tuple(raw, "annual_leave_categories"),
            mandatory_cert_names=_str_tuple(raw, "mandatory_cert_names"),
            safety_cert_names=_str_tuple(raw, "safety_cert_names"),
            thresholds=thresholds,
            services=services,
            warnings=tuple(warnings),
        )

    def service_by_id(self, service_id: str) -> ServiceTarget | None:
        for s in self.services:
            if s.id == service_id:
                return s
        return None


def load_kpi_config(path: str | None = None) -> KpiConfig:
    path = path or DEFAULT_PATH
    if not os.path.exists(path):
        raise KpiConfigError(
            f"No KPI config at {path}. Copy kpi_config.example.yaml to {path} and "
            "fill it in (or set EH_KPI_CONFIG to its path)."
        )
    with open(path) as f:
        try:
            raw = yaml.safe_load(f) or {}
        except yaml.YAMLError as exc:
            raise KpiConfigError(f"Could not parse YAML in {path}: {exc}") from exc
    return KpiConfig.from_dict(raw)


# -- parsing helpers -----------------------------------------------------


def _str_tuple(raw: dict[str, Any], key: str) -> tuple[str, ...]:
    value = raw.get(key, []) or []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise KpiConfigError(f"{key} must be a list of strings.")
    return tuple(value)


def _parse_thresholds(raw: dict[str, Any]) -> Thresholds:
    if not isinstance(raw, dict):
        raise KpiConfigError("thresholds must be a mapping.")
    defaults = Thresholds()
    mode = raw.get("early_attrition_mode", defaults.early_attrition_mode)
    if mode not in ALLOWED_ATTRITION_MODES:
        raise KpiConfigError(
            f"thresholds.early_attrition_mode must be one of "
            f"{ALLOWED_ATTRITION_MODES}, got {mode!r}."
        )
    return Thresholds(
        early_attrition_window_days=_pos_int(
            raw, "early_attrition_window_days", defaults.early_attrition_window_days
        ),
        early_attrition_mode=mode,
        long_term_absence_days=_pos_int(
            raw, "long_term_absence_days", defaults.long_term_absence_days
        ),
        bradford_period_weeks=_pos_int(
            raw, "bradford_period_weeks", defaults.bradford_period_weeks
        ),
        cert_expiry_warning_days=_pos_int(
            raw, "cert_expiry_warning_days", defaults.cert_expiry_warning_days
        ),
        lateness_grace_minutes=_pos_int(
            raw, "lateness_grace_minutes", defaults.lateness_grace_minutes
        ),
    )


def _parse_service(raw: Any, index: int) -> ServiceTarget:
    if not isinstance(raw, dict):
        raise KpiConfigError(f"services[{index}] must be a mapping.")
    if not raw.get("id") or not raw.get("name"):
        raise KpiConfigError(f"services[{index}] needs both an id and a name.")
    return ServiceTarget(
        id=str(raw["id"]),
        name=str(raw["name"]),
        establishment_headcount=_opt_number(raw, "establishment_headcount", index, int),
        establishment_fte=_opt_number(raw, "establishment_fte", index, float),
        budgeted_hours_per_period=_opt_number(
            raw, "budgeted_hours_per_period", index, float
        ),
        contracted_hours_per_period=_opt_number(
            raw, "contracted_hours_per_period", index, float
        ),
        leave_entitlement_days=_opt_number(raw, "leave_entitlement_days", index, float),
    )


def _service_warnings(service: ServiceTarget) -> list[str]:
    # Surfaced, not fatal: placeholder ids left unedited.
    if service.id.startswith("REPLACE_"):
        return [f"service {service.name!r} still has a placeholder id ({service.id})."]
    return []


def _pos_int(raw: dict[str, Any], key: str, default: int) -> int:
    if key not in raw:
        return default
    value = raw[key]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise KpiConfigError(f"thresholds.{key} must be a non-negative integer.")
    return value


def _opt_number(raw: dict[str, Any], key: str, index: int, cast):
    if key not in raw or raw[key] is None:
        return None
    value = raw[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise KpiConfigError(
            f"services[{index}].{key} must be a non-negative number if present."
        )
    return cast(value)


# -- CLI validator -------------------------------------------------------


def _cli() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PATH
    try:
        cfg = load_kpi_config(path)
    except KpiConfigError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"OK: {path}")
    print(f"  service_grouping: {cfg.service_grouping}")
    print(f"  sickness_categories: {len(cfg.sickness_categories)}")
    print(f"  mandatory_cert_names: {len(cfg.mandatory_cert_names)}")
    print(f"  safety_cert_names: {len(cfg.safety_cert_names)}")
    print(f"  services: {len(cfg.services)}")
    for w in cfg.warnings:
        print(f"  WARNING: {w}")


if __name__ == "__main__":
    _cli()
