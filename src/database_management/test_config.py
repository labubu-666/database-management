import logging
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from database_management.config import Settings, load_settings


def test_defaults_when_nothing_is_set():
    settings = load_settings()
    assert settings.host == "postgres"
    assert settings.port == 5432
    assert settings.dbname == "postgres"
    assert settings.user == "postgres"
    assert settings.password.get_secret_value() == "postgres"
    assert settings.interval_seconds == 3600
    assert settings.targets == ()
    assert settings.staging_dir == Path(tempfile.gettempdir()) / "postgres-backup"
    assert settings.keep == 7


@pytest.mark.parametrize(
    ("unrelated_var", "field", "default"),
    [("USER", "user", "postgres"), ("HOST", "host", "postgres")],
)
def test_unrelated_shell_variables_do_not_leak_into_settings(
    monkeypatch, unrelated_var, field, default
):
    monkeypatch.setenv(unrelated_var, "someone-else")
    assert getattr(load_settings(), field) == default


@pytest.mark.parametrize(
    ("var", "value", "field", "expected"),
    [
        ("POSTGRES_HOST", "db.local", "host", "db.local"),
        ("POSTGRES_PORT", "6543", "port", 6543),
        ("POSTGRES_DB", "app", "dbname", "app"),
        ("POSTGRES_USER", "backup", "user", "backup"),
        ("BACKUP_INTERVAL_SECONDS", "60", "interval_seconds", 60),
        ("BACKUP_STAGING_DIR", "/data/stage", "staging_dir", Path("/data/stage")),
        ("BACKUP_KEEP", "3", "keep", 3),
    ],
)
def test_env_variable_maps_to_field(monkeypatch, var, value, field, expected):
    monkeypatch.setenv(var, value)
    assert getattr(load_settings(), field) == expected


def test_password_is_secret(monkeypatch):
    monkeypatch.setenv("POSTGRES_PASSWORD", "hunter2")
    settings = load_settings()
    assert settings.password.get_secret_value() == "hunter2"
    assert "hunter2" not in repr(settings)
    assert "hunter2" not in str(settings)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("file:///a,file:///b", ("file:///a", "file:///b")),
        ("file:///a, file:///b  file:///c", ("file:///a", "file:///b", "file:///c")),
        ("  file:///a  ", ("file:///a",)),
        ("", ()),
    ],
)
def test_env_targets_split_on_commas_and_spaces(monkeypatch, raw, expected):
    monkeypatch.setenv("BACKUP_TARGETS", raw)
    assert load_settings().targets == expected


def test_keyword_overrides_beat_environment(monkeypatch):
    monkeypatch.setenv("BACKUP_KEEP", "2")
    monkeypatch.setenv("BACKUP_TARGETS", "file:///from/env")
    settings = load_settings(keep=5, targets=("file:///from/flag",))
    assert settings.keep == 5
    assert settings.targets == ("file:///from/flag",)


def test_values_are_read_from_dotenv_in_current_directory(isolated_config):
    (isolated_config / ".env").write_text("POSTGRES_HOST=from-dotenv\nUNUSED=1\n")
    assert load_settings().host == "from-dotenv"


def test_environment_beats_dotenv(isolated_config, monkeypatch):
    (isolated_config / ".env").write_text("POSTGRES_HOST=from-dotenv\n")
    monkeypatch.setenv("POSTGRES_HOST", "from-env")
    assert load_settings().host == "from-env"


@pytest.mark.parametrize(
    ("var", "value"),
    [
        ("BACKUP_KEEP", "0"),
        ("BACKUP_KEEP", "abc"),
        ("BACKUP_INTERVAL_SECONDS", "0"),
        ("POSTGRES_PORT", "x"),
        ("POSTGRES_PORT", "70000"),
    ],
)
def test_invalid_values_are_rejected(monkeypatch, var, value):
    monkeypatch.setenv(var, value)
    with pytest.raises(ValidationError):
        load_settings()


def test_log_summary_lists_every_field_and_hides_password(monkeypatch, caplog):
    monkeypatch.setenv("POSTGRES_PASSWORD", "hunter2")
    monkeypatch.setenv("BACKUP_TARGETS", "file:///a,file:///b")
    settings = load_settings()

    with caplog.at_level(logging.INFO, logger="database_management.config"):
        settings.log_summary()

    text = caplog.text
    for field in Settings.model_fields:
        assert field in text
    assert "file:///a, file:///b" in text
    assert "hunter2" not in text


def test_log_summary_can_exclude_fields(caplog):
    with caplog.at_level(logging.INFO, logger="database_management.config"):
        load_settings().log_summary(exclude=frozenset({"interval_seconds"}))
    assert "interval_seconds" not in caplog.text
    assert "keep" in caplog.text
