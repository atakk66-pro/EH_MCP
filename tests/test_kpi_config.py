"""Tests for the directors-supplied KPI config loader and its validation."""

import textwrap

import pytest

from eh_mcp.kpi_config import (
    KpiConfig,
    KpiConfigError,
    Thresholds,
    load_kpi_config,
)


def write(tmp_path, text):
    path = tmp_path / "kpi_config.yaml"
    path.write_text(textwrap.dedent(text))
    return str(path)


def test_full_config_loads(tmp_path):
    path = write(
        tmp_path,
        """
        service_grouping: work_location
        sickness_categories: ["Sick Leave"]
        mandatory_cert_names: ["Safeguarding", "Fire Safety"]
        thresholds:
          early_attrition_window_days: 90
          long_term_absence_days: 21
        services:
          - id: "team_1"
            name: "Oak House"
            establishment_headcount: 40
            establishment_fte: 35.5
        """,
    )
    cfg = load_kpi_config(path)
    assert cfg.service_grouping == "work_location"
    assert cfg.sickness_categories == ("Sick Leave",)
    assert cfg.thresholds.early_attrition_window_days == 90
    assert cfg.thresholds.long_term_absence_days == 21
    # Unspecified thresholds fall back to defaults.
    assert cfg.thresholds.bradford_period_weeks == Thresholds().bradford_period_weeks
    assert cfg.services[0].id == "team_1"
    assert cfg.services[0].establishment_fte == 35.5
    assert cfg.service_by_id("team_1").name == "Oak House"


def test_defaults_when_minimal(tmp_path):
    path = write(tmp_path, "service_grouping: team\n")
    cfg = load_kpi_config(path)
    assert cfg.thresholds == Thresholds()
    assert cfg.services == ()
    assert cfg.sickness_categories == ()


def test_invalid_service_grouping_rejected(tmp_path):
    path = write(tmp_path, "service_grouping: region\n")
    with pytest.raises(KpiConfigError) as exc:
        load_kpi_config(path)
    assert "service_grouping" in str(exc.value)


def test_bad_threshold_type_rejected(tmp_path):
    path = write(
        tmp_path,
        """
        service_grouping: team
        thresholds:
          long_term_absence_days: "twenty-eight"
        """,
    )
    with pytest.raises(KpiConfigError):
        load_kpi_config(path)


def test_service_missing_name_rejected(tmp_path):
    path = write(
        tmp_path,
        """
        service_grouping: team
        services:
          - id: "team_1"
        """,
    )
    with pytest.raises(KpiConfigError):
        load_kpi_config(path)


def test_negative_number_rejected(tmp_path):
    path = write(
        tmp_path,
        """
        service_grouping: team
        services:
          - id: "team_1"
            name: "Oak House"
            establishment_headcount: -5
        """,
    )
    with pytest.raises(KpiConfigError):
        load_kpi_config(path)


def test_placeholder_id_warns_not_fails(tmp_path):
    path = write(
        tmp_path,
        """
        service_grouping: team
        services:
          - id: "REPLACE_WITH_EH_TEAM_ID"
            name: "Example Care Home"
        """,
    )
    cfg = load_kpi_config(path)
    assert any("placeholder" in w for w in cfg.warnings)


def test_unknown_top_level_key_warns(tmp_path):
    path = write(
        tmp_path,
        """
        service_grouping: team
        revenue_target: 1000000
        """,
    )
    cfg = load_kpi_config(path)
    assert any("revenue_target" in w for w in cfg.warnings)


def test_missing_file_raises(tmp_path):
    with pytest.raises(KpiConfigError):
        load_kpi_config(str(tmp_path / "nope.yaml"))


def test_example_file_is_valid():
    # The committed example must always load cleanly.
    cfg = load_kpi_config("kpi_config.example.yaml")
    assert cfg.service_grouping in ("team", "department", "work_location", "cost_centre")
    assert isinstance(cfg, KpiConfig)
