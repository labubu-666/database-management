import subprocess
from pathlib import Path
from unittest import mock

import pytest

from database_management import core
from database_management.backends import (
    BackupArtifact,
    BaseBackend,
    backend_for_uri,
    parse_targets,
)
from database_management.config import Settings


def make_settings(tmp_path: Path, targets: tuple[str, ...] = ()) -> Settings:
    return Settings(
        host="localhost",
        port=5432,
        dbname="postgres",
        user="postgres",
        password="postgres",
        interval_seconds=15,
        targets=targets,
        staging_dir=tmp_path / "staging",
    )


def write_dump(path: Path, content: bytes = b"dump-bytes") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


class FailingBackend(BaseBackend):
    schemes = ("fail",)

    def store(self, artifact: BackupArtifact) -> str:
        raise RuntimeError("boom")

    def list_backups(self, dbname: str) -> list[str]:
        return []

    def delete(self, name: str) -> None:
        raise RuntimeError("boom")


def test_backend_for_uri_rejects_unknown_scheme():
    with pytest.raises(ValueError, match="Unsupported target 'ftp://host/x'"):
        backend_for_uri("ftp://host/x")


def test_backend_for_uri_rejects_missing_scheme():
    with pytest.raises(ValueError, match="Unsupported target './backups'"):
        backend_for_uri("./backups")


def test_parse_targets_removes_duplicates_and_keeps_order(tmp_path):
    a, b = f"file://{tmp_path}/a", f"file://{tmp_path}/b"
    backends = parse_targets([a, b, a])
    assert [t.uri for t in backends] == [a, b]


def test_parse_targets_passes_keep_to_every_backend(tmp_path):
    backends = parse_targets([f"file://{tmp_path}/a", f"file://{tmp_path}/b"], keep=3)
    assert [t.keep for t in backends] == [3, 3]


def test_save_returns_false_when_store_fails(tmp_path):
    staged = write_dump(tmp_path / "db_ts.dump.partial")
    backend = FailingBackend.from_uri("fail://x")
    assert backend.save(BackupArtifact("db", "ts", staged)) is False


def test_dump_database_skips_save_when_pg_dump_fails(tmp_path):
    settings = make_settings(tmp_path)
    target = mock.Mock()
    failed = subprocess.CompletedProcess(args=[], returncode=1, stderr="nope")

    with mock.patch("database_management.core.subprocess.run", return_value=failed):
        ok = core.dump_database(settings, [target], "db", "ts")

    assert ok is False
    target.save.assert_not_called()
    assert list(settings.staging_dir.glob("*")) == []


def test_dump_database_saves_to_every_target_and_cleans_staging(tmp_path):
    settings = make_settings(tmp_path)
    first = mock.Mock()
    first.save.return_value = True
    second = mock.Mock()
    second.save.return_value = False

    def fake_run(cmd, **kwargs):
        write_dump(Path(cmd[cmd.index("--file") + 1]))
        return subprocess.CompletedProcess(args=cmd, returncode=0, stderr="")

    with mock.patch("database_management.core.subprocess.run", side_effect=fake_run):
        ok = core.dump_database(settings, [first, second], "db", "ts")

    assert ok is False  # one target failed, so the database is not fully backed up
    first.save.assert_called_once()
    second.save.assert_called_once()
    assert first.save.call_args.args[0].name == "db_ts.dump"
    assert list(settings.staging_dir.glob("*")) == []


def test_cli_requires_a_target():
    from click.testing import CliRunner

    from database_management.cli import main

    result = CliRunner().invoke(main, ["backup"])

    assert result.exit_code == 1
    assert "No targets given" in result.output


def test_cli_target_flag_overrides_env(monkeypatch):
    from database_management.cli import _load_settings

    monkeypatch.setenv("BACKUP_TARGETS", "file:///from/env")
    assert _load_settings(("file:///from/flag",)).targets == ("file:///from/flag",)
    assert _load_settings(()).targets == ("file:///from/env",)


def test_cli_keep_flag_overrides_env(monkeypatch):
    from database_management.cli import _load_settings

    monkeypatch.setenv("BACKUP_KEEP", "2")
    assert _load_settings((), keep=5).keep == 5
    assert _load_settings(()).keep == 2
